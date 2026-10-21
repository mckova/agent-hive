from __future__ import annotations

import math
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from .gate import evaluate_gate
from .planner import iso_now
from .protocol import compile_payload
from .usage import add_metrics, next_ready_cells, normalize_metrics, record_cell_usage, summarize_usage
from .usage import METRIC_FIELDS, invalidate_stale_results, quarantine_interrupted
from .protocol import dependency_handoff

FINAL_STATUSES = {"done", "partial", "blocked", "failed"}


def run_hive(*, plan: dict[str, Any], driver: Any, usage: dict[str, Any] | None = None,
             run_state: dict[str, Any] | None = None, target: str = "generic", workspace: str | None = None,
             model: str | None = None, timeout_ms: float | None = None, approvals: list[str] | None = None,
             dry_run: bool = False, resume_blocked: bool = False,
             on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
             clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    if not isinstance(plan, dict) or not isinstance(plan.get("cells"), list):
        raise ValueError("runHive requires a plan.")
    if not callable(getattr(driver, "run_cell", None)):
        raise ValueError("runHive requires a driver.")
    if not dry_run and not any(cell["role"] == "guard" and cell.get("required") is not False for cell in plan["cells"]):
        raise ValueError("hive run requires at least one required guard cell.")
    validate_run_guards(plan)
    if plan.get("budget", {}).get("unit") not in {"tokens", "usd-micros"}:
        raise ValueError(f"hive run supports budget units tokens or usd-micros, not {plan.get('budget', {}).get('unit')}.")
    clock = clock or (lambda: datetime.now(timezone.utc))
    checkpoint = on_checkpoint or (lambda _event: None)
    approved = set(approvals or [])
    current_usage = invalidate_stale_results(plan, quarantine_interrupted(usage or {"schemaVersion": 1, "cells": {}}))
    current_usage.setdefault("schemaVersion", 1); current_usage.setdefault("cells", {}); current_usage.setdefault("updatedAt", iso_now(clock()))
    state = deepcopy(run_state) if run_state else _new_run_state(target, getattr(driver, "name", target), workspace, clock)
    if state.get("workspace") and workspace and state["workspace"] != workspace:
        raise ValueError(f"Cannot resume workspace {state['workspace']} in {workspace}.")
    state.setdefault("history", []); state.setdefault("repairs", {})
    state.update({"target": target, "driver": getattr(driver, "name", target), "status": "dry_run" if dry_run else "running",
                  "reason": None, "finishedAt": None, "updatedAt": iso_now(clock())})
    state["workspace"] = state.get("workspace") or workspace
    state.pop("gate", None)
    if resume_blocked:
        current_usage = _reset_retryable_cells(plan, current_usage)

    def emit(event_type: str, detail: dict[str, Any] | None = None) -> None:
        state["updatedAt"] = iso_now(clock())
        checkpoint({"type": event_type, "state": deepcopy(state), "usage": deepcopy(current_usage), "detail": detail or {}})

    def finish(status: str, reason: str) -> dict[str, Any]:
        state.update({"status": status, "reason": reason, "currentCell": None, "updatedAt": iso_now(clock())})
        if status in {"completed", "budget_exhausted", "blocked"}:
            state["finishedAt"] = state["updatedAt"]
        emit("run_finished", {"status": status, "reason": reason})
        return {"state": state, "usage": current_usage, "summary": summarize_usage(plan, current_usage)}

    if dry_run:
        state["schedule"] = deepcopy(plan["waves"])
        state["gates"] = [gate for cell in plan["cells"] for gate in _gate_cell(plan, cell, approved)]
        state["reason"] = "gate_attention_required" if any(not gate["allowed"] for gate in state["gates"]) else "ready"
        emit("dry_run")
        return {"state": state, "usage": current_usage, "summary": summarize_usage(plan, current_usage)}

    max_executions = max(1, len(plan["cells"]) * plan.get("guardrails", {}).get("maxAttemptsPerCell", 2) * 2)
    executions = 0
    while executions < max_executions:
        summary = summarize_usage(plan, current_usage)
        if not summary["usageKnown"]:
            identifier = next(row["id"] for row in summary["rows"] if not row["usageKnown"])
            return finish("blocked", f"usage_reconciliation_required:{identifier}")
        spendable = summary["total"] - summary["effectiveReserve"]
        ready = next_ready_cells(plan, current_usage)
        if not ready:
            required_done = all((current_usage["cells"].get(cell["id"], {}).get("status") or cell.get("status")) == "done"
                                for cell in plan["cells"] if cell.get("required") is not False)
            if required_done:
                return finish("completed", "required_done_budget_closed" if summary["used"] >= spendable else "all_required_cells_done")
            if summary["used"] >= spendable:
                return finish("budget_exhausted", "spendable_budget_reached")
            return finish("blocked", _blocking_reason(plan, current_usage))
        for cell in ready:
            live = summarize_usage(plan, current_usage)
            if live["used"] >= live["total"] - live["effectiveReserve"]:
                return finish("budget_exhausted", "spendable_budget_reached")
            previous = current_usage["cells"].get(cell["id"], {})
            attempts_limit = plan.get("guardrails", {}).get("maxAttemptsPerCell", 2)
            if previous.get("attempts", 0) >= attempts_limit:
                return finish("blocked", f"attempt_limit_reached:{cell['id']}")
            if previous.get("used", 0) >= cell["allocation"]:
                return finish("blocked", f"cell_allocation_exhausted:{cell['id']}")
            gates = _gate_cell(plan, cell, approved)
            denied = next((gate for gate in gates if not gate["allowed"]), None)
            if denied:
                state.update({"currentCell": cell["id"], "gate": denied})
                return finish("blocked", denied["reason"])
            current_usage = record_cell_usage(plan, current_usage, {"id": cell["id"], "status": "in_progress",
                "used": previous.get("used", 0), "attempts": previous.get("attempts", 0) + 1, "metrics": previous.get("metrics"),
                "usageKnown": False, "unknownAttempts": previous.get("unknownAttempts", 0) + 1,
                "artifacts": previous.get("artifacts"), "evidence": previous.get("evidence"), "blockers": previous.get("blockers"),
                "reusableContext": previous.get("reusableContext")}, clock())
            state["currentCell"] = cell["id"]
            emit("cell_started", {"cell": cell["id"]})
            started = clock()
            try:
                result = _normalize_result(driver.run_cell({"cell": cell, "plan": plan, "target": target, "workspace": workspace,
                    "model": model or plan.get("models", {}).get(cell["modelTier"], {}).get(target),
                    "prompt": compile_payload(plan, cell, target) + dependency_handoff(plan, cell, current_usage),
                    "repairContext": state.get("repairs", {}).get(cell["id"], []),
                    "timeoutMs": timeout_ms}))
            except Exception as error:
                result = _normalize_result({"status": "failed", "blockers": [str(error)], "metrics": {}})
            unit = plan["budget"]["unit"]
            known = result["telemetry"]["tokensReported" if unit == "tokens" else "costReported"]
            if unit == "tokens" and not known:
                result["status"] = "blocked"; result["blockers"].append("Driver did not report token usage; the token budget cannot be enforced safely.")
            if unit == "usd-micros" and not known:
                result["status"] = "blocked"; result["blockers"].append("Driver did not report costUsd; the cost budget cannot be enforced safely.")
            if result["status"] == "done" and not result["evidence"]:
                result["status"] = "partial"; result["blockers"].append("Worker claimed done without verifiable evidence.")
            finished = clock()
            if not result["metrics"]["latencyMs"]:
                result["metrics"]["latencyMs"] = max(0, int((finished - started).total_seconds() * 1000))
            cumulative_metrics = add_metrics(previous.get("metrics"), result["metrics"])
            available = set(result["telemetry"]["availableMetrics"])
            if previous.get("attempts", 0):
                available.intersection_update(previous.get("metricsAvailable", []))
            cumulative_used = previous.get("used", 0) + _spent_for(unit, result["metrics"])
            current_usage = record_cell_usage(plan, current_usage, {"id": cell["id"], "status": result["status"],
                "used": cumulative_used, "attempts": previous.get("attempts", 0) + 1, "metrics": cumulative_metrics,
                "usageKnown": known, "unknownAttempts": 0 if known else 1,
                "metricsAvailable": sorted(available), "reasoningTokensKnown": "reasoningTokens" in available,
                "artifacts": _unique([*(previous.get("artifacts") or []), *result["artifacts"]]),
                "evidence": _unique([*(previous.get("evidence") or []), *result["evidence"]]), "blockers": result["blockers"],
                "reusableContext": _unique([*(previous.get("reusableContext") or []), *result["reusableContext"]])}, finished,
                resolve_unknown=known)
            executions += 1
            state["history"].append({"cell": cell["id"], "attempt": current_usage["cells"][cell["id"]]["attempts"],
                "status": result["status"], "startedAt": iso_now(started), "finishedAt": iso_now(finished), "metrics": result["metrics"],
                "artifactCount": len(result["artifacts"]), "evidenceCount": len(result["evidence"]), "blockerCount": len(result["blockers"])})
            emit("cell_finished", {"cell": cell["id"], "result": result["status"]})
            if not known:
                return finish("blocked", f"usage_reconciliation_required:{cell['id']}")
            after = summarize_usage(plan, current_usage)
            if after["used"] >= after["total"] - after["effectiveReserve"]:
                return finish("budget_exhausted", "spendable_budget_reached")
            if cumulative_used > cell["allocation"]:
                return finish("blocked", f"cell_allocation_overrun:{cell['id']}")
            attempts_limit = plan.get("guardrails", {}).get("maxAttemptsPerCell", 2)
            if result["status"] in {"partial", "failed"} and current_usage["cells"][cell["id"]]["attempts"] < attempts_limit:
                if cumulative_used >= cell["allocation"]:
                    return finish("blocked", f"cell_allocation_exhausted:{cell['id']}")
                state.setdefault("repairs", {})[cell["id"]] = result["blockers"] or ["Previous attempt did not satisfy the return contract."]
                stored = current_usage["cells"][cell["id"]]
                current_usage = record_cell_usage(plan, current_usage, {"id": cell["id"], "status": "pending", "used": cumulative_used,
                    "attempts": stored["attempts"], "metrics": cumulative_metrics, "artifacts": stored["artifacts"],
                    "evidence": stored["evidence"], "blockers": stored["blockers"], "reusableContext": stored["reusableContext"]}, finished)
                emit("cell_retry_scheduled", {"cell": cell["id"]})
            elif result["status"] != "done":
                return finish("blocked", "worker_requires_input" if result["status"] == "blocked" else "attempt_limit_reached")
    return finish("blocked", "execution_safety_limit")


def _new_run_state(target: str, driver: str, workspace: str | None, clock: Callable[[], datetime]) -> dict[str, Any]:
    now = iso_now(clock())
    return {"schemaVersion": 1, "runId": str(uuid.uuid4()), "target": target, "driver": driver, "workspace": workspace,
            "status": "pending", "reason": None, "currentCell": None, "startedAt": now, "updatedAt": now,
            "finishedAt": None, "repairs": {}, "history": []}


def _gate_cell(plan: dict[str, Any], cell: dict[str, Any], approvals: set[str]) -> list[dict[str, Any]]:
    actions = cell.get("actions") or (["write"] if cell["role"] == "builder" else ["read"])
    return [evaluate_gate(plan, {"action": action, "paths": cell.get("paths") or [], "humanApproved": action in approvals}) for action in actions]


def _normalize_result(value: dict[str, Any] | None = None) -> dict[str, Any]:
    value = value or {}; raw_metrics = value.get("metrics") or {}
    return {"status": value.get("status") if value.get("status") in FINAL_STATUSES else "partial",
            "artifacts": _strings(value.get("artifacts")), "evidence": _strings(value.get("evidence")),
            "blockers": _strings(value.get("blockers")), "reusableContext": _strings(value.get("reusableContext") or value.get("reusable_context")),
            "metrics": _runner_metrics(raw_metrics), "telemetry": {
                "tokensReported": value.get("usageComplete", True) is True and
                    all(_integer_non_negative(raw_metrics.get(field)) for field in ("inputTokens", "outputTokens")),
                "reasoningReported": _integer_non_negative(raw_metrics.get("reasoningTokens")),
                "availableMetrics": [field for field, number in raw_metrics.items()
                                     if field in METRIC_FIELDS and value.get("usageComplete", True) is True and
                                     (_finite_non_negative(number) if field == "costUsd" else _integer_non_negative(number))],
                "costReported": value.get("usageComplete", True) is True and _finite_non_negative(raw_metrics.get("costUsd"))}}


def _runner_metrics(value: dict[str, Any]) -> dict[str, int | float]:
    # Invalid/missing fields are absent knowledge, not fabricated spend. Numeric zeros
    # remain a lower-bound display until telemetry/reconciliation establishes completeness.
    result = normalize_metrics({key: number for key, number in value.items()
                                if _finite_non_negative(number) and (key == "costUsd" or _integer_non_negative(number))})
    result["modelCalls"] = _non_negative(value.get("modelCalls"), 1)
    return result


def _spent_for(unit: str, metrics: dict[str, Any]) -> int:
    if unit == "usd-micros":
        return round(metrics["costUsd"] * 1_000_000)
    if unit != "tokens":
        raise ValueError(f"hive run supports budget units tokens or usd-micros, not {unit}.")
    # Drivers report reasoning as a diagnostic subset of output, never extra billable tokens.
    return int(metrics["inputTokens"] + metrics["outputTokens"])


def _reset_retryable_cells(plan: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(usage)
    for cell in plan["cells"]:
        record = result.get("cells", {}).get(cell["id"])
        if record and record.get("usageKnown", True) is True and record.get("status") in {"blocked", "partial", "failed"} and record.get("attempts", 0) < plan.get("guardrails", {}).get("maxAttemptsPerCell", 2):
            record["status"] = "pending"
    return result


def validate_run_guards(plan: dict[str, Any]) -> None:
    """Every declared artifact mutation needs a distinct required downstream read guard."""
    cells = {cell["id"]: cell for cell in plan["cells"]}
    mutations = {"write", "delete", "external-write"}
    guards = []
    for cell in plan["cells"]:
        actions = set(cell.get("actions") or (["write"] if cell["role"] == "builder" else ["read"]))
        if cell["role"] == "guard":
            if actions - {"read", "network"}:
                raise ValueError(f"Guard {cell['id']} must declare only read/network actions.")
            if cell.get("required") is not False:
                guards.append(cell)

    def ancestors(identifier: str, seen: set[str] | None = None) -> set[str]:
        seen = set(seen or ())
        for dependency in cells[identifier]["dependencies"]:
            if dependency not in seen:
                seen.add(dependency)
                seen.update(ancestors(dependency, seen))
        return seen

    guarded = set().union(*(ancestors(guard["id"]) for guard in guards)) if guards else set()
    for cell in plan["cells"]:
        actions = set(cell.get("actions") or (["write"] if cell["role"] == "builder" else ["read"]))
        if actions & mutations and cell["id"] not in guarded:
            raise ValueError(f"Write-producing cell {cell['id']} requires a required downstream guard cell.")


def _blocking_reason(plan: dict[str, Any], usage: dict[str, Any]) -> str:
    row = next((cell for cell in plan["cells"] if usage.get("cells", {}).get(cell["id"], {}).get("status") in {"blocked", "partial", "failed"}), None)
    return f"cell_{usage['cells'][row['id']]['status']}:{row['id']}" if row else "no_ready_cells"


def _strings(value: Any) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _non_negative(value: Any, fallback: int = 0) -> int:
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number >= 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _finite_non_negative(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        number = float(value)
        return math.isfinite(number) and number >= 0
    except (TypeError, ValueError):
        return False


def _integer_non_negative(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
