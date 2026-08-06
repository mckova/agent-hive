from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BENCHMARK_ROOT.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_hive.planner import create_plan
from agent_hive.protocol import compile_all_payloads

ARMS = ["normal", "caveman", "ralph", "loop-engineering", "agent-hive"]
TEST_COMMAND = "python -m unittest discover -s checks -v"


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    run_root = Path(arguments[0] if len(arguments) > 0 else f"C:/tmp/agent-hive-workflow-bench-{int(time.time() * 1000)}").resolve()
    caveman = Path(arguments[1] if len(arguments) > 1 else "C:/tmp/bench-caveman").resolve()
    ralph = Path(arguments[2] if len(arguments) > 2 else "C:/tmp/bench-ralph-loop").resolve()
    loop = Path(arguments[3] if len(arguments) > 3 else "C:/tmp/bench-loop-engineering").resolve()
    profile = arguments[4] if len(arguments) > 4 else "full"
    run_root.mkdir(parents=True, exist_ok=False)
    for arm in ARMS:
        shutil.copytree(BENCHMARK_ROOT / "fixture", run_root / arm)
        (run_root / arm / ".bench").mkdir(parents=True)

    destination = run_root / "caveman" / ".agents" / "skills" / "caveman"
    destination.parent.mkdir(parents=True); shutil.copytree(caveman / "skills" / "caveman", destination)

    ralph_dir = run_root / "ralph" / ".agent"; (ralph_dir / "tasks").mkdir(parents=True)
    shutil.copy2(ralph / ".agent" / "PROMPT.md", ralph_dir / "UPSTREAM_PROMPT.md")
    _write_json(ralph_dir / "tasks.json", [{"id": "TASK-001", "priority": 1, "title": "Implement the rate limiter", "passes": False},
                                              {"id": "TASK-002", "priority": 2, "title": "Verify requirements and repair gaps", "passes": False}])
    for identifier, objective in (("TASK-001", "Implement every requirement in TASK.md and run the public tests."),
                                  ("TASK-002", "Independently audit the implementation, repair gaps, and run the public tests.")):
        _write_json(ralph_dir / "tasks" / f"{identifier}.json", {"id": identifier, "objective": objective,
                    "allowedFiles": ["src/rate_limiter.py", ".agent/tasks.json"]})
    (ralph_dir / "BENCHMARK_PROMPT.md").write_text(f"""# Ralph benchmark adaptation

Follow the upstream one-task-per-fresh-context method. Never inspect parent or sibling directories.
Run `{TEST_COMMAND}`. Do not edit checks/. Mark a task complete only after tests pass.
""", encoding="utf-8")

    loop_arm = run_root / "loop-engineering"; skills = loop_arm / ".agents" / "skills"; skills.mkdir(parents=True)
    for skill in ("minimal-fix", "loop-verifier"):
        shutil.copytree(loop / "skills" / skill, skills / skill)
    (loop_arm / "LOOP.md").write_text("# Benchmark loop\n\nDiscover TASK.md, hand it to a maker, verify independently, record state, and stop. Maximum repair attempts: 2.\n", encoding="utf-8")
    (loop_arm / "STATE.md").write_text("# State\n\nstatus: pending\nattempt: 0\nlast_verdict: none\n", encoding="utf-8")
    (loop_arm / "loop-budget.md").write_text("# Budget\n\nMaximum model turns: 4. Stop on the second rejected repair.\n", encoding="utf-8")
    (loop_arm / "loop-constraints.md").write_text(f"# Constraints\n\n- Only src/rate_limiter.py and STATE.md may be edited.\n- Never edit checks/.\n- Run `{TEST_COMMAND}`.\n", encoding="utf-8")

    hive_arm, hive_dir = run_root / "agent-hive", run_root / "agent-hive" / ".hive"
    (hive_dir / "payloads").mkdir(parents=True)
    shutil.copytree(REPOSITORY_ROOT / "plugins" / "codex" / "agent-hive" / "skills" / "run-agent-hive",
                    hive_arm / ".bench" / "run-agent-hive")
    cells = ([
        _cell("build", "Implement TASK.md in src/rate_limiter.py and run public tests", "builder", 5, 4, 4, []),
        _cell("verify", "Independently verify code, tests, security, scope, and every requirement", "guard", 5, 3, 5, ["build"]),
    ] if profile == "compact" else [
        _cell("survey", "Map requirements, edge cases, and security risks", "scout", 5, 2, 3, []),
        _cell("build", "Implement TASK.md in src/rate_limiter.py and run public tests", "builder", 5, 4, 4, ["survey"]),
        _cell("verify", "Independently verify code, tests, security, scope, and every requirement", "guard", 5, 3, 5, ["build"]),
    ])
    mission = {"schemaVersion": 1, "mission": {"goal": "ממשו במדויק את TASK.md בפייתון, עם אבטחה ובדיקות.",
        "sourceLanguage": "he", "responseLanguage": "he", "must": ["אין לשנות checks/", "אין לקרוא תיקיות אב או sibling", f"יש להריץ {TEST_COMMAND}"],
        "avoid": ["third-party dependencies", "timers", "unbounded storage"], "doneWhen": ["כל הבדיקות הציבוריות עוברות", "guard מאמת כל דרישה"]},
        "budget": {"unit": "tokens", "total": 80000, "reservePercent": 20}, "policy": {"maxWorkers": 1, "qualityFloor": "economy"},
        "models": {}, "cells": cells}
    _write_json(hive_dir / "mission.json", mission); plan = create_plan(mission); _write_json(hive_dir / "plan.json", plan)
    if profile == "compact":
        (hive_dir / "survey.md").write_text("# Swarm admission\n\nScout omitted: TASK.md is bounded and testable.\n", encoding="utf-8")
    for name, payload in compile_all_payloads(plan, "codex").items():
        (hive_dir / "payloads" / name).write_text(payload, encoding="utf-8")

    provenance = {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(), "runRoot": str(run_root),
        "model": "gpt-5.5", "reasoningEffort": "medium", "repositories": {"caveman": _repo_info(caveman),
        "ralphLoop": _repo_info(ralph), "loopEngineering": _repo_info(loop),
        "agentHive": {"path": str(REPOSITORY_ROOT), "version": "0.4.0", "profile": profile}}}
    _write_json(run_root / "provenance.json", provenance); print(run_root)


def _cell(identifier, title, role, priority, complexity, risk, dependencies):
    return {"id": identifier, "title": title, "role": role, "priority": priority, "complexity": complexity,
            "risk": risk, "dependencies": dependencies, "required": True}


def _repo_info(directory):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=directory, capture_output=True, text=True)
    return {"path": str(directory), "commit": result.stdout.strip() or "unknown"}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
