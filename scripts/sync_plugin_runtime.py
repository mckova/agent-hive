from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "plugins" / platform / "agent-hive" / "runtime" for platform in ("codex", "claude-code")]
SPACE_MODULES = ("__init__.py", "mission.py", "planner.py", "prompt_compiler.py", "protocol.py", "token_counter.py")


def main() -> int:
    for target in TARGETS:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        shutil.copytree(ROOT / "src" / "agent_hive", target / "agent_hive", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wrapper = '''#!/usr/bin/env python3
from agent_hive.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
'''
        (target / "hive.py").write_text(wrapper, encoding="utf-8", newline="\n")
    space_target = ROOT / "space" / "agent_hive"
    if space_target.exists():
        shutil.rmtree(space_target)
    space_target.mkdir(parents=True)
    for name in SPACE_MODULES:
        shutil.copy2(ROOT / "src" / "agent_hive" / name, space_target / name)
    print(f"Synced Python runtime to {len(TARGETS)} plugins and the static Space.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
