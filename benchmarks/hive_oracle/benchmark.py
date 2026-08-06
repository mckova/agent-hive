from __future__ import annotations

import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_hive.control import GoalController, HookBus
from agent_hive.memory import ScopedMemory
from agent_hive.planner import create_plan
from agent_hive.protocol import compile_payload
from benchmarks.hive_oracle.lib import aggregate_methods, aggregate_usage, answer_metrics, bm25_rank, enforce_answer_contract


def main(argv: list[str] | None = None) -> int:
    options = parse_arguments(sys.argv[1:] if argv is None else argv)
    api_key = os.environ.get("OPENAI_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENAI_KEY or OPENAI_API_KEY before running the live oracle.")
    rows = [row for row in fetch_hotpot_rows(options["poolSize"]) if row["id"] not in options["excludedIds"]]
    if options["includedIds"]:
        rows = [row for row in rows if row["id"] in options["includedIds"]]
    examples = choose_examples(rows, options["limit"], options["seed"])
    result = {"schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "oracle": {
        "question": "Does Agent Hive improve answer quality enough to justify its latency and token cost?",
        "dataset": "hotpotqa/hotpot_qa", "config": "distractor", "split": "validation", "examples": len(examples),
        "seed": options["seed"], "excludedIds": options["excludedIds"], "includedIds": options["includedIds"],
        "enabledMethods": options["methods"], "model": options["model"], "reasoningEffort": options["reasoningEffort"],
        "outputTokenBudgetPerSystem": options["outputBudget"], "rag": f"local BM25 top-{options['contextK']} + one model call",
        "hive": "scout -> forager -> builder -> guard", "adaptiveMemoryHive": "scoped evidence memory + controller + early stop + one repair",
        "loss": "taskLoss = 1 - HotpotQA token F1; exactLoss = 1 - exact match"}, "methods": {}, "examples": []}

    def call_model(name: str, instructions: str, input_text: str, max_output_tokens: int) -> dict[str, Any]:
        started = time.perf_counter()
        payload = fetch_json("https://api.openai.com/v1/responses", {"model": options["model"],
            "reasoning": {"effort": options["reasoningEffort"]}, "max_output_tokens": max_output_tokens,
            "instructions": instructions, "input": input_text, "store": False}, api_key)
        text = extract_output_text(payload)
        if not text:
            raise RuntimeError(f"{name} returned no output text ({(payload.get('incomplete_details') or {}).get('reason') or payload.get('status')}).")
        return {"name": name, "text": text, "latencyMs": (time.perf_counter() - started) * 1000,
                "usage": payload.get("usage"), "returnedModel": payload.get("model"), "status": payload.get("status")}

    for index, row in enumerate(examples):
        documents = documents_from_hotpot(row)
        runners: dict[str, Callable[[], dict[str, Any]]] = {
            "directGpt56": lambda q=row["question"]: run_direct(q, options, call_model),
            "ragGpt56": lambda q=row["question"], docs=documents: run_rag(q, docs, options, call_model),
            "agentHive": lambda q=row["question"], docs=documents: run_hive_system(q, docs, options, call_model),
            "adaptiveMemoryHive": lambda item=row, docs=documents: run_adaptive(item["id"], item["question"], docs, options, call_model),
        }
        unknown = [name for name in options["methods"] if name not in runners]
        if unknown:
            raise ValueError(f"Unknown benchmark methods: {', '.join(unknown)}")
        order = rotate(options["methods"], index); systems = {name: runners[name]() for name in order}
        for system in systems.values():
            system["quality"] = answer_metrics(system["answer"], row["answer"])
        result["examples"].append({"id": row["id"], "type": row["type"], "level": row["level"],
                                   "question": row["question"], "expected": row["answer"], "executionOrder": order, "systems": systems})
        result["methods"] = aggregate_methods(result["examples"])
        output = ROOT / options["output"]; output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Completed {index + 1}/{len(examples)}: {row['id']}")
    print(json.dumps({"output": str((ROOT / options['output']).resolve()), "methods": result["methods"]}, indent=2))
    return 0


def run_direct(question, options, call_model):
    started = time.perf_counter()
    call = call_model("direct-answer", short_answer_instruction("Answer from the model's own knowledge."), question, options["outputBudget"])
    return system_record(call["text"], [call], (time.perf_counter() - started) * 1000)


def run_rag(question, documents, options, call_model):
    started = time.perf_counter(); retrieval = time.perf_counter(); ranked = bm25_rank(question, documents)
    selected = [documents[index] for index in ranked[:options["contextK"]]]; retrieval_ms = (time.perf_counter() - retrieval) * 1000
    call = call_model("rag-answer", short_answer_instruction("Use only the supplied evidence. If insufficient, answer unknown."),
                      f"{question}\n\nRetrieved evidence:\n{render_documents(selected)}", options["outputBudget"])
    return {**system_record(call["text"], [call], (time.perf_counter() - started) * 1000),
            "retrieval": {"kind": "BM25", "latencyMs": retrieval_ms, "selectedTitles": [doc["title"] for doc in selected]}}


def run_hive_system(question, documents, options, call_model):
    started = time.perf_counter(); plan = hive_plan(question, options); outputs, calls = {}, []
    for identifier in [item for wave in plan["waves"] for item in wave]:
        cell = next(row for row in plan["cells"] if row["id"] == identifier)
        call = call_model(f"hive-{identifier}", role_instruction(cell["role"]),
                          hive_prompt(cell, question, documents, outputs, compile_payload(plan, cell, "openai")), cell["allocation"])
        calls.append({**call, "cell": identifier, "role": cell["role"], "allocation": cell["allocation"]}); outputs[identifier] = call["text"]
    return {**system_record(outputs["verify"], calls, (time.perf_counter() - started) * 1000),
            "plan": {"totalBudget": plan["budget"]["total"], "allocations": {cell["id"]: cell["allocation"] for cell in plan["cells"]},
                     "waves": plan["waves"]}, "cellOutputs": outputs}


def run_adaptive(identifier, question, documents, options, call_model):
    started = time.perf_counter(); namespace = f"mission:{identifier}"; memory_events = []; hooks = HookBus()
    memory = ScopedMemory(on_event=memory_events.append)
    controller = GoalController({"goal": f"Answer accurately: {question}",
        "success": {"confidenceMin": options["adaptiveConfidence"], "evidenceMin": 2},
        "budget": {"maxModelCalls": 2, "maxIterations": 2, "maxOutputTokens": options["outputBudget"],
                   "maxTotalTokens": options["adaptiveTotalTokenBudget"], "maxLatencyMs": options["adaptiveLatencyBudget"]}}, hooks=hooks)
    monitor = {"traceId": namespace, "inputValidated": False, "allowedTools": ["bm25_retrieve"], "toolCalls": 0,
               "policyDenials": 0, "repairTriggered": False, "earlyStopped": False}; calls = []
    validate_adaptive_input(question); monitor["inputValidated"] = True; hooks.emit("on_input_validated", {"chars": len(question), "scope": namespace})
    memory.write({"scope": "mission", "namespace": namespace, "kind": "queen",
                  "content": "Goal: answer accurately. Must use evidence. Final output: short answer span.",
                  "visibility": ["builder", "guard"], "ttlMs": 3600000})
    ranked = retrieve_with_policy(question, documents, monitor, hooks)
    write_evidence(memory, namespace, [documents[index] for index in ranked[:options["contextK"]]], ranked, documents)
    evidence = memory.query({"scope": "team", "namespace": namespace, "role": "builder", "limit": options["contextK"], "minimumScore": 0.25})
    queen = memory.query({"scope": "mission", "namespace": namespace, "role": "builder", "limit": 1})[0]
    hooks.emit("before_cell_run", {"cell": "builder", "evidenceCount": len(evidence)})
    builder = call_model("adaptive-builder", "Return JSON only: {\"answer\":\"short span\",\"confidence\":0.0,\"sources\":[\"exact title\"]}.",
                         f"{queen['content']}\n\nQuestion: {question}\n\nEvidence memory:\n{render_memory_evidence(evidence)}", options["outputBudget"])
    calls.append({**builder, "cell": "build", "role": "builder"}); controller.record_call(builder)
    draft = parse_adaptive_draft(builder["text"]); valid_sources = validate_sources(draft["sources"], evidence)
    memory.write({"scope": "agent", "namespace": namespace, "kind": "draft", "content": draft["answer"] or builder["text"],
                  "confidence": draft["confidence"], "visibility": ["builder"], "ttlMs": 1})
    decision = controller.evaluate({"answer": draft["answer"], "confidence": draft["confidence"],
                                    "evidenceCount": len(valid_sources), "conflict": False})
    answer = draft["answer"] or builder["text"]
    if decision["stop"]:
        monitor["earlyStopped"] = True; hooks.emit("on_goal_reached", {"reason": decision["reason"]})
        for row in evidence:
            if row["metadata"]["title"] in valid_sources: memory.reinforce(row["id"], verified=True, successful=True)
    else:
        monitor["repairTriggered"] = True; hooks.emit("on_low_confidence", {"confidence": draft["confidence"]})
        write_evidence(memory, namespace, [documents[index] for index in ranked[:options["adaptiveContextK"]]], ranked, documents)
        repair = memory.query({"scope": "team", "namespace": namespace, "role": "guard", "limit": options["adaptiveContextK"], "minimumScore": 0.25})
        remaining = max(1, options["outputBudget"] - (builder.get("usage") or {}).get("output_tokens", 0))
        guard = call_model("adaptive-guard", short_answer_instruction("Audit the draft against the complete evidence and repair it."),
                           f"Question: {question}\n\nEvidence:\n{render_memory_evidence(repair)}\n\nDraft: {draft['answer']}", remaining)
        calls.append({**guard, "cell": "verify", "role": "guard"}); controller.record_call(guard); answer = guard["text"]
        hooks.emit("on_loop_stopped", controller.evaluate({"answer": answer, "confidence": 0 if answer.lower() == "unknown" else 0.9,
                                                            "evidenceCount": len(repair), "conflict": False}))
    before = memory.snapshot(); deleted = sum(memory.delete_scope(scope, namespace, "mission_complete") for scope in ("agent", "team", "mission"))
    hooks.emit("on_session_end", {"deletions": deleted}); guarded = enforce_answer_contract(question, answer)
    if guarded != answer: hooks.emit("on_output_sanitized", {"rule": "binary_answer_span"})
    return {**system_record(guarded, calls, (time.perf_counter() - started) * 1000), "controller": controller.telemetry(),
            "monitoring": {**monitor, "hookEvents": len(hooks.trace()), "memoryEvents": len(memory_events),
                           "memoryRecordsBeforeCleanup": len(before), "memoryRecordsAfterCleanup": len(memory.snapshot()), "deletions": deleted}, "draft": draft}


def retrieve_with_policy(question, documents, monitor, hooks):
    if "bm25_retrieve" not in monitor["allowedTools"]:
        monitor["policyDenials"] += 1; raise RuntimeError("Adaptive Hive policy denied retrieval tool.")
    hooks.emit("before_tool_call", {"tool": "bm25_retrieve"}); ranked = bm25_rank(question, documents); monitor["toolCalls"] += 1
    hooks.emit("after_retrieval", {"tool": "bm25_retrieve", "candidates": len(ranked)}); return ranked


def write_evidence(memory, namespace, selected, ranked, all_documents):
    existing = {row.get("metadata", {}).get("title") for row in memory.snapshot(include_content=True)}
    for document in selected:
        if document["title"] in existing: continue
        rank = ranked.index(all_documents.index(document))
        memory.write({"scope": "team", "namespace": namespace, "kind": "evidence", "content": document["text"],
            "confidence": 1, "relevance": max(0.55, 1 - rank * 0.07), "sourceQuality": 1, "verifiedUtility": 0.95,
            "visibility": ["builder", "guard"], "ttlMs": 3600000, "metadata": {"title": document["title"], "rank": rank}})


def parse_adaptive_draft(text):
    try:
        value = json.loads(text[text.index("{"):text.rindex("}") + 1]); confidence = max(0, min(1, float(value.get("confidence", 0))))
        return {"answer": value.get("answer", "").strip() if isinstance(value.get("answer"), str) else "", "confidence": confidence,
                "sources": [item for item in value.get("sources", []) if isinstance(item, str)], "parseSucceeded": True, "raw": text}
    except (ValueError, json.JSONDecodeError):
        return {"answer": text.strip(), "confidence": 0, "sources": [], "parseSucceeded": False, "raw": text}


def validate_sources(sources, evidence):
    available = {row["metadata"]["title"].lower(): row["metadata"]["title"] for row in evidence}
    return list(dict.fromkeys(available[source.strip().lower()] for source in sources if source.strip().lower() in available))


def validate_adaptive_input(question):
    if not isinstance(question, str) or not question.strip(): raise ValueError("Adaptive Hive input guard rejected an empty question.")
    if len(question) > 5000: raise ValueError("Adaptive Hive input guard rejected an oversized question.")


def hive_plan(question, options):
    def cell(identifier, title, role, priority, complexity, risk, dependencies):
        return {"id": identifier, "title": title, "role": role, "priority": priority, "complexity": complexity,
                "risk": risk, "dependencies": dependencies, "required": True}
    mission = {"schemaVersion": 1, "mission": {"goal": f"Answer this multi-hop question accurately: {question}",
        "sourceLanguage": "English", "responseLanguage": "English", "must": ["Use the supplied corpus", "Return a short answer span"],
        "avoid": ["Inventing unsupported facts", "Explanations in the final answer"], "doneWhen": ["The guard returns only the corrected final answer"]},
        "budget": {"unit": "tokens", "total": options["outputBudget"], "reservePercent": 0},
        "policy": {"maxWorkers": 1, "qualityFloor": "frontier"}, "models": {tier: {"openai": options["model"]} for tier in ("economy", "balanced", "frontier")},
        "cells": [cell("survey", "Identify the two-hop evidence needed", "scout", 2, 2, 2, []),
                  cell("forage", "Extract the minimum supported evidence chain", "forager", 5, 4, 4, ["survey"]),
                  cell("build", "Produce a short answer from the evidence", "builder", 5, 3, 3, ["forage"]),
                  cell("verify", "Audit and return the corrected final answer", "guard", 5, 4, 5, ["build"])]}
    return create_plan(mission, datetime.fromtimestamp(0, timezone.utc))


def hive_prompt(cell, question, documents, outputs, payload):
    parts = [f"Question: {question}"]
    if cell["id"] == "survey": parts.append("Available titles: " + " | ".join(doc["title"] for doc in documents))
    if cell["id"] == "forage": parts.extend([f"Scout map:\n{outputs['survey']}", f"Corpus:\n{render_documents(documents)}"])
    if cell["id"] == "build": parts.append(f"Forager evidence:\n{outputs['forage']}")
    if cell["id"] == "verify": parts.extend([f"Forager evidence:\n{outputs['forage']}", f"Builder draft:\n{outputs['build']}"])
    return payload + "\n" + "\n\n".join(parts)


def role_instruction(role):
    return {"scout": "Map the minimum evidence needed. Be compact and do not answer.",
            "forager": "Return a compact evidence chain with exact titles. Use no outside knowledge.",
            "builder": "Use only forager evidence. Return only the short answer span.",
            "guard": "Check the draft, correct it if needed, and return only the final answer."}[role]


def system_record(answer, calls, latency): return {"answer": answer, "endToEndLatencyMs": latency, "usage": aggregate_usage(calls), "calls": calls}
def short_answer_instruction(prefix): return prefix + " Return only the answer span, usually 1-8 words. No explanation or labels."
def render_documents(documents): return "\n\n".join(f"[{index + 1}] {doc['title']}\n{doc['text']}" for index, doc in enumerate(documents))
def render_memory_evidence(rows): return "\n\n".join(f"[{index + 1}] {row['metadata']['title']}\n{row['content']}" for index, row in enumerate(rows))


def extract_output_text(payload):
    return "".join(content.get("text", "") for item in payload.get("output", []) for content in item.get("content", [])
                   if content.get("type") == "output_text").strip()


def fetch_hotpot_rows(length):
    query = urllib.parse.urlencode({"dataset": "hotpotqa/hotpot_qa", "config": "distractor", "split": "validation", "offset": 0, "length": min(100, length)})
    return [entry["row"] for entry in fetch_json("https://datasets-server.huggingface.co/rows?" + query, None).get("rows", [])]


def fetch_json(url, payload=None, api_key=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if api_key: headers["Authorization"] = f"Bearer {api_key}"
    last_error = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace"); last_error = RuntimeError(f"HTTP {error.code}: {detail}")
            if error.code != 429 and error.code < 500: raise last_error
        except Exception as error: last_error = error
        time.sleep(0.7 * (2 ** attempt))
    raise last_error or RuntimeError("request failed")


def choose_examples(rows, limit, seed):
    shuffled = list(rows); random.Random(seed).shuffle(shuffled); chosen = []
    for kind in ("bridge", "comparison"):
        for row in (item for item in shuffled if item["type"] == kind):
            if len(chosen) >= limit or sum(item["type"] == kind for item in chosen) >= math.ceil(limit / 2): break
            chosen.append(row)
    for row in shuffled:
        if len(chosen) >= limit: break
        if all(item["id"] != row["id"] for item in chosen): chosen.append(row)
    return chosen[:limit]


def documents_from_hotpot(row):
    titles, sentences = (row.get("context") or {}).get("title", []), (row.get("context") or {}).get("sentences", [])
    return [{"title": title, "sentences": sentences[index] if index < len(sentences) else [],
             "text": f"{title}. {' '.join(sentences[index] if index < len(sentences) else [])}"} for index, title in enumerate(titles)]


def rotate(values, offset):
    amount = offset % len(values); return values[amount:] + values[:amount]


def parse_arguments(args):
    values = {}
    for argument in args:
        key, _, value = argument.removeprefix("--").partition("="); values[key] = value or "true"
    integer = lambda name, default: int(values[name]) if values.get(name, "").isdigit() and int(values[name]) > 0 else default
    def decimal(name, default):
        try: value = float(values[name]); return value if 0 <= value <= 1 else default
        except (KeyError, ValueError): return default
    split = lambda name: [item.strip() for item in values.get(name, "").split(",") if item.strip()]
    return {"limit": integer("limit", 6), "poolSize": integer("pool", 80), "seed": integer("seed", 7419),
        "contextK": integer("context-k", 3), "adaptiveContextK": integer("adaptive-context-k", 10),
        "adaptiveTotalTokenBudget": integer("adaptive-total-token-budget", 2000), "adaptiveLatencyBudget": integer("adaptive-latency-budget", 15000),
        "adaptiveConfidence": decimal("adaptive-confidence", 0.9), "excludedIds": split("exclude"), "includedIds": split("include"),
        "methods": split("methods") or ["directGpt56", "ragGpt56", "agentHive", "adaptiveMemoryHive"],
        "outputBudget": integer("output-budget", 416), "model": values.get("model", "gpt-5.6-sol"),
        "reasoningEffort": values.get("reasoning", "none"), "output": values.get("output", "benchmarks/hive-oracle/results/latest.json")}


if __name__ == "__main__":
    raise SystemExit(main())
