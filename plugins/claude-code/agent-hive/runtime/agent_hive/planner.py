from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .mission import build_waves, normalized_mission

TIER_RANK = {"economy": 1, "balanced": 2, "frontier": 3}


def iso_now(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_plan(raw_mission: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    mission = normalized_mission(raw_mission)
    reserve = math.floor(mission["budget"]["total"] * mission["budget"]["reservePercent"] / 100)
    distributable = mission["budget"]["total"] - reserve
    allocations = allocate(distributable, mission["cells"])
    floor_rank = TIER_RANK.get(mission["policy"]["qualityFloor"], TIER_RANK["balanced"])
    cells = []
    for candidate in mission["cells"]:
        score = task_score(candidate)
        cell = dict(candidate)
        cell.update({
            "modelTier": _tier_for(score, floor_rank), "allocation": allocations[candidate["id"]],
            "status": "pending", "factors": {"score": round(score, 2), "weight": round(task_weight(candidate), 2),
                                                 "required": candidate["required"]},
        })
        cells.append(cell)
    return {
        "schemaVersion": 1, "revision": 1, "generatedAt": iso_now(now), "mission": mission["mission"],
        "policy": mission["policy"], "guardrails": mission["guardrails"], "models": mission["models"],
        "budget": {"unit": mission["budget"]["unit"], "total": mission["budget"]["total"], "reserve": reserve,
                   "allocated": distributable, "reservePercent": mission["budget"]["reservePercent"],
                   "reserveReleased": False},
        "waves": build_waves(cells, mission["policy"]["maxWorkers"]), "cells": cells,
    }


def task_weight(candidate: dict[str, Any]) -> float:
    multiplier = 1.25 if candidate.get("required") else 0.7
    return multiplier * (candidate["priority"] * 0.45 + candidate["complexity"] * 0.35 + candidate["risk"] * 0.2)


def task_score(candidate: dict[str, Any]) -> float:
    return candidate["complexity"] * 0.45 + candidate["risk"] * 0.4 + candidate["priority"] * 0.15


def _tier_for(score: float, floor_rank: int) -> str:
    score_rank = 3 if score >= 4 else 2 if score >= 2.75 else 1
    rank = max(score_rank, floor_rank)
    return next(name for name, value in TIER_RANK.items() if value == rank)


def allocate(total: int, cells: list[dict[str, Any]]) -> dict[str, int]:
    weights = [{"id": cell["id"], "weight": task_weight(cell)} for cell in cells]
    weight_total = sum(row["weight"] for row in weights)
    rows = []
    for row in weights:
        exact = total * row["weight"] / weight_total
        rows.append({**row, "exact": exact, "value": math.floor(exact), "fraction": exact - math.floor(exact)})
    remainder = total - sum(row["value"] for row in rows)
    rows.sort(key=lambda row: (-row["fraction"], row["id"]))
    for index in range(remainder):
        rows[index % len(rows)]["value"] += 1
    return {row["id"]: row["value"] for row in rows}


def explain_cell(plan: dict[str, Any], identifier: str) -> str:
    cell = next((candidate for candidate in plan["cells"] if candidate["id"] == identifier), None)
    if cell is None:
        raise ValueError(f"Unknown cell: {identifier}")
    share = cell["allocation"] / plan["budget"]["allocated"] * 100 if plan["budget"]["allocated"] else 0
    dependencies = ",".join(cell["dependencies"]) if cell["dependencies"] else "none"
    return "\n".join([
        f"{cell['id']}: {cell['title']}",
        f"role={cell['role']} tier={cell['modelTier']} allocation={cell['allocation']} {plan['budget']['unit']}",
        f"priority={cell['priority']}/5 complexity={cell['complexity']}/5 risk={cell['risk']}/5 required={str(cell['required']).lower()}",
        f"weight={cell['factors']['weight']} score={cell['factors']['score']} share={share:.1f}%",
        f"dependencies={dependencies}",
    ])
