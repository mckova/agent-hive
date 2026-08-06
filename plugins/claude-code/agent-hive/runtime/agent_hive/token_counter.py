from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable


def heuristic_count(text: str) -> dict[str, Any]:
    return {"tokens": max(1, (len(text.encode("utf-8")) + 3) // 4), "precision": "heuristic",
            "counter": "utf8-bytes/4", "note": "Planning estimate only; not a provider tokenizer."}


def openai_text_count(text: str, model: str | None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    if not model:
        raise ValueError("OpenAI counting requires --model.")
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("OpenAI tokenizer unavailable. Install the optional 'openai-count' dependency.") from error
    encoding = tiktoken.encoding_for_model(model)
    return {"tokens": len(encoding.encode(text)), "precision": "exact-text", "counter": f"tiktoken:{model}",
            "note": "Counts text tokens; API message framing may add tokens."}


def anthropic_message_count(text: str, model: str | None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    if not model:
        raise ValueError("Anthropic counting requires --model.")
    api_key = options.get("apiKey") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Anthropic counting requires ANTHROPIC_API_KEY.")
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": text}]}).encode("utf-8")
    url = f"{options.get('baseUrl', 'https://api.anthropic.com').rstrip('/')}/v1/messages/count_tokens"
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01",
    })
    opener: Callable[..., Any] = options.get("urlopen") or urllib.request.urlopen
    try:
        with opener(request, timeout=options.get("timeout", 30)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic token count failed ({error.code}): {detail}") from error
    tokens = payload.get("input_tokens")
    if not isinstance(tokens, int) or isinstance(tokens, bool):
        raise RuntimeError("Anthropic response omitted input_tokens.")
    return {"tokens": tokens, "precision": "provider-estimate", "counter": f"anthropic:{model}",
            "note": "Provider count for a one-message request."}


def create_token_counter(options: dict[str, Any] | None = None) -> Callable[[str], dict[str, Any]]:
    options = options or {}
    counter_type = options.get("type", "heuristic")
    if counter_type == "heuristic":
        return heuristic_count
    if counter_type == "openai":
        return lambda text: openai_text_count(text, options.get("model"), options)
    if counter_type == "anthropic":
        return lambda text: anthropic_message_count(text, options.get("model"), options)
    if counter_type == "auto":
        def auto(text: str) -> dict[str, Any]:
            try:
                model = options.get("model")
                if model and model.startswith("claude") and (options.get("apiKey") or os.environ.get("ANTHROPIC_API_KEY")):
                    return anthropic_message_count(text, model, options)
                if model:
                    return openai_text_count(text, model, options)
            except Exception as error:
                estimate = heuristic_count(text)
                estimate["note"] = f"Exact counter unavailable: {error}"
                return estimate
            return heuristic_count(text)
        return auto
    raise ValueError(f"Unknown counter: {counter_type}")
