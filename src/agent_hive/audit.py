from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .planner import iso_now

SECRET_KEY = re.compile(r"authorization|api[-_]?key|secret|password|access[-_]?token|refresh[-_]?token|cookie", re.I)
CONTENT_KEY = re.compile(r"^(prompt|input|content|memory|reusableContext|messages)$", re.I)


def append_audit(file_path: str | Path, event: dict[str, Any], clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    safe = redact({"schemaVersion": 1, "at": iso_now(clock() if clock else None), **event})
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")
    return safe


def redact(value: Any, key: str = "") -> Any:
    if SECRET_KEY.search(key) or key.lower() == "token" or CONTENT_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {child_key: redact(child, child_key) for child_key, child in value.items()}
    return value
