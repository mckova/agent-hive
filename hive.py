#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src"
if SOURCE.is_dir():
    sys.path.insert(0, str(SOURCE))

from agent_hive.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
