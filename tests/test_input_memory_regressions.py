from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agent_hive.memory import ScopedMemory
from agent_hive.drivers import create_mock_driver
from agent_hive.mission import default_mission, validate_mission
from agent_hive.planner import create_plan
from agent_hive.runner import run_hive
from tests.helpers import metric


class MissionCellsValidationTests(unittest.TestCase):
    def test_present_non_array_cells_are_rejected_before_planning(self):
        for cells in (None, False, True, 0, 1, 1.5, "", "build", {}, {"unexpected": "object"}):
            with self.subTest(cells=cells):
                mission = default_mission()
                mission["cells"] = cells
                self.assertIn("cells must be an array.", validate_mission(mission))
                with self.assertRaisesRegex(ValueError, r"cells must be an array\."):
                    create_plan(mission)

    def test_missing_and_empty_cells_keep_the_default_route(self):
        expected = ["scout", "forager", "architect", "builder", "guard", "keeper"]
        for omit in (False, True):
            with self.subTest(omit=omit):
                mission = default_mission()
                if omit:
                    mission.pop("cells")
                self.assertEqual(validate_mission(mission), [])
                self.assertEqual([cell["role"] for cell in create_plan(mission)["cells"]], expected)

    def test_declared_cell_array_remains_supported(self):
        mission = default_mission()
        mission["cells"] = [{"id": "inspect", "title": "Inspect", "role": "scout",
                             "priority": 1, "complexity": 1, "risk": 1, "dependencies": []}]
        self.assertEqual(validate_mission(mission), [])
        self.assertEqual([cell["id"] for cell in create_plan(mission)["cells"]], ["inspect"])

    def test_default_graph_has_no_unguarded_keeper_write_and_completes(self):
        plan = create_plan(default_mission())
        keeper = next(cell for cell in plan["cells"] if cell["role"] == "keeper")
        self.assertEqual(keeper["actions"], ["read"])
        driver = create_mock_driver({"cells": {
            cell["id"]: {"status": "done", "evidence": [f"Verified {cell['id']}"],
                         "reusableContext": [f"Summary for {cell['id']}"], "metrics": metric(10, 2)}
            for cell in plan["cells"]
        }})
        result = run_hive(plan=plan, target="mock", driver=driver)
        self.assertEqual(result["state"]["status"], "completed")
        self.assertEqual(result["usage"]["cells"][keeper["id"]]["reusableContext"],
                         [f"Summary for {keeper['id']}"])


class MemoryQueryExpiryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.events = []
        self.memory = ScopedMemory(clock=lambda: self.now, on_event=self.events.append)
        self.record = self.memory.write({"scope": "mission", "namespace": "expiry-test",
                                         "content": "Temporary fact", "ttlMs": 1000})

    def query_at(self, milliseconds):
        return self.memory.query({"scope": "mission", "namespace": "expiry-test",
                                  "now": self.now + timedelta(milliseconds=milliseconds)})

    def test_record_is_available_before_ttl_and_excluded_at_exact_boundary(self):
        self.assertEqual([row["id"] for row in self.query_at(999)], [self.record["id"]])
        self.assertEqual(self.query_at(1000), [])
        self.assertEqual(self.query_at(1001), [])

    def test_query_does_not_delete_refresh_or_emit_read_for_expired_records(self):
        before = self.memory.export()
        event_count = len(self.events)
        self.assertEqual(self.query_at(1001), [])
        self.assertEqual(self.memory.export(), before)
        self.assertEqual(len(self.events), event_count)
        self.assertEqual(self.memory.decay(now=self.now + timedelta(milliseconds=1001))["deleted"], 1)

    def test_restored_expired_record_is_excluded_without_decay(self):
        restored = ScopedMemory(records=self.memory.export()["records"],
                                clock=lambda: self.now + timedelta(seconds=2))
        self.assertEqual(restored.query({"scope": "mission", "namespace": "expiry-test"}), [])

    def test_explicit_null_ttl_remains_queryable_after_elapsed_time(self):
        permanent = self.memory.write({"scope": "mission", "namespace": "expiry-test",
                                       "content": "Persistent fact", "ttlMs": None})
        self.assertEqual([row["id"] for row in self.query_at(1001)], [permanent["id"]])


if __name__ == "__main__":
    unittest.main()
