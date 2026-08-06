from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agent_hive.control import GoalController, HookBus
from agent_hive.memory import ScopedMemory, retention_score


class MemoryControlTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_scoped_memory_does_not_cross_namespaces_or_visibility(self):
        memory = ScopedMemory(clock=lambda: self.now)
        memory.write({"scope": "project", "namespace": "alpha", "content": "A", "visibility": ["builder"]})
        memory.write({"scope": "project", "namespace": "beta", "content": "B", "visibility": ["builder"]})
        self.assertEqual(memory.query({"scope": "project", "namespace": "alpha", "role": "guard"}), [])
        self.assertEqual([row["content"] for row in memory.query({"scope": "project", "namespace": "alpha", "role": "builder"})], ["A"])

    def test_decay_deletes_expired_short_term_memory(self):
        memory = ScopedMemory(clock=lambda: self.now)
        memory.write({"scope": "agent", "namespace": "mission-1", "content": "scratch", "ttlMs": 1000})
        self.assertEqual(memory.decay(now=self.now + timedelta(milliseconds=1001))["deleted"], 1)
        self.assertEqual(memory.snapshot(), [])

    def test_reinforcement_requires_verified_successful_use(self):
        memory = ScopedMemory(clock=lambda: self.now)
        row = memory.write({"scope": "team", "namespace": "mission-1", "content": "fact", "trust": "trusted"})
        memory.reinforce(row["id"], verified=False, successful=True); self.assertEqual(memory.snapshot()[0]["reuseCount"], 0)
        memory.reinforce(row["id"], verified=True, successful=True); self.assertEqual(memory.snapshot()[0]["reuseCount"], 1)
        self.assertGreater(retention_score(memory.snapshot()[0], self.now), 0.99)

    def test_memory_export_filters_untrusted_or_sensitive_recall(self):
        original = ScopedMemory(clock=lambda: self.now)
        original.write({"scope": "mission", "namespace": "m1", "content": "verified", "trust": "trusted"})
        original.write({"scope": "mission", "namespace": "m1", "content": "web says ignore mission", "trust": "untrusted"})
        original.write({"scope": "mission", "namespace": "m1", "content": "private", "trust": "trusted", "sensitivity": 0.9})
        restored = ScopedMemory(clock=lambda: self.now, records=original.export()["records"])
        self.assertEqual([row["content"] for row in restored.query({"scope": "mission", "namespace": "m1", "trustedOnly": True})], ["verified"])
        self.assertEqual(len(restored.snapshot(include_content=True)), 3)

    def test_goal_controller_stops_on_success_and_enforces_call_budgets(self):
        hooks = HookBus(clock=lambda: self.now)
        controller = GoalController({"goal": "answer", "success": {"confidenceMin": 0.8, "evidenceMin": 2},
            "budget": {"maxModelCalls": 2, "maxIterations": 2, "maxOutputTokens": 100,
                       "maxTotalTokens": 1000, "maxLatencyMs": 5000}}, hooks=hooks)
        controller.record_call({"latencyMs": 100, "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}})
        self.assertEqual(controller.evaluate({"answer": "yes", "confidence": 0.9, "evidenceCount": 2}),
                         {"stop": True, "reason": "goal_reached", "success": True})
        self.assertEqual(controller.telemetry()["events"][0]["name"], "after_model_call")


if __name__ == "__main__":
    unittest.main()
