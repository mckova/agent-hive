from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_hive.mission import default_mission, validate_mission
from agent_hive.planner import create_plan
from agent_hive.prompt_compiler import compare_mission_variants, render_mission_variants
from agent_hive.protocol import compile_payload
from agent_hive.token_counter import anthropic_message_count, heuristic_count
from agent_hive.usage import next_ready_cells, rebalance_plan, record_cell_usage


class PlannerTests(unittest.TestCase):
    def test_allocation_preserves_total_and_protected_reserve(self):
        mission = default_mission(); mission["budget"]["total"] = 100003
        plan = create_plan(mission, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(plan["budget"]["reserve"], 20000)
        self.assertEqual(sum(cell["allocation"] for cell in plan["cells"]), plan["budget"]["total"] - plan["budget"]["reserve"])

    def test_dependency_graph_produces_ordered_waves(self):
        self.assertEqual(create_plan(default_mission())["waves"], [["survey", "forage"], ["design"], ["build"], ["verify"], ["distill"]])

    def test_default_route_becomes_mission_specific_worker_contracts(self):
        mission = default_mission()
        mission["mission"].update({
            "goal": "Add passwordless sign-in without breaking existing users",
            "must": ["Preserve existing sessions"],
            "avoid": ["Do not log authentication tokens"],
            "doneWhen": ["Security tests pass"],
        })
        plan = create_plan(mission)
        self.assertEqual([cell["role"] for cell in plan["cells"]],
                         ["scout", "forager", "architect", "builder", "guard", "keeper"])
        self.assertTrue(all(mission["mission"]["goal"] in cell["title"] for cell in plan["cells"]))
        builder = next(cell for cell in plan["cells"] if cell["role"] == "builder")
        guard = next(cell for cell in plan["cells"] if cell["role"] == "guard")
        self.assertIn("Preserve existing sessions", " ".join(builder["instructions"]))
        self.assertIn("Security tests pass", " ".join(guard["instructions"]))
        self.assertIn("LOCAL:", compile_payload(plan, builder))

    def test_hive_protocol_preserves_non_latin_mission_text(self):
        path = Path(__file__).parents[1] / "examples" / "missions" / "japanese-release.json"
        mission = json.loads(path.read_text(encoding="utf-8")); plan = create_plan(mission)
        payload = compile_payload(plan, plan["cells"][0])
        self.assertIn(mission["mission"]["goal"], payload); self.assertTrue(payload.startswith("HIVE/1"))

    def test_target_payload_resolves_configured_model_tier(self):
        mission = default_mission(); mission["models"] = {"frontier": {"codex": "gpt-example", "claude": "claude-example"}}
        plan = create_plan(mission); cell = next(cell for cell in plan["cells"] if cell["modelTier"] == "frontier")
        self.assertIn("TARGET: codex\nMODEL: gpt-example", compile_payload(plan, cell, "codex"))

    def test_prompt_variants_preserve_multilingual_literals(self):
        mission = {"goal": "צור API בשם user_id", "sourceLanguage": "he", "responseLanguage": "he",
                   "must": ["אל תשנה user_id"], "avoid": ["מחיקת נתונים"], "doneWhen": ["הבדיקות עוברות"]}
        first, second = render_mission_variants(mission), render_mission_variants(mission)
        self.assertEqual(first[0]["fingerprint"], second[0]["fingerprint"])
        self.assertTrue(all(row["literalsPreserved"] for row in first))
        compared = compare_mission_variants(mission, heuristic_count)
        self.assertTrue(all(row["precision"] == "heuristic" for row in compared))
        self.assertLessEqual(compared[0]["tokens"], compared[-1]["tokens"])

    def test_anthropic_counter_reports_provider_estimate(self):
        captured = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return b'{"input_tokens":7}'
        def urlopen(request, timeout):
            captured.append((request.full_url, json.loads(request.data), timeout)); return Response()
        result = anthropic_message_count("hola", "claude-test", {"apiKey": "test-key", "urlopen": urlopen})
        self.assertEqual(result["tokens"], 7); self.assertEqual(result["precision"], "provider-estimate")
        self.assertTrue(captured[0][0].endswith("/v1/messages/count_tokens")); self.assertEqual(captured[0][1]["messages"][0]["content"], "hola")

    def test_rebalance_protects_reserve(self):
        plan = create_plan(default_mission(), datetime(2026, 1, 1, tzinfo=timezone.utc))
        revised = rebalance_plan(plan, {"cells": {"survey": {"used": 5000, "status": "done"},
                                                        "design": {"used": 10000, "status": "in_progress"}}},
                                  datetime(2026, 1, 2, tzinfo=timezone.utc))
        open_allocation = sum(cell["allocation"] - (10000 if cell["id"] == "design" else 0)
                              for cell in revised["cells"] if cell["status"] != "done")
        self.assertEqual(open_allocation, plan["budget"]["total"] - plan["budget"]["reserve"] - 15000)
        self.assertEqual(sum(cell["allocation"] for cell in revised["cells"]), plan["budget"]["allocated"])
        self.assertEqual(revised["revision"], 2)

    def test_lifecycle_unlocks_dependencies_and_reserve_release_is_explicit(self):
        plan = create_plan(default_mission(), datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual([cell["id"] for cell in next_ready_cells(plan)], ["survey", "forage"])
        usage = record_cell_usage(plan, {}, {"id": "survey", "status": "done", "used": 1000,
                                              "artifacts": ["map.md"], "evidence": ["test"]})
        self.assertEqual([cell["id"] for cell in next_ready_cells(plan, usage)], ["forage"])
        usage = record_cell_usage(plan, usage, {"id": "forage", "status": "done", "used": 500,
                                                "artifacts": ["evidence.md"], "evidence": ["paths cited"]})
        self.assertEqual([cell["id"] for cell in next_ready_cells(plan, usage)], ["design"])
        revised = rebalance_plan(plan, usage, release_reserve=True)
        self.assertTrue(revised["budget"]["reserveReleased"]); self.assertEqual(revised["budget"]["allocated"], plan["budget"]["total"])

    def test_validation_detects_dependency_cycles(self):
        mission = default_mission(); mission["cells"] = [
            {"id": "a", "title": "A", "role": "scout", "priority": 1, "complexity": 1, "risk": 1, "dependencies": ["b"]},
            {"id": "b", "title": "B", "role": "builder", "priority": 1, "complexity": 1, "risk": 1, "dependencies": ["a"]},]
        self.assertTrue(any("cycle" in error for error in validate_mission(mission)))


if __name__ == "__main__":
    unittest.main()
