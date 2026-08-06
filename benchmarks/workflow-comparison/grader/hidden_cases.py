from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any, Callable


def run_hidden_cases(target_directory: str | Path) -> list[dict[str, Any]]:
    source = Path(target_directory) / "src" / "rate_limiter.py"
    spec = importlib.util.spec_from_file_location("bench_rate_limiter", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("implementation does not load")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    factory = getattr(module, "create_rate_limiter", None)

    def invalid_options():
        for options in ({"capacity": 0, "refill_per_second": 1}, {"capacity": 1, "refill_per_second": math.inf},
                        {"capacity": 1, "refill_per_second": 1, "max_keys": 1.5}):
            _raises(TypeError, lambda value=options: factory(value))

    def invalid_calls():
        limiter = factory({"capacity": 2, "refill_per_second": 1})
        for call in (lambda: limiter.allow("", 1, 0), lambda: limiter.allow("x", 0, 0),
                     lambda: limiter.allow("x", 1, math.nan), lambda: limiter.peek("", 0)):
            _raises(TypeError, call)

    cases: list[tuple[str, Callable[[], None], str]] = [
        ("exports factory", lambda: _assert(callable(factory)), "functional"),
        ("rejects invalid options", invalid_options, "security"),
        ("rejects invalid calls", invalid_calls, "security"),
        ("supports fractional refill", lambda: _fractional(factory), "functional"),
        ("caps refill", lambda: _caps(factory), "functional"),
        ("denial advances monotonic refill time", lambda: _denial_time(factory), "functional"),
        ("backwards time neither refills nor rewinds", lambda: _backwards(factory), "security"),
        ("uses LRU eviction", lambda: _lru(factory), "security"),
        ("handles arbitrary keys safely", lambda: _keys(factory), "security"),
        ("does not consume on peek", lambda: _peek(factory), "functional"),
        ("resets one or all buckets", lambda: _reset(factory), "functional"),
        ("does not create background threads", lambda: _no_threads(factory), "security"),
    ]
    results = []
    for name, execute, category in cases:
        try:
            execute(); results.append({"name": name, "category": category, "passed": True})
        except Exception as error:
            results.append({"name": name, "category": category, "passed": False, "error": str(error)})
    return results


def _fractional(factory):
    limiter = factory({"capacity": 3, "refill_per_second": 0.5}); limiter.allow("x", 3, 100); _equal(limiter.peek("x", 600), 0.25)


def _caps(factory):
    limiter = factory({"capacity": 2, "refill_per_second": 100}); limiter.allow("x", 2, 0); _equal(limiter.peek("x", 5000), 2)


def _denial_time(factory):
    limiter = factory({"capacity": 2, "refill_per_second": 1}); limiter.allow("x", 2, 0)
    _equal(limiter.allow("x", 2, 1000), False); _equal(limiter.peek("x", 1500), 1.5)


def _backwards(factory):
    limiter = factory({"capacity": 2, "refill_per_second": 1}); limiter.allow("x", 2, 1000)
    _equal(limiter.peek("x", 500), 0); _equal(limiter.peek("x", 1500), 0.5)


def _lru(factory):
    limiter = factory({"capacity": 2, "refill_per_second": 1, "max_keys": 2})
    limiter.allow("a", 2, 0); limiter.allow("b", 2, 0); limiter.peek("a", 0); limiter.allow("c", 2, 0)
    _equal(limiter.size, 2); _equal(limiter.allow("b", 2, 0), True)


def _keys(factory):
    limiter = factory({"capacity": 1, "refill_per_second": 1})
    _equal(limiter.allow("__proto__", 1, 0), True); _equal(limiter.allow("constructor", 1, 0), True); _equal(limiter.size, 2)


def _peek(factory):
    limiter = factory({"capacity": 5, "refill_per_second": 1})
    _equal(limiter.peek("x", 0), 5); _equal(limiter.peek("x", 0), 5); _equal(limiter.allow("x", 5, 0), True)


def _reset(factory):
    limiter = factory({"capacity": 1, "refill_per_second": 1}); limiter.allow("a", 1, 0); limiter.allow("b", 1, 0)
    limiter.reset("a"); _equal(limiter.size, 1); _equal(limiter.allow("a", 1, 0), True); limiter.reset(); _equal(limiter.size, 0)


def _no_threads(factory):
    import threading
    before = len(threading.enumerate()); limiter = factory({"capacity": 1, "refill_per_second": 1})
    for index in range(100): limiter.allow(f"key-{index}", 1, index)
    _assert(len(threading.enumerate()) <= before)


def _raises(kind, call):
    try: call()
    except kind: return
    raise AssertionError(f"expected {kind.__name__}")


def _assert(value):
    if not value: raise AssertionError("assertion failed")


def _equal(actual, expected):
    if actual != expected: raise AssertionError(f"{actual!r} != {expected!r}")
