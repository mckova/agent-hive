from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Callable


def mission_fingerprint(mission: dict[str, Any]) -> str:
    canonical = json.dumps({
        "goal": mission["goal"], "sourceLanguage": mission["sourceLanguage"],
        "responseLanguage": mission["responseLanguage"], "must": mission.get("must"),
        "avoid": mission.get("avoid"), "doneWhen": mission.get("doneWhen"),
    }, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def render_mission_variants(mission: dict[str, Any]) -> list[dict[str, Any]]:
    fingerprint = mission_fingerprint(mission)
    source = "\n".join(filter(None, [
        mission["goal"], f"Must: {'; '.join(mission.get('must') or [])}" if mission.get("must") else "",
        f"Avoid: {'; '.join(mission.get('avoid') or [])}" if mission.get("avoid") else "",
        f"Done when: {'; '.join(mission.get('doneWhen') or [])}" if mission.get("doneWhen") else "",
    ]))
    join = lambda values: " | ".join(values) if values else "none"
    hive = "\n".join([
        f"G:{mission['goal']}", f"M:{join(mission.get('must'))}", f"A:{join(mission.get('avoid'))}",
        f"D:{join(mission.get('doneWhen'))}",
        f"L:{mission['sourceLanguage']}>{mission['responseLanguage']}", f"F:{fingerprint}",
    ])
    compact = json.dumps({
        "g": mission["goal"], "m": mission.get("must"), "a": mission.get("avoid"),
        "d": mission.get("doneWhen"), "l": [mission["sourceLanguage"], mission["responseLanguage"]],
        "f": fingerprint,
    }, ensure_ascii=False, separators=(",", ":"))
    return [_variant("source", source, mission, fingerprint), _variant("hive-ir", hive, mission, fingerprint),
            _variant("compact-json", compact, mission, fingerprint)]


def _variant(name: str, text: str, mission: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    literals = [mission["goal"], *(mission.get("must") or []), *(mission.get("avoid") or []), *(mission.get("doneWhen") or [])]
    if name == "compact-json":
        decoded = json.loads(text)
        stored = [decoded["g"], *decoded["m"], *decoded["a"], *decoded["d"]]
        preserved = all(value in stored for value in literals if value)
    else:
        preserved = all(value in text for value in literals if value)
    return {"name": name, "text": text, "fingerprint": fingerprint, "chars": len(text),
            "bytes": len(text.encode("utf-8")), "literalsPreserved": preserved}


def compare_mission_variants(mission: dict[str, Any], counter: Callable[[str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for candidate in render_mission_variants(mission):
        counted = counter(candidate["text"])
        if inspect.isawaitable(counted):
            raise TypeError("Python token counters must be synchronous.")
        rows.append({**candidate, "tokens": counted["tokens"], "precision": counted["precision"],
                     "counter": counted["counter"], "note": counted.get("note", "")})
    rows.sort(key=lambda row: (-int(row["literalsPreserved"]), row["tokens"]))
    return rows
