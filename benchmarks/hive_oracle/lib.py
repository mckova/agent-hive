from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any


def tokenize(text: Any) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(text)).lower()
    return re.sub(r"[^a-z0-9\s]", " ", normalized).split()


def bm25_rank(query: str, documents: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> list[int]:
    terms = list(dict.fromkeys(tokenize(query)))
    tokenized = [tokenize(document["text"]) for document in documents]
    average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
    frequencies = {term: sum(term in tokens for tokens in tokenized) for term in terms}
    scores = []
    for tokens in tokenized:
        counts = Counter(tokens); score = 0.0
        for term in terms:
            count = counts[term]
            if not count:
                continue
            frequency = frequencies[term]
            inverse = math.log(1 + (len(documents) - frequency + 0.5) / (frequency + 0.5))
            penalty = count + k1 * (1 - b + b * len(tokens) / max(1, average_length))
            score += inverse * count * (k1 + 1) / penalty
        scores.append(score)
    return sorted(range(len(scores)), key=lambda index: (-scores[index], index))


def answer_metrics(prediction: Any, expected: Any) -> dict[str, float | int]:
    predicted, wanted = _normalize_answer(prediction).split(), _normalize_answer(expected).split()
    exact = int(predicted == wanted); counts = Counter(predicted); overlap = 0
    for token in wanted:
        if counts[token] > 0:
            overlap += 1; counts[token] -= 1
    if not predicted or not wanted:
        return {"exactMatch": exact, "tokenF1": exact, "exactLoss": 1 - exact, "taskLoss": 1 - exact}
    precision, recall = overlap / len(predicted), overlap / len(wanted)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {"exactMatch": exact, "tokenF1": f1, "exactLoss": 1 - exact, "taskLoss": 1 - f1}


def aggregate_usage(calls: list[dict[str, Any]] | None = None) -> dict[str, int]:
    total = {"inputTokens": 0, "outputTokens": 0, "reasoningTokens": 0, "totalTokens": 0, "modelLatencyMs": 0}
    for call in calls or []:
        usage = call.get("usage") or {}
        total["inputTokens"] += usage.get("input_tokens", 0); total["outputTokens"] += usage.get("output_tokens", 0)
        total["reasoningTokens"] += (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
        total["totalTokens"] += usage.get("total_tokens", usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
        total["modelLatencyMs"] += call.get("latencyMs", 0)
    return total


def enforce_answer_contract(question: Any, answer: Any) -> str:
    trimmed = str(answer or "").strip()
    if not re.match(r"^(are|is|was|were|do|does|did|can|could|will|would|has|have|had)\b", str(question).strip(), re.I):
        return trimmed
    if re.match(r"^yes(?:\b|[.,;:])", trimmed, re.I): return "yes"
    if re.match(r"^no(?:\b|[.,;:])", trimmed, re.I): return "no"
    return trimmed


def aggregate_methods(examples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    names = list(dict.fromkeys(name for example in examples for name in (example.get("systems") or {})))
    output = {}
    for name in names:
        rows = [example["systems"][name] for example in examples if name in (example.get("systems") or {})]
        usage = {key: sum((row.get("usage") or {}).get(key, 0) for row in rows)
                 for key in ("inputTokens", "outputTokens", "reasoningTokens", "totalTokens")}
        output[name] = {"examples": len(rows), "calls": sum(len(row.get("calls") or []) for row in rows),
            "exactMatch": _mean([row["quality"]["exactMatch"] for row in rows]),
            "tokenF1": _mean([row["quality"]["tokenF1"] for row in rows]),
            "exactLoss": _mean([row["quality"]["exactLoss"] for row in rows]),
            "taskLoss": _mean([row["quality"]["taskLoss"] for row in rows]),
            "averageEndToEndLatencyMs": _mean([row["endToEndLatencyMs"] for row in rows]),
            "p50EndToEndLatencyMs": _percentile([row["endToEndLatencyMs"] for row in rows], 0.5),
            "usage": usage, "averageTokensPerExample": usage["totalTokens"] / len(rows) if rows else 0}
    return output


def _normalize_answer(text: Any) -> str:
    value = re.sub(r"\b(a|an|the)\b", " ", str(text).lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", value)).strip()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[math.floor((len(values) - 1) * fraction)] if values else 0
