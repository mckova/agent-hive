from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_hive.mission import normalized_mission
from agent_hive.prompt_compiler import compare_mission_variants
from agent_hive.token_counter import heuristic_count


def main() -> int:
    rows = []
    for sample in ("japanese-release.json", "arabic-api.json", "spanish-migration.json"):
        raw = json.loads((ROOT / "examples" / "missions" / sample).read_text(encoding="utf-8"))
        mission = normalized_mission(raw)["mission"]
        compared = compare_mission_variants(mission, heuristic_count)
        source = next(row for row in compared if row["name"] == "source")
        best = compared[0]
        rows.append({"sample": sample, "language": mission["sourceLanguage"], "sourceEstimate": source["tokens"],
                     "bestVariant": best["name"], "bestEstimate": best["tokens"],
                     "estimatedChange": f"{round((best['tokens'] - source['tokens']) / source['tokens'] * 100)}%",
                     "literalsPreserved": best["literalsPreserved"]})
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    print("All counts use the utf8-bytes/4 planning heuristic. They are not model tokenizer benchmarks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
