from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .audit import append_audit
from .drivers import create_claude_driver, create_codex_driver, create_mock_driver
from .gate import evaluate_gate
from .memory import ScopedMemory
from .mission import default_mission, validate_mission
from .planner import create_plan, explain_cell, iso_now
from .prompt_compiler import compare_mission_variants
from .protocol import compile_all_payloads
from .runner import run_hive
from .token_counter import create_token_counter
from .usage import next_ready_cells, rebalance_plan, record_cell_usage, summarize_usage

BOOLEAN_OPTIONS = {"--release-reserve", "--human-approved", "--trusted", "--trusted-only", "--include-sensitive", "--resume", "--dry-run"}


class ConsoleIO:
    def log(self, value: Any) -> None:
        print(value)

    def table(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        columns = list(dict.fromkeys(key for row in rows for key in row))
        rendered = [[_display(row.get(column, "")) for column in columns] for row in rows]
        widths = [max(len(column), *(len(row[index]) for row in rendered)) for index, column in enumerate(columns)]
        print("  ".join(column.ljust(widths[index]) for index, column in enumerate(columns)))
        print("  ".join("-" * width for width in widths))
        for row in rendered:
            print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def run_cli(argv: list[str], io: Any | None = None) -> Any:
    io = io or ConsoleIO()
    command, args = (argv[0], argv[1:]) if argv else ("help", [])
    commands = {"init": _init_command, "plan": _plan_command, "compile": _compile_command,
                "compare": _compare_command, "next": _next_command, "record": _record_command,
                "status": _status_command, "rebalance": _rebalance_command, "explain": _explain_command,
                "gate": _gate_command, "memory": _memory_command, "run": _run_command,
                "validate": _validate_command}
    if command in {"help", "--help", "-h"}:
        io.log(help_text())
        return None
    if command not in commands:
        raise ValueError(f"Unknown command: {command}\n\n{help_text()}")
    return commands[command](args, io)


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_cli(list(sys.argv[1:] if argv is None else argv))
        if not isinstance(result, dict) or not isinstance(result.get("state"), dict):
            return 0
        state = result["state"]
        succeeded = state["status"] == "completed" or (state["status"] == "dry_run" and state["reason"] == "ready")
        return 0 if succeeded else 2
    except Exception as error:
        print(f"hive: {error}", file=sys.stderr)
        return 1


def _init_command(args: list[str], io: Any) -> None:
    directory = Path(args[0] if args else ".hive").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    mission_path = directory / "mission.json"
    _write_json(mission_path, default_mission())
    io.log(f"Created {mission_path}")


def _plan_command(args: list[str], io: Any) -> None:
    mission_path = Path(_option(args, "--mission") or (args[0] if args else ".hive/mission.json")).resolve()
    output_path = Path(_option(args, "--out") or ".hive/plan.json").resolve()
    mission = _read_json(mission_path)
    errors = validate_mission(mission)
    if errors:
        raise ValueError("\n".join(errors))
    plan = create_plan(mission)
    _write_json(output_path, plan)
    append_audit(_audit_path(args, output_path), {"event": "plan.created", "planPath": str(output_path),
                                                   "cells": len(plan["cells"]), "budget": plan["budget"]})
    io.log(f"Planned {len(plan['cells'])} cells in {len(plan['waves'])} waves.")
    io.log(f"Allocated {plan['budget']['allocated']} {plan['budget']['unit']}; reserve {plan['budget']['reserve']}.")
    io.log(f"Wrote {output_path}")


def _compile_command(args: list[str], io: Any) -> None:
    plan_path = Path(_option(args, "--plan") or (args[0] if args else ".hive/plan.json")).resolve()
    output_directory = Path(_option(args, "--out-dir") or ".hive/payloads").resolve()
    target = _option(args, "--target") or "generic"
    if target not in {"generic", "codex", "claude"}:
        raise ValueError("--target must be generic, codex, or claude.")
    output_directory.mkdir(parents=True, exist_ok=True)
    payloads = compile_all_payloads(_read_json(plan_path), target)
    for name, contents in payloads.items():
        (output_directory / name).write_text(contents, encoding="utf-8", newline="\n")
    io.log(f"Compiled {len(payloads)} HIVE/1 payloads for {target} to {output_directory}")


def _compare_command(args: list[str], io: Any) -> list[dict[str, Any]]:
    positions = _positional(args)
    mission_path = Path(_option(args, "--mission") or (positions[0] if positions else ".hive/mission.json")).resolve()
    raw = _read_json(mission_path)
    mission = raw["mission"] if isinstance(raw.get("mission"), dict) and raw["mission"].get("goal") else raw
    rows = compare_mission_variants(mission, create_token_counter({"type": _option(args, "--counter") or "heuristic",
                                                                    "model": _option(args, "--model")}))
    io.table([{"variant": row["name"], "tokens": row["tokens"], "precision": row["precision"],
               "counter": row["counter"], "chars": row["chars"], "bytes": row["bytes"],
               "preserved": row["literalsPreserved"], "note": row["note"]} for row in rows])
    best = next((row for row in rows if row["literalsPreserved"]), None)
    output_path = _option(args, "--write-best")
    if output_path and best:
        path = Path(output_path).resolve(); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(best["text"] + "\n", encoding="utf-8", newline="\n")
        io.log(f"Wrote lowest-count lossless variant ({best['name']}) to {path}")
    io.log("Precision is reported per row; heuristic counts are planning estimates, not provider tokenizer results.")
    return rows


def _next_command(args: list[str], io: Any) -> list[dict[str, Any]]:
    positions = _positional(args)
    plan = _read_json(Path(_option(args, "--plan") or (positions[0] if positions else ".hive/plan.json")).resolve())
    usage = _read_json_if_present(Path(_option(args, "--usage") or ".hive/usage.json").resolve(), {"cells": {}})
    ready = next_ready_cells(plan, usage)
    if not ready:
        summary = summarize_usage(plan, usage); spendable = summary["total"] - summary["effectiveReserve"]
        io.log(f"Budget gate closed: used {summary['used']}/{spendable} spendable {plan['budget']['unit']}."
               if summary["used"] >= spendable else "No pending cell has all dependencies completed.")
        return []
    rows = [{"id": cell["id"], "role": cell["role"], "tier": cell["modelTier"], "allocation": cell["allocation"],
             "dependencies": ",".join(cell["dependencies"]) or "none"} for cell in ready]
    io.table(rows)
    return ready


def _record_command(args: list[str], io: Any) -> dict[str, Any]:
    positions = _positional(args)
    if not positions:
        raise ValueError("record requires a cell id.")
    identifier, status = positions[0], _option(args, "--status")
    if not status:
        raise ValueError("record requires --status.")
    used = _optional_integer(args, "--used")
    if used is None:
        raise ValueError("record requires --used as a non-negative integer.")
    plan = _read_json(Path(_option(args, "--plan") or ".hive/plan.json").resolve())
    usage_path = Path(_option(args, "--usage") or ".hive/usage.json").resolve()
    usage = _read_json_if_present(usage_path, {"cells": {}})
    updated = record_cell_usage(plan, usage, {"id": identifier, "status": status, "used": used,
        "artifacts": _options(args, "--artifact"), "evidence": _options(args, "--evidence"),
        "blockers": _options(args, "--blocker"), "reusableContext": _options(args, "--context"),
        "attempts": _optional_integer(args, "--attempts"), "metrics": _metrics_options(args)})
    _write_json(usage_path, updated)
    stored = updated["cells"][identifier]
    append_audit(_audit_path(args, usage_path), {"event": "cell.recorded", "cell": identifier, "status": stored["status"],
        "used": stored["used"], "attempts": stored["attempts"], "metrics": stored["metrics"],
        "artifactCount": len(stored["artifacts"]), "evidenceCount": len(stored["evidence"]), "blockerCount": len(stored["blockers"])})
    io.log(f"Recorded {identifier}: {status}, {used} {plan['budget']['unit']} used."); io.log(f"Wrote {usage_path}")
    return updated


def _status_command(args: list[str], io: Any) -> dict[str, Any]:
    plan = _read_json(Path(_option(args, "--plan") or (args[0] if args else ".hive/plan.json")).resolve())
    usage = _read_json_if_present(Path(_option(args, "--usage") or ".hive/usage.json").resolve(), {"cells": {}})
    summary = summarize_usage(plan, usage); io.table(summary["rows"])
    io.log(f"Used {summary['used']}/{summary['total']} {plan['budget']['unit']}; protected reserve {summary['effectiveReserve']}.")
    metrics = summary["metrics"]
    io.log(f"Calls {metrics['modelCalls']}; input {metrics['inputTokens']} ({metrics['cachedInputTokens']} cached); output {metrics['outputTokens']}; reasoning {metrics['reasoningTokens']}; latency {metrics['latencyMs']}ms; cost ${metrics['costUsd']:.4f}.")
    if summary["alerts"]:
        io.table(summary["alerts"])
    if summary["used"] >= summary["total"] - summary["effectiveReserve"]:
        io.log("BUDGET GATE: closed; rebalance or explicitly release reserve.")
    return summary


def _rebalance_command(args: list[str], io: Any) -> dict[str, Any]:
    plan_path = Path(_option(args, "--plan") or (args[0] if args else ".hive/plan.json")).resolve()
    usage_path = Path(_option(args, "--usage") or ".hive/usage.json").resolve()
    output_path = Path(_option(args, "--out") or ".hive/plan.rebalanced.json").resolve()
    revised = rebalance_plan(_read_json(plan_path), _read_json_if_present(usage_path, {"cells": {}}),
                             release_reserve="--release-reserve" in args)
    _write_json(output_path, revised)
    append_audit(_audit_path(args, output_path), {"event": "plan.rebalanced", "revision": revised["revision"],
                                                  "reserveReleased": revised["budget"]["reserveReleased"]})
    io.log(f"Rebalanced revision {revised['revision']}; wrote {output_path}")
    return revised


def _explain_command(args: list[str], io: Any) -> str:
    plan_path = Path(_option(args, "--plan") or ".hive/plan.json").resolve()
    positions = _positional(args)
    if not positions:
        raise ValueError("explain requires a cell id.")
    explanation = explain_cell(_read_json(plan_path), positions[0]); io.log(explanation)
    return explanation


def _validate_command(args: list[str], io: Any) -> None:
    mission_path = Path(_option(args, "--mission") or (args[0] if args else ".hive/mission.json")).resolve()
    errors = validate_mission(_read_json(mission_path))
    if errors:
        raise ValueError("\n".join(errors))
    io.log(f"Valid mission: {mission_path}")


def _gate_command(args: list[str], io: Any) -> dict[str, Any]:
    plan_path = Path(_option(args, "--plan") or ".hive/plan.json").resolve()
    result = evaluate_gate(_read_json(plan_path), {"action": _option(args, "--action") or "read",
        "paths": _options(args, "--path") or [], "humanApproved": "--human-approved" in args})
    append_audit(_audit_path(args, plan_path), {"event": "gate.checked", **result})
    io.log(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    if not result["allowed"]:
        raise ValueError(f"Gate {result['result']}: {result['reason']}")
    return result


def _memory_command(args: list[str], io: Any) -> Any:
    if not args:
        raise ValueError("memory requires put, query, decay, or delete.")
    subcommand, rest = args[0], args[1:]
    store_path = Path(_option(rest, "--store") or ".hive/memory.json").resolve()
    saved = _read_json_if_present(store_path, {"schemaVersion": 1, "records": []})
    memory = ScopedMemory(records=saved.get("records", []))
    scope, namespace = _option(rest, "--scope") or "mission", _option(rest, "--namespace") or "default"
    if subcommand == "put":
        content = _option(rest, "--content")
        if not content:
            raise ValueError("memory put requires --content.")
        record = memory.write({"scope": scope, "namespace": namespace, "content": content,
            "kind": _option(rest, "--kind") or "context", "trust": "trusted" if "--trusted" in rest else "untrusted",
            "visibility": _options(rest, "--visibility"), "ttlMs": _optional_number(rest, "--ttl-ms"),
            "sensitivity": _numeric_option(rest, "--sensitivity")})
        _write_json(store_path, memory.export())
        append_audit(_audit_path(rest, store_path), {"event": "memory.put", "memoryId": record["id"], "scope": scope,
            "namespace": namespace, "kind": record["kind"], "trust": record["trust"], "visibility": record["visibility"]})
        io.log(f"Stored {record['id']} in {scope}/{namespace}."); return record
    if subcommand == "query":
        rows = memory.query({"scope": scope, "namespace": namespace, "role": _option(rest, "--role"),
            "limit": _optional_integer(rest, "--limit"), "minimumScore": _optional_number(rest, "--minimum-score"),
            "maxSensitivity": 1 if "--include-sensitive" in rest else _optional_number(rest, "--max-sensitivity"),
            "trustedOnly": "--trusted-only" in rest})
        _write_json(store_path, memory.export())
        append_audit(_audit_path(rest, store_path), {"event": "memory.query", "scope": scope, "namespace": namespace,
            "role": _option(rest, "--role") or "*", "resultCount": len(rows), "trustedOnly": "--trusted-only" in rest})
        io.table([{"id": row["id"], "kind": row["kind"], "trust": row["trust"],
                   "score": round(row["retentionScore"], 3), "content": row["content"]} for row in rows]); return rows
    if subcommand == "decay":
        summary = memory.decay(); _write_json(store_path, memory.export())
        append_audit(_audit_path(rest, store_path), {"event": "memory.decay", **summary})
        io.log(json.dumps(summary, separators=(",", ":"))); return summary
    if subcommand == "delete":
        deleted = memory.delete_scope(scope, namespace, _option(rest, "--reason") or "scope_expired")
        _write_json(store_path, memory.export()); append_audit(_audit_path(rest, store_path), {"event": "memory.delete", "scope": scope, "namespace": namespace, "deleted": deleted})
        io.log(f"Deleted {deleted} records from {scope}/{namespace}."); return deleted
    raise ValueError("memory requires put, query, decay, or delete.")


def _run_command(args: list[str], io: Any) -> dict[str, Any]:
    requested_target = _option(args, "--target")
    if requested_target and requested_target not in {"codex", "claude", "mock"}:
        raise ValueError("--target must be codex, claude, or mock.")
    state_directory = Path(_option(args, "--state-dir") or ".hive").resolve()
    requested_workspace = _option(args, "--workspace")
    workspace = Path(requested_workspace or ".").resolve()
    plan_path, usage_path, run_path = state_directory / "plan.json", state_directory / "usage.json", state_directory / "run.json"
    audit_file, payload_directory = Path(_option(args, "--audit") or state_directory / "audit.jsonl").resolve(), state_directory / "payloads"
    resume, target = "--resume" in args, requested_target or "codex"
    state_directory.mkdir(parents=True, exist_ok=True)
    run_state = None
    if resume:
        plan, usage, run_state = _read_json(plan_path), _read_json_if_present(usage_path, {"schemaVersion": 1, "cells": {}}), _read_json(run_path)
        target = requested_target or run_state.get("target")
        if target not in {"codex", "claude", "mock"}:
            raise ValueError("Saved run target is invalid; pass --target explicitly after inspecting run.json.")
        if requested_target and run_state.get("target") != requested_target:
            raise ValueError(f"Cannot resume a {run_state.get('target')} run with target {requested_target}. Start a new state directory instead.")
        workspace = Path(requested_workspace).resolve() if requested_workspace else Path(run_state.get("workspace") or ".").resolve()
        if requested_workspace and run_state.get("workspace") and Path(run_state["workspace"]).resolve() != workspace:
            raise ValueError(f"Cannot resume workspace {run_state['workspace']} in {workspace}. Start a new state directory instead.")
    else:
        positions = _positional(args)
        mission_path = Path(_option(args, "--mission") or (positions[0] if positions else state_directory / "mission.json")).resolve()
        mission = _read_json(mission_path); errors = validate_mission(mission)
        if errors:
            raise ValueError("\n".join(errors))
        plan, usage = create_plan(mission), {"schemaVersion": 1, "updatedAt": iso_now(), "cells": {}}
        _write_json(plan_path, plan); _write_json(usage_path, usage)
        append_audit(audit_file, {"event": "run.created", "target": target, "planPath": str(plan_path),
                                  "workspace": str(workspace), "cells": len(plan["cells"]), "budget": plan["budget"]})
    payload_directory.mkdir(parents=True, exist_ok=True)
    for name, contents in compile_all_payloads(plan, "generic" if target == "mock" else target).items():
        (payload_directory / name).write_text(contents, encoding="utf-8", newline="\n")
    approvals = _options(args, "--approve") or []
    invalid = next((action for action in approvals if action not in {"delete", "push", "deploy", "external-write"}), None)
    if invalid:
        raise ValueError(f"Unsupported --approve action: {invalid}.")
    driver = _run_driver(target, args, "--dry-run" in args)
    def checkpoint(event: dict[str, Any]) -> None:
        _write_json(usage_path, event["usage"]); _write_json(run_path, event["state"])
        detail = event["detail"]
        append_audit(audit_file, {"event": f"run.{event['type']}", "runId": event["state"]["runId"],
            "status": event["state"]["status"], "cell": detail.get("cell"), "result": detail.get("result"), "reason": detail.get("reason")})
        if event["type"] in {"cell_started", "cell_finished", "cell_retry_scheduled"}:
            suffix = f" ({detail['result']})" if detail.get("result") else ""
            io.log(f"{event['type']}: {detail.get('cell')}{suffix}")
    result = run_hive(plan=plan, usage=usage, run_state=run_state, target=target, driver=driver,
        workspace=str(workspace), model=_option(args, "--model"), timeout_ms=_optional_number(args, "--timeout-ms"),
        approvals=approvals, dry_run="--dry-run" in args, resume_blocked=resume, on_checkpoint=checkpoint)
    io.log(f"Hive run {result['state']['status']}: {result['state']['reason']}.")
    io.log(f"Used {result['summary']['used']}/{result['summary']['total']} {plan['budget']['unit']}; calls {result['summary']['metrics']['modelCalls']}; latency {result['summary']['metrics']['latencyMs']}ms.")
    if result["summary"]["alerts"]:
        io.table(result["summary"]["alerts"])
    return result


def _run_driver(target: str, args: list[str], dry_run: bool) -> Any:
    if target == "mock":
        mock_path = _option(args, "--mock-results")
        if not mock_path and not dry_run:
            raise ValueError("Mock runs require --mock-results.")
        return create_mock_driver(_read_json(Path(mock_path).resolve()) if mock_path else {})
    if target == "codex":
        sandbox = _option(args, "--sandbox") or "workspace-write"
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("--sandbox must be read-only or workspace-write.")
        return create_codex_driver(_option(args, "--codex-command"), sandbox)
    permission = _option(args, "--permission-mode") or "default"
    if permission not in {"default", "dontAsk", "plan", "acceptEdits", "auto"}:
        raise ValueError("--permission-mode must be default, dontAsk, plan, acceptEdits, or auto.")
    return create_claude_driver(_option(args, "--claude-command"), permission)


def _option(args: list[str], name: str) -> str | None:
    try:
        index = args.index(name)
        return args[index + 1] if index + 1 < len(args) else None
    except ValueError:
        return None


def _options(args: list[str], name: str) -> list[str] | None:
    values = [args[index + 1] for index, value in enumerate(args[:-1]) if value == name]
    return values or None


def _positional(args: list[str]) -> list[str]:
    values, index = [], 0
    while index < len(args):
        if args[index].startswith("--"):
            index += 1 if args[index] in BOOLEAN_OPTIONS else 2
        else:
            values.append(args[index]); index += 1
    return values


def _numeric_option(args: list[str], name: str) -> float:
    value = _option(args, name)
    if value is None:
        return 0
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a non-negative number.") from error
    if number < 0:
        raise ValueError(f"{name} must be a non-negative number.")
    return number


def _optional_number(args: list[str], name: str) -> float | None:
    return None if _option(args, name) is None else _numeric_option(args, name)


def _optional_integer(args: list[str], name: str) -> int | None:
    value = _option(args, name)
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a non-negative integer.") from error
    if str(number) != value or number < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
    return number


def _metrics_options(args: list[str]) -> dict[str, float] | None:
    fields = {"modelCalls": "--model-calls", "inputTokens": "--input-tokens", "cachedInputTokens": "--cached-input-tokens",
              "outputTokens": "--output-tokens", "reasoningTokens": "--reasoning-tokens", "latencyMs": "--latency-ms", "costUsd": "--cost-usd"}
    if not any(_option(args, name) is not None for name in fields.values()):
        return None
    return {field: _numeric_option(args, name) for field, name in fields.items()}


def _audit_path(args: list[str], state_path: Path) -> Path:
    return Path(_option(args, "--audit") or state_path.parent / "audit.jsonl").resolve()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_if_present(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    return _read_json(path) if path.exists() else fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _display(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)


def help_text() -> str:
    return """Agent Hive CLI

Usage:
  hive init [directory]
  hive validate [mission.json]
  hive plan [mission.json] [--out plan.json]
  hive compile [plan.json] [--target generic|codex|claude] [--out-dir payloads]
  hive compare [mission.json] [--counter heuristic|openai|anthropic|auto] [--model id] [--write-best file]
  hive next [plan.json] [--usage usage.json]
  hive record <cell-id> --status pending|in_progress|done|partial|blocked|failed --used number
              [--attempts number] [--artifact path] [--evidence text] [--blocker text] [--context text]
              [--model-calls n] [--input-tokens n] [--cached-input-tokens n]
              [--output-tokens n] [--reasoning-tokens n] [--latency-ms n] [--cost-usd n]
  hive status [plan.json] [--usage usage.json]
  hive rebalance [plan.json] [--usage usage.json] [--out revised.json] [--release-reserve]
  hive explain <cell-id> [--plan plan.json]
  hive gate --action read|write|delete|push|deploy|external-write|network [--path path] [--human-approved]
  hive memory put|query|decay|delete [--store memory.json] [--scope scope] [--namespace id]
  hive run [mission.json] --target codex|claude|mock [--state-dir .hive] [--workspace path]
           [--resume] [--dry-run] [--approve action] [--model id] [--timeout-ms n]
           [--mock-results file] [--sandbox read-only|workspace-write]
           [--permission-mode default|dontAsk|plan|acceptEdits|auto]"""
