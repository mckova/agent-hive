from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_hive.cli import run_cli
from agent_hive.drivers import create_mock_driver, parse_claude_output, parse_codex_output, parse_worker_result
from agent_hive.planner import create_plan
from agent_hive.runner import run_hive
from tests.helpers import FakeIO, metric, two_cell_mission


class RunnerTests(unittest.TestCase):
    def test_runner_retries_partial_cell_and_completes_through_guard(self):
        checkpoints = []
        result = run_hive(plan=create_plan(two_cell_mission()), target="mock", workspace=".",
            driver=create_mock_driver({"cells": {"build": [
                {"status": "partial", "blockers": ["missing edge case"], "metrics": metric(100, 10)},
                {"status": "done", "artifacts": ["src/result.py"], "evidence": ["tests pass"], "metrics": metric(100, 20)}],
                "verify": {"status": "done", "evidence": ["guard pass"], "metrics": metric(80, 10)}}}),
            on_checkpoint=lambda event: checkpoints.append(event["type"]))
        self.assertEqual(result["state"]["status"], "completed")
        self.assertEqual(result["usage"]["cells"]["build"]["attempts"], 2)
        self.assertEqual(result["usage"]["cells"]["verify"]["attempts"], 1)
        self.assertEqual(result["summary"]["used"], 320); self.assertEqual(result["summary"]["metrics"]["modelCalls"], 3)
        self.assertEqual(result["usage"]["cells"]["build"]["artifacts"], ["src/result.py"])
        self.assertIn("cell_retry_scheduled", checkpoints)

    def test_runner_stops_before_human_gated_action(self):
        mission = two_cell_mission(); mission["cells"][0]["actions"] = ["deploy"]
        result = run_hive(plan=create_plan(mission), target="mock", driver=create_mock_driver({}), workspace=".")
        self.assertEqual(result["state"]["status"], "blocked"); self.assertEqual(result["state"]["reason"], "approval_required:deploy")
        self.assertEqual(result["summary"]["metrics"]["modelCalls"], 0)

    def test_runner_stops_when_call_crosses_spendable_budget(self):
        mission = two_cell_mission(); mission["budget"] = {"unit": "tokens", "total": 100, "reservePercent": 20}
        result = run_hive(plan=create_plan(mission), target="mock", driver=create_mock_driver({"cells": {
            "build": {"status": "done", "evidence": ["built"], "metrics": metric(85, 5)},
            "verify": {"status": "done", "evidence": ["verified"], "metrics": metric(1, 1)}}}), workspace=".")
        self.assertEqual(result["state"]["status"], "budget_exhausted"); self.assertNotIn("verify", result["usage"]["cells"])

    def test_runner_blocks_success_without_budget_telemetry(self):
        result = run_hive(plan=create_plan(two_cell_mission()), target="mock",
                          driver=create_mock_driver({"cells": {"build": {"status": "done", "artifacts": ["src/result.py"]}}}))
        self.assertEqual(result["state"]["status"], "blocked")
        self.assertIn("token usage", result["usage"]["cells"]["build"]["blockers"][0])

    def test_runner_requires_guard_and_evidence(self):
        no_guard = two_cell_mission(); no_guard["cells"] = [no_guard["cells"][0]]
        with self.assertRaisesRegex(ValueError, "required guard cell"):
            run_hive(plan=create_plan(no_guard), target="mock", driver=create_mock_driver({}))
        result = run_hive(plan=create_plan(two_cell_mission()), target="mock",
                          driver=create_mock_driver({"cells": {"build": {"status": "done", "metrics": metric(10, 2)}}}))
        self.assertEqual(result["state"]["status"], "blocked"); self.assertEqual(result["usage"]["cells"]["build"]["attempts"], 2)
        self.assertIn("without verifiable evidence", result["usage"]["cells"]["build"]["blockers"][0])

    def test_runner_stops_for_rebalance_after_cell_overrun(self):
        plan = create_plan(two_cell_mission()); allocation = next(cell for cell in plan["cells"] if cell["id"] == "build")["allocation"]
        result = run_hive(plan=plan, target="mock", driver=create_mock_driver({"cells": {
            "build": {"status": "done", "evidence": ["built"], "metrics": metric(allocation, 1)}}}))
        self.assertEqual(result["state"]["reason"], "cell_allocation_overrun:build"); self.assertNotIn("verify", result["usage"]["cells"])

    def test_explicit_resume_retries_previously_blocked_cell(self):
        plan = create_plan(two_cell_mission())
        first = run_hive(plan=plan, target="mock", workspace=".", driver=create_mock_driver({"cells": {
            "build": {"status": "done", "evidence": ["build verified"], "metrics": metric(10, 2)},
            "verify": {"status": "blocked", "blockers": ["need fixture"], "metrics": metric(5, 1)}}}))
        checkpoints = []
        resumed = run_hive(plan=plan, usage=first["usage"], run_state=first["state"], resume_blocked=True,
            target="mock", workspace=".", driver=create_mock_driver({"cells": {
                "verify": {"status": "done", "evidence": ["fixture supplied"], "metrics": metric(5, 1)}}}),
            on_checkpoint=checkpoints.append)
        self.assertEqual(resumed["state"]["status"], "completed"); self.assertEqual(resumed["usage"]["cells"]["verify"]["attempts"], 2)
        started = next(event for event in checkpoints if event["type"] == "cell_started")
        self.assertIsNone(started["state"]["finishedAt"])

    def test_runner_rechecks_global_budget_between_ready_cells(self):
        mission = two_cell_mission(); mission["policy"]["maxWorkers"] = 2
        mission["budget"] = {"unit": "tokens", "total": 100, "reservePercent": 20}
        mission["cells"][1]["dependencies"] = []; mission["cells"][1]["priority"] = 4
        result = run_hive(plan=create_plan(mission), target="mock", driver=create_mock_driver({"cells": {
            "build": {"status": "done", "evidence": ["built"], "metrics": metric(85, 5)},
            "verify": {"status": "done", "evidence": ["verified"], "metrics": metric(1, 1)}}}))
        self.assertEqual(result["state"]["status"], "budget_exhausted"); self.assertNotIn("verify", result["usage"]["cells"])

    def test_driver_parsers_require_structured_worker_contract(self):
        contract = 'HIVE_RESULT_JSON:{"status":"done","artifacts":["a.md"],"evidence":["ok"],"blockers":[],"reusable_context":["fact"]}'
        direct = parse_worker_result(contract, {"exitCode": 0, "metrics": metric(1, 1)})
        self.assertEqual(direct["status"], "done"); self.assertEqual(direct["reusableContext"], ["fact"])
        codex = parse_codex_output("\n".join([json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": contract}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4,
                                                               "output_tokens": 3, "reasoning_output_tokens": 2}})]),
            {"exitCode": 0, "elapsedMs": 20})
        self.assertEqual(codex["metrics"]["cachedInputTokens"], 4)
        claude = parse_claude_output(json.dumps({"result": contract, "num_turns": 2, "total_cost_usd": 0.01,
            "usage": {"input_tokens": 8, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2, "output_tokens": 4}}),
            {"exitCode": 0, "elapsedMs": 30})
        self.assertEqual(claude["metrics"]["cachedInputTokens"], 5); self.assertEqual(claude["metrics"]["inputTokens"], 13)
        self.assertEqual(claude["metrics"]["modelCalls"], 2); self.assertEqual(claude["metrics"]["costUsd"], 0.01)
        timed_out = parse_worker_result(contract, {"exitCode": 124, "stderr": "Driver timed out."})
        self.assertEqual(timed_out["status"], "failed"); self.assertIn("timed out", timed_out["blockers"][0])

    def test_cli_run_writes_resumable_state_and_payloads(self):
        with tempfile.TemporaryDirectory(prefix="agent-hive-run-") as directory:
            root = Path(directory); mission_path, scenario_path, state = root / "mission.json", root / "mock.json", root / ".hive"
            mission_path.write_text(json.dumps(two_cell_mission()), encoding="utf-8")
            scenario_path.write_text(json.dumps({"cells": {
                "build": {"status": "done", "artifacts": ["result.py"], "evidence": ["built"], "metrics": metric(10, 2)},
                "verify": {"status": "done", "evidence": ["verified"], "metrics": metric(5, 1)}}}), encoding="utf-8")
            io = FakeIO(); result = run_cli(["run", str(mission_path), "--target", "mock", "--state-dir", str(state),
                "--workspace", directory, "--mock-results", str(scenario_path)], io)
            self.assertEqual(result["state"]["status"], "completed")
            self.assertEqual(json.loads((state / "run.json").read_text(encoding="utf-8"))["status"], "completed")
            self.assertEqual(json.loads((state / "usage.json").read_text(encoding="utf-8"))["cells"]["verify"]["status"], "done")
            self.assertIn("HIVE/1", (state / "payloads" / "build.hive").read_text(encoding="utf-8"))
            self.assertTrue(any("Hive run completed" in str(line) for line in io.output))

    def test_cli_resume_reuses_saved_target(self):
        with tempfile.TemporaryDirectory(prefix="agent-hive-resume-") as directory:
            root = Path(directory); mission, first_path, resume_path, state = root / "mission.json", root / "first.json", root / "resume.json", root / ".hive"
            mission.write_text(json.dumps(two_cell_mission()), encoding="utf-8")
            first_path.write_text(json.dumps({"cells": {
                "build": {"status": "done", "evidence": ["build verified"], "metrics": metric(10, 2)},
                "verify": {"status": "blocked", "blockers": ["fixture missing"], "metrics": metric(5, 1)}}}), encoding="utf-8")
            io = FakeIO(); first = run_cli(["run", str(mission), "--target", "mock", "--state-dir", str(state), "--workspace", directory, "--mock-results", str(first_path)], io)
            self.assertEqual(first["state"]["status"], "blocked")
            resume_path.write_text(json.dumps({"cells": {"verify": {"status": "done", "evidence": ["fixture verified"], "metrics": metric(5, 1)}}}), encoding="utf-8")
            resumed = run_cli(["run", "--resume", "--state-dir", str(state), "--workspace", directory, "--mock-results", str(resume_path)], io)
            self.assertEqual(resumed["state"]["status"], "completed"); self.assertEqual(resumed["usage"]["cells"]["verify"]["attempts"], 2)
            with self.assertRaisesRegex(ValueError, "Cannot resume workspace"):
                run_cli(["run", "--resume", "--state-dir", str(state), "--workspace", str(root / "other"), "--mock-results", str(resume_path)], io)

    def test_cli_process_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="agent-hive-exit-") as directory:
            root = Path(directory); mission, gated = root / "mission.json", root / "gated.json"
            mission.write_text(json.dumps(two_cell_mission()), encoding="utf-8")
            gated_mission = two_cell_mission(); gated_mission["cells"][0]["actions"] = ["deploy"]
            gated.write_text(json.dumps(gated_mission), encoding="utf-8")
            hive = Path(__file__).parents[1] / "hive.py"
            def execute(arguments):
                return subprocess.run([sys.executable, str(hive), *arguments], capture_output=True, text=True, timeout=30,
                                      env={**os.environ, "PYTHONUTF8": "1"})
            success = execute(["run", str(mission), "--target", "codex", "--dry-run", "--state-dir", str(root / "clean"), "--workspace", directory])
            controlled = execute(["run", str(gated), "--target", "codex", "--dry-run", "--state-dir", str(root / "gated"), "--workspace", directory])
            invalid = execute(["run", str(root / "missing.json"), "--dry-run"])
            self.assertEqual(success.returncode, 0, success.stderr); self.assertEqual(controlled.returncode, 2, controlled.stderr); self.assertEqual(invalid.returncode, 1)


if __name__ == "__main__":
    unittest.main()
