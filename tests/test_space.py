from __future__ import annotations

import unittest

from space.hive_playground import build_playground_result


class SpacePlaygroundTests(unittest.TestCase):
    def test_builds_safe_multilingual_plan(self):
        result = build_playground_result(
            "הוסף אימות דו-שלבי", "שמור תאימות", "אל תדליף סודות", "הבדיקות עוברות",
            50_000, 20, 2, "balanced", "codex",
        )
        self.assertEqual(sum(row[3] for row in result["planRows"]), 40_000)
        self.assertIn("הוסף אימות דו-שלבי", result["mission"]["mission"]["goal"])
        self.assertIn("NETWORK: denied", result["payloads"])
        self.assertEqual(result["guardrails"]["allowNetwork"], False)

    def test_rejects_empty_or_oversized_input(self):
        with self.assertRaisesRegex(ValueError, "Enter a mission"):
            build_playground_result("", "", "", "", 10_000, 20, 2, "economy", "generic")
        with self.assertRaisesRegex(ValueError, "at most 20"):
            build_playground_result("goal", "\n".join(str(i) for i in range(21)), "", "", 10_000, 20, 2, "economy", "generic")


if __name__ == "__main__":
    unittest.main()
