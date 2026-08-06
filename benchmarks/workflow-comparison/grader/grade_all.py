from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from grade import grade

ARMS = ["normal", "caveman", "ralph", "loop-engineering", "agent-hive"]


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments: raise SystemExit("Usage: python grade_all.py <run-root>")
    root = Path(arguments[0]).resolve(); grades = []
    for arm in ARMS:
        try: grades.append({"arm": arm, **grade(root / arm)})
        except Exception as error: grades.append({"arm": arm, "artifactScore": 0, "graderError": str(error)})
    report = {"schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "runRoot": str(root), "grades": grades}
    (root / "grades.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in grades:
        print(f"{row['arm']}: {row.get('artifactScore', 0)}/40")


if __name__ == "__main__": main()
