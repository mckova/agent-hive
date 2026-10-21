from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

ROLES = {"scout", "architect", "forager", "builder", "guard", "keeper"}
HUMAN_GATE_ACTIONS = ["delete", "push", "deploy", "external-write"]
ACTIONS = {"read", "write", "network", "delete", "push", "deploy", "external-write"}


def default_mission() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "mission": {
            "goal": "Describe the outcome in any language.",
            "sourceLanguage": "auto",
            "responseLanguage": "same-as-user",
            "must": [],
            "avoid": [],
            "doneWhen": [],
        },
        "budget": {"unit": "tokens", "total": 100000, "reservePercent": 20},
        "policy": {"maxWorkers": 3, "qualityFloor": "balanced"},
        "guardrails": default_guardrails(),
        "models": {},
        "cells": [],
    }


def default_guardrails() -> dict[str, Any]:
    return {
        "allowedPathPrefixes": [],
        "deniedPathPrefixes": [".env", ".git", "secrets", "credentials"],
        "allowNetwork": False,
        "humanApprovalActions": list(HUMAN_GATE_ACTIONS),
        "maxAttemptsPerCell": 2,
        "trustedInstructionSources": ["mission", "cell"],
    }


def decompose_mission(
    goal: str,
    must: list[str] | None = None,
    avoid: list[str] | None = None,
    done_when: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Create role-specific worker assignments from the queen's mission genome."""
    clean_goal = " ".join((goal or "the mission").split())
    excerpt = clean_goal if len(clean_goal) <= 180 else clean_goal[:177].rstrip() + "..."
    must_items = _clean_strings(must)
    avoid_items = _clean_strings(avoid)
    done_items = _clean_strings(done_when)
    success = "; ".join(done_items) if done_items else "produce verifiable evidence that the mission goal is complete"

    def job(
        identifier: str,
        title: str,
        role: str,
        priority: int,
        complexity: int,
        risk: int,
        dependencies: list[str],
        required: bool,
        instructions: list[str],
        actions: list[str],
    ) -> dict[str, Any]:
        cell = _cell(identifier, title, role, priority, complexity, risk, dependencies, required)
        cell.update({"instructions": instructions, "actions": actions, "paths": []})
        return cell

    constraint_instruction = (
        "Treat these as hard requirements: " + "; ".join(must_items)
        if must_items else "Identify the hard requirements implied by the mission without inventing new scope."
    )
    forbidden_instruction = (
        "Protect against these forbidden outcomes: " + "; ".join(avoid_items)
        if avoid_items else "Record risky or irreversible actions that need an explicit gate."
    )
    return [
        job(
            "survey", f"Map requirements and unknowns for: {excerpt}", "scout", 5, 2, 2, [], True,
            [
                f"Read the queen mission exactly as written: {clean_goal}",
                constraint_instruction,
                "Return affected areas, assumptions, unknowns, risks, and questions; do not change project files.",
            ], ["read"],
        ),
        job(
            "forage", f"Gather evidence and reusable assets for: {excerpt}", "forager", 4, 2, 2, [], True,
            [
                "Find only project files, tests, documentation, prior decisions, and interfaces relevant to the queen mission.",
                "Cite exact paths or evidence and separate verified facts from assumptions.",
                "Stop when the evidence is sufficient for design; do not implement the solution.",
            ], ["read"],
        ),
        job(
            "design", f"Design the smallest safe route to: {excerpt}", "architect", 5, 4, 3,
            ["survey", "forage"], True,
            [
                "Use the scout's requirement map and the forager's evidence pack as inputs.",
                constraint_instruction,
                f"Produce an ordered implementation plan and acceptance matrix for: {success}.",
            ], ["read"],
        ),
        job(
            "build", f"Implement the approved route for: {excerpt}", "builder", 5, 5, 4, ["design"], True,
            [
                "Implement only the architect's approved plan and keep the change set focused on the queen mission.",
                constraint_instruction,
                forbidden_instruction,
                "Return changed artifacts, focused checks, actual token usage, and any blocker; do not claim success without evidence.",
            ], ["read", "write"],
        ),
        job(
            "verify", f"Independently verify the result for: {excerpt}", "guard", 5, 4, 5, ["build"], True,
            [
                f"Build a pass/fail evidence matrix for these completion criteria: {success}.",
                constraint_instruction,
                forbidden_instruction,
                "Check security, regressions, tool accuracy, and budget telemetry; block completion on missing evidence.",
            ], ["read"],
        ),
        job(
            "distill", f"Distill verified hive memory for: {excerpt}", "keeper", 2, 1, 1, ["verify"], False,
            [
                "Keep only verified decisions, reusable context, artifact paths, and unresolved risks from this run.",
                "Exclude secrets, raw prompt repetition, stale assumptions, and unverified claims.",
                "Return a compact handoff that reduces context cost for the next hive run.",
            ], ["read"],
        ),
    ]


def default_cells() -> list[dict[str, Any]]:
    return decompose_mission("Describe the desired outcome in any language.")


def _cell(identifier: str, title: str, role: str, priority: int, complexity: int,
          risk: int, dependencies: list[str], required: bool) -> dict[str, Any]:
    return {"id": identifier, "title": title, "role": role, "priority": priority,
            "complexity": complexity, "risk": risk, "dependencies": dependencies,
            "required": required}


def validate_mission(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["Mission must be a JSON object."]
    mission = value.get("mission")
    if not isinstance(mission, dict) or not isinstance(mission.get("goal"), str) or not mission["goal"].strip():
        errors.append("mission.goal must be a non-empty string.")

    budget = value.get("budget") if isinstance(value.get("budget"), dict) else {}
    total = budget.get("total")
    if not _is_int(total) or total <= 0:
        errors.append("budget.total must be a positive integer.")
    if budget.get("unit") is not None and budget.get("unit") not in {"tokens", "usd-micros"}:
        errors.append("budget.unit must be tokens or usd-micros.")
    reserve = budget.get("reservePercent")
    if not _is_number(reserve) or reserve < 0 or reserve >= 100:
        errors.append("budget.reservePercent must be at least 0 and below 100.")

    policy = value.get("policy") if isinstance(value.get("policy"), dict) else {}
    max_workers = policy.get("maxWorkers")
    if not _is_int(max_workers) or max_workers < 1 or max_workers > 32:
        errors.append("policy.maxWorkers must be an integer from 1 to 32.")
    if policy.get("qualityFloor") is not None and policy.get("qualityFloor") not in {"economy", "balanced", "frontier"}:
        errors.append("policy.qualityFloor must be economy, balanced, or frontier.")

    guardrails = value.get("guardrails")
    if guardrails is not None:
        if not isinstance(guardrails, dict):
            errors.append("guardrails must be an object.")
        else:
            for field in ("allowedPathPrefixes", "deniedPathPrefixes", "humanApprovalActions", "trustedInstructionSources"):
                if field in guardrails and not _is_string_list(guardrails[field]):
                    errors.append(f"guardrails.{field} must be an array of strings.")
            if "allowNetwork" in guardrails and not isinstance(guardrails["allowNetwork"], bool):
                errors.append("guardrails.allowNetwork must be a boolean.")
            attempts = guardrails.get("maxAttemptsPerCell")
            if attempts is not None and (not _is_int(attempts) or attempts < 1 or attempts > 20):
                errors.append("guardrails.maxAttemptsPerCell must be an integer from 1 to 20.")

    if isinstance(mission, dict):
        for field in ("must", "avoid", "doneWhen"):
            if field in mission and not _is_string_list(mission[field]):
                errors.append(f"mission.{field} must be an array of strings.")

    models = value.get("models") if isinstance(value.get("models"), dict) else {}
    for tier in ("economy", "balanced", "frontier"):
        mapping = models.get(tier)
        if mapping is None:
            continue
        if not isinstance(mapping, dict):
            errors.append(f"models.{tier} must be an object.")
            continue
        for target, model in mapping.items():
            if not isinstance(target, str) or not target.strip() or not isinstance(model, str) or not model.strip():
                errors.append(f"models.{tier}.{target} must be a non-empty string.")

    raw_cells = value.get("cells")
    if "cells" in value and not isinstance(raw_cells, list):
        errors.append("cells must be an array.")
    goal = mission.get("goal") if isinstance(mission, dict) and isinstance(mission.get("goal"), str) else "the mission"
    cells = raw_cells if isinstance(raw_cells, list) and raw_cells else decompose_mission(
        goal,
        mission.get("must") if isinstance(mission, dict) else None,
        mission.get("avoid") if isinstance(mission, dict) else None,
        mission.get("doneWhen") if isinstance(mission, dict) else None,
    )
    identifiers: set[str] = set()
    for index, candidate in enumerate(cells):
        prefix = f"cells[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        identifier = candidate.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", identifier):
            errors.append(f"{prefix}.id must be lower-case kebab-case.")
        elif identifier in identifiers:
            errors.append(f"{prefix}.id duplicates {identifier}.")
        else:
            identifiers.add(identifier)
        if not isinstance(candidate.get("title"), str) or not candidate["title"].strip():
            errors.append(f"{prefix}.title must be a non-empty string.")
        if candidate.get("role") not in ROLES:
            errors.append(f"{prefix}.role must be one of {', '.join(sorted(ROLES))}.")
        for field in ("priority", "complexity", "risk"):
            score = candidate.get(field)
            if not _is_int(score) or score < 1 or score > 5:
                errors.append(f"{prefix}.{field} must be an integer from 1 to 5.")
        if candidate.get("dependencies") is not None and not isinstance(candidate["dependencies"], list):
            errors.append(f"{prefix}.dependencies must be an array.")
        for field in ("instructions", "paths"):
            if field in candidate and not _is_string_list(candidate[field]):
                suffix = "workspace-relative strings" if field == "paths" else "strings"
                errors.append(f"{prefix}.{field} must be an array of {suffix}.")
        actions = candidate.get("actions")
        if actions is not None and (not _is_string_list(actions) or any(action not in ACTIONS for action in actions)):
            errors.append(f"{prefix}.actions must contain only {', '.join(sorted(ACTIONS))}.")

    for candidate in cells:
        if not isinstance(candidate, dict):
            continue
        for dependency in candidate.get("dependencies") or []:
            if dependency not in identifiers:
                errors.append(f"Cell {candidate.get('id')} depends on missing cell {dependency}.")
            if dependency == candidate.get("id"):
                errors.append(f"Cell {candidate.get('id')} cannot depend on itself.")
    if not errors:
        try:
            build_waves(cells, max_workers)
        except ValueError as error:
            errors.append(str(error))
    return errors


def normalized_mission(value: dict[str, Any]) -> dict[str, Any]:
    errors = validate_mission(value)
    if errors:
        raise ValueError("\n".join(errors))
    mission = value["mission"]
    budget = value["budget"]
    policy = value["policy"]
    cells = value.get("cells") or decompose_mission(
        mission["goal"], mission.get("must"), mission.get("avoid"), mission.get("doneWhen")
    )
    return {
        "schemaVersion": 1,
        "mission": {
            "goal": mission["goal"].strip(),
            "sourceLanguage": mission.get("sourceLanguage") or "auto",
            "responseLanguage": mission.get("responseLanguage") or "same-as-user",
            "must": _clean_strings(mission.get("must")),
            "avoid": _clean_strings(mission.get("avoid")),
            "doneWhen": _clean_strings(mission.get("doneWhen")),
        },
        "budget": {"unit": budget.get("unit") or "tokens", "total": budget["total"],
                   "reservePercent": budget["reservePercent"]},
        "policy": {"maxWorkers": policy["maxWorkers"], "qualityFloor": policy.get("qualityFloor") or "balanced"},
        "guardrails": _normalize_guardrails(value.get("guardrails")),
        "models": _normalize_models(value.get("models")),
        "cells": [{
            "id": cell["id"], "title": cell["title"].strip(), "role": cell["role"],
            "priority": cell["priority"], "complexity": cell["complexity"], "risk": cell["risk"],
            "dependencies": list(cell.get("dependencies") or []), "required": cell.get("required") is not False,
            "instructions": _clean_strings(cell.get("instructions")), "actions": _clean_strings(cell.get("actions")),
            "paths": _clean_strings(cell.get("paths")),
        } for cell in cells],
    }


def build_waves(cells: list[dict[str, Any]], max_workers: int) -> list[list[str]]:
    remaining = {cell["id"]: cell for cell in cells}
    complete: set[str] = set()
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(
            (cell for cell in remaining.values() if all(dep in complete for dep in cell.get("dependencies", []))),
            key=lambda cell: (-cell["priority"], cell["id"]),
        )
        if not ready:
            raise ValueError("Cell dependencies contain a cycle.")
        for offset in range(0, len(ready), max_workers):
            wave = [cell["id"] for cell in ready[offset:offset + max_workers]]
            waves.append(wave)
            for identifier in wave:
                remaining.pop(identifier)
                complete.add(identifier)
    return waves


def _normalize_guardrails(value: Any) -> dict[str, Any]:
    defaults = default_guardrails()
    source = value if isinstance(value, dict) else {}
    return {
        "allowedPathPrefixes": _clean_strings(source.get("allowedPathPrefixes")),
        "deniedPathPrefixes": defaults["deniedPathPrefixes"] if "deniedPathPrefixes" not in source else _clean_strings(source["deniedPathPrefixes"]),
        "allowNetwork": source.get("allowNetwork") is True,
        "humanApprovalActions": defaults["humanApprovalActions"] if "humanApprovalActions" not in source else _clean_strings(source["humanApprovalActions"]),
        "maxAttemptsPerCell": source.get("maxAttemptsPerCell", defaults["maxAttemptsPerCell"]),
        "trustedInstructionSources": defaults["trustedInstructionSources"] if "trustedInstructionSources" not in source else _clean_strings(source["trustedInstructionSources"]),
    }


def _normalize_models(value: Any) -> dict[str, dict[str, str]]:
    models = value if isinstance(value, dict) else {}
    return {tier: {target.strip(): model.strip() for target, model in models[tier].items()}
            for tier in ("economy", "balanced", "frontier") if isinstance(models.get(tier), dict)}


def _clean_strings(value: Any) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
