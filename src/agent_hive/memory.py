from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from .planner import iso_now

SCOPES = {"user", "project", "session", "mission", "team", "agent"}


class ScopedMemory:
    def __init__(self, records: list[dict[str, Any]] | None = None, clock: Callable[[], datetime] | None = None,
                 on_event: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.on_event = on_event or (lambda _event: None)
        self.records: dict[str, dict[str, Any]] = {}
        self.sequence = 0
        for record in records or []:
            self.restore(record)

    def write(self, value: dict[str, Any]) -> dict[str, Any]:
        _assert_scope(value.get("scope"))
        namespace, content = value.get("namespace"), value.get("content")
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("memory.namespace must be a non-empty string.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("memory.content must be a non-empty string.")
        now = _date(value.get("now") or self.clock())
        self.sequence += 1
        identifier = value.get("id") or f"mem-{self.sequence}"
        if identifier in self.records:
            raise ValueError(f"Duplicate memory id: {identifier}")
        scope, namespace = value["scope"], namespace.strip()
        record = {"id": identifier, "scope": scope, "namespace": namespace, "kind": value.get("kind") or "context",
            "content": content, "trust": "trusted" if value.get("trust") == "trusted" else "untrusted",
            "confidence": _unit(value.get("confidence"), 1), "relevance": _unit(value.get("relevance"), 1),
            "sourceQuality": _unit(value.get("sourceQuality"), 1 if value.get("trust") == "trusted" else 0.5),
            "verifiedUtility": _unit(value.get("verifiedUtility"), 1 if value.get("trust") == "trusted" else 0.5),
            "sensitivity": _unit(value.get("sensitivity"), 0), "reuseCount": _non_negative_int(value.get("reuseCount"), 0),
            "halfLifeMs": _positive(value.get("halfLifeMs"), 60 * 60 * 1000),
            "ttlMs": None if value.get("ttlMs", "missing") is None else _positive(value.get("ttlMs"), 24 * 60 * 60 * 1000),
            "status": value.get("status") or "active", "visibility": _clean_visibility(value.get("visibility"), scope, namespace),
            "createdAt": iso_now(now), "lastUsedAt": iso_now(now),
            "metadata": deepcopy(value.get("metadata")) if isinstance(value.get("metadata"), dict) else {}}
        self.records[identifier] = record
        self._emit("memory.write", record)
        return deepcopy(record)

    def query(self, value: dict[str, Any]) -> list[dict[str, Any]]:
        _assert_scope(value.get("scope"))
        namespace = value.get("namespace")
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("query.namespace must be a non-empty string.")
        now, role = _date(value.get("now") or self.clock()), value.get("role")
        minimum = _finite(value.get("minimumScore"), 0)
        limit = _positive_int(value.get("limit"), 10)
        maximum_sensitivity = _unit(value.get("maxSensitivity"), 0.5)
        rows = []
        for record in self.records.values():
            if record["scope"] != value["scope"] or record["namespace"] != namespace or record["status"] not in {"active", "cooling"}:
                continue
            if not ("*" in record["visibility"] or (role and role in record["visibility"])):
                continue
            if value.get("trustedOnly") is True and record["trust"] != "trusted":
                continue
            if record["sensitivity"] > maximum_sensitivity:
                continue
            row = {**deepcopy(record), "retentionScore": retention_score(record, now)}
            if row["retentionScore"] >= minimum:
                rows.append(row)
        rows.sort(key=lambda row: (-row["retentionScore"], row["id"]))
        rows = rows[:limit]
        for row in rows:
            stored = self.records[row["id"]]
            stored["lastUsedAt"] = iso_now(now)
            self._emit("memory.read", stored, {"role": role or "*", "retentionScore": row["retentionScore"]})
        return deepcopy(rows)

    def reinforce(self, identifier: str, verified: bool = False, successful: bool = False,
                  now: datetime | None = None) -> dict[str, Any]:
        record = self.records.get(identifier)
        if record is None:
            raise ValueError(f"Unknown memory id: {identifier}")
        if not verified or not successful:
            self._emit("memory.reinforce_skipped", record)
            return deepcopy(record)
        record["reuseCount"] += 1
        record["verifiedUtility"] = min(1, record["verifiedUtility"] + 0.05)
        record["lastUsedAt"], record["status"] = iso_now(_date(now or self.clock())), "active"
        self._emit("memory.reinforced", record)
        return deepcopy(record)

    def decay(self, now: datetime | None = None, cooling_threshold: float = 0.4,
              archive_threshold: float = 0.2, delete_threshold: float = 0.05) -> dict[str, int]:
        current, summary = _date(now or self.clock()), {"cooled": 0, "archived": 0, "deleted": 0}
        for record in list(self.records.values()):
            age = (current - _date(record["createdAt"])).total_seconds() * 1000
            expired = record["ttlMs"] is not None and age >= record["ttlMs"]
            score = retention_score(record, current)
            if expired or score < delete_threshold:
                self.records.pop(record["id"])
                summary["deleted"] += 1
                self._emit("memory.deleted", record, {"expired": expired, "retentionScore": score})
            elif score < archive_threshold:
                record["status"] = "archived"
                summary["archived"] += 1
                self._emit("memory.archived", record, {"retentionScore": score})
            elif score < cooling_threshold and record["status"] == "active":
                record["status"] = "cooling"
                summary["cooled"] += 1
                self._emit("memory.cooled", record, {"retentionScore": score})
        return summary

    def delete_scope(self, scope: str, namespace: str, reason: str = "scope_expired") -> int:
        _assert_scope(scope)
        deleted = 0
        for record in list(self.records.values()):
            if record["scope"] == scope and record["namespace"] == namespace:
                self.records.pop(record["id"])
                deleted += 1
                self._emit("memory.deleted", record, {"reason": reason})
        return deleted

    def snapshot(self, include_content: bool = False) -> list[dict[str, Any]]:
        rows = deepcopy(list(self.records.values()))
        if not include_content:
            for row in rows:
                row.pop("content", None)
        return rows

    def export(self) -> dict[str, Any]:
        return {"schemaVersion": 1, "records": self.snapshot(include_content=True)}

    def restore(self, value: dict[str, Any]) -> None:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise ValueError("Invalid memory record.")
        _assert_scope(value.get("scope"))
        record = deepcopy(value)
        record["trust"] = "trusted" if value.get("trust") == "trusted" else "untrusted"
        record["visibility"] = _clean_visibility(value.get("visibility"), value["scope"], value["namespace"])
        _date(record["createdAt"]); _date(record["lastUsedAt"])
        self.records[record["id"]] = record
        if record["id"].startswith("mem-") and record["id"][4:].isdigit():
            self.sequence = max(self.sequence, int(record["id"][4:]))

    def _emit(self, event_type: str, record: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
        self.on_event({"type": event_type, "memoryId": record["id"], "scope": record["scope"],
                       "namespace": record["namespace"], "kind": record["kind"], "at": iso_now(self.clock()), **(extra or {})})


def retention_score(record: dict[str, Any], now: datetime | None = None) -> float:
    current = _date(now or datetime.now(timezone.utc))
    age = max(0, (current - _date(record.get("lastUsedAt") or record["createdAt"])).total_seconds() * 1000)
    strength = 2 ** (-age / _positive(record.get("halfLifeMs"), 1))
    reuse = min(0.2, math.log2(1 + _non_negative_int(record.get("reuseCount"), 0)) * 0.04)
    base = strength * _unit(record.get("confidence"), 1) * _unit(record.get("relevance"), 1) * _unit(record.get("sourceQuality"), 1) * _unit(record.get("verifiedUtility"), 1)
    return max(0, min(1, base + reuse - _unit(record.get("sensitivity"), 0) * 0.25))


def _assert_scope(scope: Any) -> None:
    if scope not in SCOPES:
        raise ValueError(f"memory.scope must be one of {', '.join(sorted(SCOPES))}.")


def _clean_visibility(value: Any, scope: str, namespace: str) -> list[str]:
    if value is None:
        return [namespace] if scope == "agent" else ["*"]
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("memory.visibility must be a non-empty array of strings.")
    return list(dict.fromkeys(item.strip() for item in value))


def _unit(value: Any, fallback: float) -> float:
    number = _finite(value, fallback)
    return max(0, min(1, number))


def _positive(value: Any, fallback: float) -> float:
    number = _finite(value, fallback)
    return number if number > 0 else fallback


def _finite(value: Any, fallback: float) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else fallback
    except (TypeError, ValueError):
        return fallback


def _positive_int(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else fallback


def _non_negative_int(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else fallback


def _date(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Invalid memory timestamp.") from error
    else:
        raise ValueError("Invalid memory timestamp.")
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
