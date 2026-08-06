from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_hive.cli import run_cli
from agent_hive.mission import default_mission
from tests.helpers import FakeIO


class CliTests(unittest.TestCase):
    def test_cli_completes_plan_next_record_compare_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="agent-hive-test-") as directory:
            root = Path(directory); mission, plan, usage = root / "mission.json", root / "plan.json", root / "usage.json"
            mission.write_text(json.dumps(default_mission()), encoding="utf-8"); io = FakeIO()
            run_cli(["plan", str(mission), "--out", str(plan)], io)
            run_cli(["next", str(plan), "--usage", str(usage)], io)
            run_cli(["record", "survey", "--status", "done", "--used", "123", "--artifact", "map.md",
                     "--plan", str(plan), "--usage", str(usage)], io)
            run_cli(["compare", str(mission), "--counter", "heuristic"], io)
            stored = json.loads(usage.read_text(encoding="utf-8"))["cells"]["survey"]
            self.assertEqual(stored["status"], "done"); self.assertEqual(stored["used"], 123); self.assertEqual(stored["attempts"], 1)
            self.assertEqual(stored["artifacts"], ["map.md"])
            self.assertTrue(any(isinstance(value, list) and any(row.get("id") == "survey" for row in value) for value in io.output))


if __name__ == "__main__":
    unittest.main()
