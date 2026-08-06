from __future__ import annotations

import ntpath
import posixpath
from typing import Any


def evaluate_gate(plan: dict[str, Any] | None, request: dict[str, Any] | None = None) -> dict[str, Any]:
    guardrails = (plan or {}).get("guardrails", {})
    request = request or {}
    action = str(request.get("action") or "read").strip().lower()
    paths = [_normalize_path(value) for value in request.get("paths") or []]
    denied = guardrails.get("deniedPathPrefixes") or []
    allowed = guardrails.get("allowedPathPrefixes") or []
    if action == "network" and guardrails.get("allowNetwork") is not True:
        return _decision("deny", "network_disabled", action, paths)
    if action in {"write", "delete", "external-write"} and allowed and not paths:
        return _decision("deny", "path_required_for_allowlist", action, paths)
    for candidate in paths:
        if candidate.startswith("!outside:"):
            return _decision("deny", f"outside_workspace:{candidate[9:]}", action, paths)
        if any(_within_prefix(candidate, prefix) for prefix in denied):
            return _decision("deny", f"denied_path:{candidate}", action, paths)
        if allowed and not any(_within_prefix(candidate, prefix) for prefix in allowed):
            return _decision("deny", f"outside_allowed_paths:{candidate}", action, paths)
    gated = [str(item).lower() for item in guardrails.get("humanApprovalActions") or []]
    if action in gated and request.get("humanApproved") is not True:
        return _decision("human_required", f"approval_required:{action}", action, paths)
    return _decision("allow", "policy_passed", action, paths)


def _decision(result: str, reason: str, action: str, paths: list[str]) -> dict[str, Any]:
    return {"result": result, "reason": reason, "action": action, "paths": paths, "allowed": result == "allow"}


def _normalize_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    normalized = posixpath.normpath(text or ".")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == ".." or normalized.startswith("../") or posixpath.isabs(normalized) or ntpath.isabs(text):
        return f"!outside:{normalized}"
    return normalized.lower()


def _within_prefix(candidate: str, raw_prefix: str) -> bool:
    prefix = _normalize_path(raw_prefix).rstrip("/")
    return candidate == prefix or candidate.startswith(prefix + "/") or (prefix == ".env" and candidate.startswith(".env."))
