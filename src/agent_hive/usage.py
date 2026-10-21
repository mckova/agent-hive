from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime
from typing import Any

from .planner import allocate, iso_now

METRIC_FIELDS = ("modelCalls", "inputTokens", "cachedInputTokens", "outputTokens", "reasoningTokens", "latencyMs", "costUsd")


def normalize_metrics(value: dict[str, Any] | None = None) -> dict[str, int | float]:
    value = value or {}
    result: dict[str, int | float] = {}
    for field in METRIC_FIELDS:
        try:
            number = float(value.get(field, 0))
        except (TypeError, ValueError):
            number = 0
        if not math.isfinite(number):
            number = 0
        number = max(0, number)
        result[field] = number if field == "costUsd" else int(number)
    return result


def add_metrics(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, int | float]:
    a, b = normalize_metrics(left), normalize_metrics(right)
    return {field: a[field] + b[field] for field in METRIC_FIELDS}


def summarize_usage(plan: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    records = (usage or {}).get("cells", {})
    rows = []
    for cell in plan["cells"]:
        record = records.get(cell["id"], {})
        used = max(0, int(_number(record.get("used"), 0)))
        status = record.get("status") or cell.get("status") or "pending"
        known = usage_is_known(record, status)
        rows.append({"id": cell["id"], "role": cell["role"], "status": status,
                     "allocation": cell["allocation"], "used": used, "remaining": max(0, cell["allocation"] - used),
                     "usageKnown": known, "unknownAttempts": record.get("unknownAttempts", 0),
                     "metricsAvailable": record.get("metricsAvailable", []),
                     "burnPercent": round(used / cell["allocation"] * 100) if cell["allocation"] else 0,
                     "attempts": max(0, int(_number(record.get("attempts"), 0))), "metrics": normalize_metrics(record.get("metrics"))})
    result = {"rows": rows, "used": sum(row["used"] for row in rows), "total": plan["budget"]["total"],
              "reserve": plan["budget"]["reserve"],
              "effectiveReserve": 0 if plan["budget"].get("reserveReleased") else plan["budget"]["reserve"],
              "reserveReleased": bool(plan["budget"].get("reserveReleased")), "metrics": normalize_metrics()}
    result["usageKnown"] = all(row["usageKnown"] for row in rows)
    result["metricsAvailable"] = sorted(set.intersection(*(set(row["metricsAvailable"]) for row in rows
                                        if row["attempts"] > 0))) if any(row["attempts"] > 0 for row in rows) else []
    for row in rows:
        result["metrics"] = add_metrics(result["metrics"], row["metrics"])
    result["alerts"] = usage_alerts(plan, result)
    return result


def usage_alerts(plan: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = []
    spendable = max(1, summary["total"] - summary["effectiveReserve"])
    burn = summary["used"] / spendable
    if burn >= 1:
        alerts.append({"severity": "critical", "code": "budget_gate_closed", "message": f"Used {summary['used']}/{spendable} spendable {plan['budget']['unit']}."})
    elif burn >= 0.8:
        alerts.append({"severity": "warning", "code": "budget_near_limit", "message": f"Used {round(burn * 100)}% of spendable budget."})
    attempts_limit = plan.get("guardrails", {}).get("maxAttemptsPerCell", 2)
    for row in summary["rows"]:
        if not row["usageKnown"]:
            alerts.append({"severity": "critical", "code": "usage_unknown", "cell": row["id"],
                           "message": f"{row['id']} has unaccounted usage. Used is a known lower bound; inspect the outcome and run hive reconcile before dispatch."})
        if row["used"] > row["allocation"]:
            alerts.append({"severity": "warning", "code": "cell_overrun", "cell": row["id"], "message": f"{row['id']} used {row['used']}/{row['allocation']}."})
        if row["status"] in {"blocked", "failed"}:
            alerts.append({"severity": "warning", "code": f"cell_{row['status']}", "cell": row["id"], "message": f"{row['id']} is {row['status']}."})
        if row["attempts"] >= attempts_limit and row["status"] != "done":
            alerts.append({"severity": "critical", "code": "attempt_limit", "cell": row["id"], "message": f"{row['id']} reached its attempt limit."})
    return alerts


def next_ready_cells(plan: dict[str, Any], usage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    records = (usage or {}).get("cells", {})
    summary = summarize_usage(plan, usage)
    if not summary["usageKnown"] or summary["used"] >= plan["budget"]["total"] - summary["effectiveReserve"]:
        return []
    done = {cell["id"] for cell in plan["cells"] if (records.get(cell["id"], {}).get("status") or cell.get("status")) == "done"}
    ready = [cell for cell in plan["cells"] if (records.get(cell["id"], {}).get("status") or cell.get("status") or "pending") == "pending"
             and all(identifier in done for identifier in cell["dependencies"])]
    ready.sort(key=lambda cell: (-cell["priority"], -cell["risk"], cell["id"]))
    return ready[:plan["policy"]["maxWorkers"]]


def record_cell_usage(plan: dict[str, Any], usage: dict[str, Any] | None, record: dict[str, Any],
                      now: datetime | None = None, *, resolve_unknown: bool = False) -> dict[str, Any]:
    if not any(cell["id"] == record.get("id") for cell in plan["cells"]):
        raise ValueError(f"Unknown cell: {record.get('id')}")
    if record.get("status") not in {"pending", "in_progress", "done", "partial", "blocked", "failed"}:
        raise ValueError(f"Invalid cell status: {record.get('status')}")
    if not _is_non_negative_int(record.get("used")):
        raise ValueError("used must be a non-negative integer.")
    output = deepcopy(usage or {})
    output.setdefault("cells", {})
    previous = output["cells"].get(record["id"], {})
    if record["used"] < previous.get("used", 0):
        raise ValueError("Cumulative used cannot decrease.")
    completed = 1 if record["status"] in {"done", "partial", "blocked", "failed"} else 0
    attempts = record.get("attempts")
    if attempts is None:
        attempts = previous.get("attempts", 0) + completed
    if not _is_non_negative_int(attempts):
        raise ValueError("attempts must be a non-negative integer.")
    if attempts < previous.get("attempts", 0):
        raise ValueError("Cumulative attempts cannot decrease.")
    if attempts > plan.get("guardrails", {}).get("maxAttemptsPerCell", 2):
        raise ValueError(f"Attempt limit exceeded for {record['id']}.")
    def pick(name: str, default: Any) -> Any:
        return deepcopy(record[name]) if name in record and record[name] is not None else deepcopy(previous.get(name, default))
    known = pick("usageKnown", True)
    if not isinstance(known, bool):
        raise ValueError("usageKnown must be a boolean.")
    if previous and not usage_is_known(previous) and known and not resolve_unknown:
        raise ValueError("Unknown usage must be resolved with hive reconcile, not record.")
    unknown_attempts = pick("unknownAttempts", 0)
    if not _is_non_negative_int(unknown_attempts):
        raise ValueError("unknownAttempts must be a non-negative integer.")
    if record["status"] == "in_progress":
        known = False
        unknown_attempts = max(1, unknown_attempts)
    if known and unknown_attempts:
        raise ValueError("Known usage cannot retain unknown attempts.")
    output.update({"schemaVersion": 1, "updatedAt": iso_now(now)})
    output["cells"][record["id"]] = {**previous, "status": record["status"], "used": record["used"], "attempts": attempts,
        "metrics": normalize_metrics(record.get("metrics") if record.get("metrics") is not None else previous.get("metrics")),
        "artifacts": pick("artifacts", []), "evidence": pick("evidence", []), "blockers": pick("blockers", []),
        "reusableContext": pick("reusableContext", []), "usageKnown": known, "unknownAttempts": unknown_attempts,
        "reasoningTokensKnown": pick("reasoningTokensKnown", False),
        "metricsAvailable": pick("metricsAvailable", []),
        "revision": previous.get("revision", 0) + 1,
        "dependencyRevisions": {identifier: output["cells"].get(identifier, {}).get("revision", 0)
                                for identifier in next(cell for cell in plan["cells"] if cell["id"] == record["id"])["dependencies"]}
                               if record["status"] == "done" else {}}
    return invalidate_stale_results(plan, output)


def invalidate_stale_results(plan: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    """Invalidate ledger results whose prerequisites changed; never reset spend or attempts."""
    output = deepcopy(usage)
    records = output.setdefault("cells", {})
    changed = True
    while changed:
        changed = False
        for cell in plan["cells"]:
            row = records.get(cell["id"], {})
            if row.get("status") != "done" or not cell["dependencies"]:
                continue
            revisions = row.get("dependencyRevisions", {})
            if any(records.get(dep, {}).get("status") != "done"
                   or records.get(dep, {}).get("usageKnown", True) is not True
                   or revisions.get(dep) != records.get(dep, {}).get("revision", 0)
                   for dep in cell["dependencies"]):
                row.update({"status": "pending", "evidence": [], "reusableContext": [],
                            "dependencyRevisions": {}, "revision": row.get("revision", 0) + 1,
                            "blockers": ["Upstream result changed; fresh verification is required."]})
                changed = True
    return output


def quarantine_interrupted(usage: dict[str, Any]) -> dict[str, Any]:
    """An interrupted invocation may have executed: retain it for explicit reconciliation."""
    result = deepcopy(usage)
    for row in result.get("cells", {}).values():
        if "usageKnown" not in row and row.get("status") in {"pending", "failed", "partial", "blocked"} and row.get("attempts", 0) > 0:
            row.update({"usageKnown": False, "unknownAttempts": max(1, row.get("unknownAttempts", 0)),
                        "blockers": ["Legacy incomplete invocation has no usage-completeness marker; inspect and run hive reconcile."]})
        if row.get("status") != "in_progress":
            continue
        # Old checkpoints counted attempts after dispatch. New checkpoints reserve them first.
        attempts = row.get("attempts", 0) + (0 if "unknownAttempts" in row else 1)
        row.update({"status": "blocked", "usageKnown": False, "unknownAttempts": max(1, row.get("unknownAttempts", 0)),
                    "attempts": attempts, "revision": row.get("revision", 0) + 1,
                    "blockers": ["Interrupted invocation: inspect artifacts and provider usage, then run hive reconcile. Do not rerun blindly."]})
    return result


def usage_is_known(record: dict[str, Any], status: str | None = None) -> bool:
    status = status or record.get("status")
    if status == "in_progress":
        return False
    if "usageKnown" not in record and status in {"pending", "failed", "partial", "blocked"} and record.get("attempts", 0) > 0:
        return False
    return record.get("usageKnown", True) is True


def reconcile_cell_usage(plan: dict[str, Any], usage: dict[str, Any], identifier: str, *, status: str,
                         used: int, attempts: int, evidence: list[str], artifacts: list[str] | None = None,
                         now: datetime | None = None) -> dict[str, Any]:
    """Record an inspected outcome and confirmed cumulative usage; never authorize a new call."""
    usage = quarantine_interrupted(usage)
    previous = usage.get("cells", {}).get(identifier)
    if not previous or previous.get("usageKnown", True) is True:
        raise ValueError("Cell has no unresolved invocation to reconcile.")
    if status not in {"done", "pending", "blocked", "failed"}:
        raise ValueError("Reconciliation status must be done, pending, blocked, or failed.")
    if not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
        raise ValueError("Reconciliation requires evidence of the inspected outcome and confirmed cumulative usage.")
    cell = next((cell for cell in plan["cells"] if cell["id"] == identifier), None)
    if cell is None:
        raise ValueError(f"Unknown cell: {identifier}")
    if status == "done" and any(usage.get("cells", {}).get(dep, {}).get("status") != "done"
                                or usage["cells"][dep].get("usageKnown", True) is not True
                                for dep in cell["dependencies"]):
        raise ValueError("Cannot reconcile done before dependencies have known, completed outcomes.")
    return record_cell_usage(plan, usage, {"id": identifier, "status": status, "used": used, "attempts": attempts,
        "usageKnown": True, "unknownAttempts": 0, "evidence": evidence,
        "artifacts": artifacts if artifacts is not None else previous.get("artifacts", []),
        "blockers": [] if status in {"done", "pending"} else previous.get("blockers", [])}, now, resolve_unknown=True)


def rebalance_plan(plan: dict[str, Any], usage: dict[str, Any] | None = None, now: datetime | None = None,
                   release_reserve: bool = False) -> dict[str, Any]:
    summary, records = summarize_usage(plan, usage), (usage or {}).get("cells", {})
    pending = [cell for cell in plan["cells"] if (records.get(cell["id"], {}).get("status") or cell.get("status")) != "done"]
    released = bool(release_reserve or plan["budget"].get("reserveReleased"))
    protected = 0 if released else plan["budget"]["reserve"]
    future = max(0, plan["budget"]["total"] - protected - summary["used"])
    allocations = allocate(future, pending) if pending else {}
    revised = deepcopy(plan)
    revised.update({"revision": plan.get("revision", 1) + 1, "rebalancedAt": iso_now(now)})
    revised["budget"].update({"allocated": summary["used"] + future, "reserveReleased": released})
    cells = []
    for cell in plan["cells"]:
        row = records.get(cell["id"], {})
        used, status = max(0, int(_number(row.get("used"), 0))), row.get("status") or cell.get("status") or "pending"
        updated = deepcopy(cell)
        updated.update({"status": status, "allocation": used if status == "done" else used + allocations.get(cell["id"], 0)})
        cells.append(updated)
    revised["cells"] = cells
    return revised


def _number(value: Any, fallback: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
