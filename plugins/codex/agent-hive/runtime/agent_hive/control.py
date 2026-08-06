from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from .audit import redact
from .planner import iso_now


class HookBus:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.handlers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self.events: list[dict[str, Any]] = []

    def on(self, name: str, handler: Callable[[dict[str, Any]], Any]) -> Callable[[], None]:
        if not callable(handler):
            raise ValueError("Hook handler must be a function.")
        self.handlers.setdefault(name, []).append(handler)
        def unsubscribe() -> None:
            self.handlers[name] = [candidate for candidate in self.handlers[name] if candidate is not handler]
        return unsubscribe

    def emit(self, name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {"name": name, "at": iso_now(self.clock()), "data": redact(data or {})}
        self.events.append(event)
        for handler in self.handlers.get(name, []):
            handler(event)
        return event

    def trace(self) -> list[dict[str, Any]]:
        return deepcopy(self.events)


class GoalController:
    def __init__(self, contract: dict[str, Any], hooks: HookBus | None = None) -> None:
        if not isinstance(contract, dict) or not isinstance(contract.get("goal"), str) or not contract["goal"].strip():
            raise ValueError("goal contract requires a non-empty goal.")
        success, budget = contract.get("success") or {}, contract.get("budget") or {}
        self.contract = {"goal": contract["goal"].strip(),
            "success": {"confidenceMin": _bounded(success.get("confidenceMin"), 0.85),
                        "evidenceMin": _non_negative_int(success.get("evidenceMin"), 1)},
            "budget": {"maxModelCalls": _positive_int(budget.get("maxModelCalls"), 2),
                       "maxIterations": _positive_int(budget.get("maxIterations"), 2),
                       "maxOutputTokens": _positive_int(budget.get("maxOutputTokens"), 512),
                       "maxTotalTokens": _positive_int(budget.get("maxTotalTokens"), 2000),
                       "maxLatencyMs": _positive(budget.get("maxLatencyMs"), 15000)}}
        self.hooks = hooks or HookBus()
        self.usage = {"calls": 0, "iterations": 0, "inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "latencyMs": 0}
        self.states: list[dict[str, Any]] = []

    def record_call(self, call: dict[str, Any]) -> dict[str, Any]:
        usage = call.get("usage") or {}
        self.usage["calls"] += 1; self.usage["iterations"] += 1
        self.usage["inputTokens"] += usage.get("input_tokens", 0)
        self.usage["outputTokens"] += usage.get("output_tokens", 0)
        self.usage["totalTokens"] += usage.get("total_tokens", usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
        self.usage["latencyMs"] += call.get("latencyMs", 0)
        self.hooks.emit("after_model_call", self.usage)
        return deepcopy(self.usage)

    def evaluate(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or {}
        normalized = {"answer": str(state.get("answer") or "").strip(), "confidence": _bounded(state.get("confidence"), 0),
                      "evidenceCount": _non_negative_int(state.get("evidenceCount"), 0), "conflict": bool(state.get("conflict"))}
        self.states.append(normalized)
        success = bool(normalized["answer"] and normalized["answer"].lower() != "unknown"
                       and normalized["confidence"] >= self.contract["success"]["confidenceMin"]
                       and normalized["evidenceCount"] >= self.contract["success"]["evidenceMin"] and not normalized["conflict"])
        if success:
            return {"stop": True, "reason": "goal_reached", "success": True}
        reason = self.budget_reason()
        if reason:
            return {"stop": True, "reason": reason, "success": False}
        if len(self.states) > 1 and all(self.states[-2][key] == normalized[key] for key in ("answer", "evidenceCount")):
            return {"stop": True, "reason": "no_new_information", "success": False}
        return {"stop": False, "reason": "repair_allowed", "success": False}

    def budget_reason(self) -> str | None:
        budget = self.contract["budget"]
        checks = (("calls", "maxModelCalls", "model_call_budget"), ("iterations", "maxIterations", "iteration_budget"),
                  ("outputTokens", "maxOutputTokens", "output_token_budget"), ("totalTokens", "maxTotalTokens", "total_token_budget"),
                  ("latencyMs", "maxLatencyMs", "latency_budget"))
        return next((reason for used, limit, reason in checks if self.usage[used] >= budget[limit]), None)

    def telemetry(self) -> dict[str, Any]:
        return {"goal": self.contract["goal"], "success": deepcopy(self.contract["success"]), "budget": deepcopy(self.contract["budget"]),
                "usage": deepcopy(self.usage), "states": deepcopy(self.states), "events": self.hooks.trace()}


def _number(value: Any, fallback: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def _bounded(value: Any, fallback: float) -> float:
    return max(0, min(1, _number(value, fallback)))


def _positive(value: Any, fallback: float) -> float:
    number = _number(value, fallback)
    return number if number > 0 else fallback


def _positive_int(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else fallback


def _non_negative_int(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else fallback
