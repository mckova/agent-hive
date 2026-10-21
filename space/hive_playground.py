from __future__ import annotations

from typing import Any

from agent_hive.mission import default_mission
from agent_hive.planner import create_plan
from agent_hive.prompt_compiler import compare_mission_variants
from agent_hive.protocol import compile_all_payloads
from agent_hive.token_counter import heuristic_count

MAX_GOAL_CHARS = 6_000
MAX_LIST_ITEMS = 20
MAX_ITEM_CHARS = 1_000

ROLE_GUIDE = {
    "scout": {
        "name": "Scout bee",
        "purpose": "Turns the queen's prompt into a factual requirement and risk map before anyone changes the project.",
        "deliverable": "Requirement map: affected areas, hard constraints, assumptions, unknowns, risks, and questions.",
    },
    "forager": {
        "name": "Forager bee",
        "purpose": "Collects the smallest evidence pack the hive needs instead of making every worker reread the whole project.",
        "deliverable": "Evidence pack: relevant files, tests, interfaces, prior decisions, and cited facts separated from assumptions.",
    },
    "architect": {
        "name": "Architect bee",
        "purpose": "Combines requirements and evidence into a dependency-aware route the builder can execute.",
        "deliverable": "Approved route: ordered implementation steps, affected artifacts, risks, gates, and an acceptance matrix.",
    },
    "builder": {
        "name": "Builder bee",
        "purpose": "Produces the requested outcome inside the route and boundaries approved by the architect.",
        "deliverable": "Focused change set or requested artifact, plus focused checks, evidence, blockers, and actual usage.",
    },
    "guard": {
        "name": "Guard bee",
        "purpose": "Independently decides whether the result satisfies the queen instead of trusting the builder's claim.",
        "deliverable": "Pass/fail evidence matrix covering every must, avoid, done-when, regression, security, and budget check.",
    },
    "keeper": {
        "name": "Keeper bee",
        "purpose": "Returns a compact reusable-context summary without writing project artifacts after verification.",
        "deliverable": "Compact handoff: verified decisions, artifact paths, reusable context, and unresolved risks—with no secrets.",
    },
}


def build_playground_result(
    goal: str,
    must_text: str,
    avoid_text: str,
    done_text: str,
    total_tokens: int | float,
    reserve_percent: int | float,
    max_workers: int | float,
    quality_floor: str,
    target: str,
) -> dict[str, Any]:
    """Create a deterministic, read-only Hive plan for the public Space."""
    clean_goal = (goal or "").strip()
    if not clean_goal:
        raise ValueError("Enter a mission goal in any language.")
    if len(clean_goal) > MAX_GOAL_CHARS:
        raise ValueError(f"Mission goal must be at most {MAX_GOAL_CHARS:,} characters.")

    total = _bounded_integer(total_tokens, "Total token budget", 1_000, 5_000_000)
    reserve = _bounded_integer(reserve_percent, "Reserve percentage", 0, 80)
    workers = _bounded_integer(max_workers, "Maximum workers", 1, 12)
    if quality_floor not in {"economy", "balanced", "frontier"}:
        raise ValueError("Unknown quality floor.")
    if target not in {"generic", "codex", "claude"}:
        raise ValueError("Unknown provider target.")

    mission = default_mission()
    mission["mission"].update({
        "goal": clean_goal,
        "sourceLanguage": "auto",
        "responseLanguage": "same-as-user",
        "must": _lines(must_text),
        "avoid": _lines(avoid_text),
        "doneWhen": _lines(done_text),
    })
    mission["budget"].update({"total": total, "reservePercent": reserve})
    mission["policy"].update({"maxWorkers": workers, "qualityFloor": quality_floor})

    plan = create_plan(mission)
    variants = compare_mission_variants(plan["mission"], heuristic_count)
    best = variants[0]
    payloads = compile_all_payloads(plan, target)

    wave_by_cell = {
        identifier: index
        for index, wave in enumerate(plan["waves"], start=1)
        for identifier in wave
    }
    assignments = []
    for cell in plan["cells"]:
        guide = ROLE_GUIDE[cell["role"]]
        assignments.append({
            "id": cell["id"],
            "role": cell["role"],
            "roleName": guide["name"],
            "purpose": guide["purpose"],
            "task": cell["title"],
            "instructions": cell.get("instructions") or [],
            "deliverable": guide["deliverable"],
            "wave": wave_by_cell[cell["id"]],
            "dependencies": cell["dependencies"],
            "modelTier": cell["modelTier"],
            "allocation": cell["allocation"],
            "required": cell["required"],
            "risk": cell["risk"],
            "priority": cell["priority"],
        })

    plan_rows = [[
        cell["id"], cell["role"], cell["modelTier"], cell["allocation"],
        ", ".join(cell["dependencies"]) or "—", "yes" if cell["required"] else "no",
    ] for cell in plan["cells"]]
    variant_rows = [[
        row["name"], row["tokens"], row["precision"], row["bytes"],
        "yes" if row["literalsPreserved"] else "no",
    ] for row in variants]
    wave_text = " → ".join(" + ".join(wave) for wave in plan["waves"])
    payload_text = "\n\n".join(f"# {name}\n{payload}" for name, payload in payloads.items())
    summary = (
        "### Hive plan ready\n"
        f"**{len(plan['cells'])} cells** across **{len(plan['waves'])} waves** · "
        f"**{plan['budget']['allocated']:,}** spendable tokens · "
        f"**{plan['budget']['reserve']:,}** protected reserve · "
        f"lowest-count representation retaining normalized literals: **{best['name']}** "
        f"({best['tokens']:,} heuristic tokens)\n\n"
        "This public demo performs deterministic planning only. It does not call a model, "
        "run provider CLIs, retain prompts, or execute tools."
    )
    return {
        "summary": summary,
        "queen": {
            "goal": plan["mission"]["goal"],
            "must": plan["mission"]["must"],
            "avoid": plan["mission"]["avoid"],
            "doneWhen": plan["mission"]["doneWhen"],
            "rule": "The mission supplies intent and constraints to a fixed role template. This preview executes no workers; normalization trims surrounding whitespace.",
        },
        "assignments": assignments,
        "metrics": {
            "cells": len(plan["cells"]),
            "waves": len(plan["waves"]),
            "spendable": plan["budget"]["allocated"],
            "reserve": plan["budget"]["reserve"],
            "bestVariant": best["name"],
            "bestTokens": best["tokens"],
        },
        "planRows": plan_rows,
        "waves": wave_text,
        "variantRows": variant_rows,
        "bestPrompt": best["text"],
        "mission": mission,
        "payloads": payload_text,
        "guardrails": plan["guardrails"],
    }


def _lines(value: str | None) -> list[str]:
    rows = [row.strip() for row in (value or "").splitlines() if row.strip()]
    if len(rows) > MAX_LIST_ITEMS:
        raise ValueError(f"Use at most {MAX_LIST_ITEMS} non-empty lines per constraint field.")
    if any(len(row) > MAX_ITEM_CHARS for row in rows):
        raise ValueError(f"Each constraint line must be at most {MAX_ITEM_CHARS:,} characters.")
    return rows


def _bounded_integer(value: int | float, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    try:
        integer = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an integer.") from error
    if float(value) != integer or integer < minimum or integer > maximum:
        raise ValueError(f"{label} must be from {minimum:,} to {maximum:,}.")
    return integer
