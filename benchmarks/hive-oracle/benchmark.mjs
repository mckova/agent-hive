import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { GoalController, HookBus } from "../../src/core/control.mjs";
import { ScopedMemory } from "../../src/core/memory.mjs";
import { createPlan } from "../../src/core/planner.mjs";
import { compilePayload } from "../../src/core/protocol.mjs";
import { aggregateMethods, aggregateUsage, answerMetrics, bm25Rank, enforceAnswerContract } from "./lib.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const options = parseArguments(process.argv.slice(2));
const apiKey = process.env.OPENAI_KEY || process.env.OPENAI_API_KEY;
if (!apiKey) throw new Error("Set OPENAI_KEY or OPENAI_API_KEY before running the live oracle.");

const rows = (await fetchHotpotRows(options.poolSize))
  .filter((row) => !options.excludedIds.includes(row.id))
  .filter((row) => !options.includedIds.length || options.includedIds.includes(row.id));
const examples = chooseExamples(rows, options.limit, options.seed);
const result = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  oracle: {
    question: "Does Agent Hive improve answer quality enough to justify its latency and token cost?",
    dataset: "hotpotqa/hotpot_qa",
    config: "distractor",
    split: "validation",
    examples: examples.length,
    seed: options.seed,
    excludedIds: options.excludedIds,
    includedIds: options.includedIds,
    enabledMethods: options.methods,
    model: options.model,
    reasoningEffort: options.reasoningEffort,
    outputTokenBudgetPerSystem: options.outputBudget,
    rag: `local BM25 top-${options.contextK} + one ${options.model} call`,
    hive: `scout -> forager -> builder -> guard; every cell uses ${options.model}`,
    adaptiveMemoryHive: `scoped evidence memory + goal controller + hooks + early stop + at most one guard repair; every model call uses ${options.model}`,
    loss: "taskLoss = 1 - HotpotQA token F1; exactLoss = 1 - exact match"
  },
  methods: {},
  examples: []
};

for (let index = 0; index < examples.length; index += 1) {
  const row = examples[index];
  const documents = documentsFromHotpot(row);
  const availableRunners = {
    directGpt56: () => runDirect(row.question),
    ragGpt56: () => runRag(row.question, documents),
    agentHive: () => runHive(row.question, documents),
    adaptiveMemoryHive: () => runAdaptiveMemoryHive(row.id, row.question, documents)
  };
  const unknownMethods = options.methods.filter((name) => !availableRunners[name]);
  if (unknownMethods.length) throw new Error(`Unknown benchmark methods: ${unknownMethods.join(", ")}`);
  const runners = Object.fromEntries(options.methods.map((name) => [name, availableRunners[name]]));
  const methodOrder = rotate(Object.keys(runners), index);
  const systems = {};
  for (const name of methodOrder) systems[name] = await runners[name]();
  for (const system of Object.values(systems)) system.quality = answerMetrics(system.answer, row.answer);

  result.examples.push({
    id: row.id,
    type: row.type,
    level: row.level,
    question: row.question,
    expected: row.answer,
    executionOrder: methodOrder,
    systems
  });
  result.methods = aggregateMethods(result.examples);
  await persist();
  process.stdout.write(`Completed ${index + 1}/${examples.length}: ${row.id}\n`);
}

console.log(JSON.stringify({ output: path.resolve(root, options.output), methods: result.methods }, null, 2));

async function runDirect(question) {
  const startedAt = performance.now();
  const call = await callModel({
    name: "direct-answer",
    instructions: shortAnswerInstruction("Answer from the model's own knowledge."),
    input: question,
    maxOutputTokens: options.outputBudget
  });
  return systemRecord(call.text, [call], performance.now() - startedAt);
}

async function runRag(question, documents) {
  const startedAt = performance.now();
  const retrievalStartedAt = performance.now();
  const ranked = bm25Rank(question, documents);
  const selected = ranked.slice(0, options.contextK).map((documentIndex) => documents[documentIndex]);
  const retrievalLatencyMs = performance.now() - retrievalStartedAt;
  const call = await callModel({
    name: "rag-answer",
    instructions: shortAnswerInstruction("Use only the supplied retrieved evidence. If it is insufficient, answer unknown."),
    input: `${question}\n\nRetrieved evidence:\n${renderDocuments(selected)}`,
    maxOutputTokens: options.outputBudget
  });
  return {
    ...systemRecord(call.text, [call], performance.now() - startedAt),
    retrieval: { kind: "BM25", latencyMs: retrievalLatencyMs, selectedTitles: selected.map((document) => document.title) }
  };
}

async function runHive(question, documents) {
  const startedAt = performance.now();
  const plan = hivePlan(question);
  const outputs = {};
  const calls = [];
  for (const cellId of plan.waves.flat()) {
    const cell = plan.cells.find((candidate) => candidate.id === cellId);
    const payload = compilePayload(plan, cell, { target: "openai" });
    const prompt = hivePrompt(cell, question, documents, outputs, payload);
    const call = await callModel({
      name: `hive-${cell.id}`,
      instructions: roleInstruction(cell.role),
      input: prompt,
      maxOutputTokens: cell.allocation
    });
    calls.push({ ...call, cell: cell.id, role: cell.role, allocation: cell.allocation });
    outputs[cell.id] = call.text;
  }
  return {
    ...systemRecord(outputs.verify, calls, performance.now() - startedAt),
    plan: {
      totalBudget: plan.budget.total,
      allocations: Object.fromEntries(plan.cells.map((cell) => [cell.id, cell.allocation])),
      waves: plan.waves
    },
    cellOutputs: outputs
  };
}

async function runAdaptiveMemoryHive(id, question, documents) {
  const startedAt = performance.now();
  const namespace = `mission:${id}`;
  const memoryEvents = [];
  const hooks = new HookBus();
  const memory = new ScopedMemory({ onEvent: (event) => memoryEvents.push(event) });
  const controller = new GoalController({
    goal: `Answer the multi-hop question accurately: ${question}`,
    success: { confidenceMin: options.adaptiveConfidence, evidenceMin: 2 },
    budget: {
      maxModelCalls: 2,
      maxIterations: 2,
      maxOutputTokens: options.outputBudget,
      maxTotalTokens: options.adaptiveTotalTokenBudget,
      maxLatencyMs: options.adaptiveLatencyBudget
    }
  }, { hooks });
  const calls = [];
  const monitor = {
    traceId: namespace,
    inputValidated: false,
    allowedTools: ["bm25_retrieve"],
    toolCalls: 0,
    policyDenials: 0,
    repairTriggered: false,
    earlyStopped: false
  };

  validateAdaptiveInput(question);
  monitor.inputValidated = true;
  await hooks.emit("on_input_validated", { chars: question.length, scope: namespace });
  memory.write({
    scope: "mission",
    namespace,
    kind: "queen",
    content: `Goal: answer accurately. Must use evidence. Final output: short answer span.`,
    visibility: ["builder", "guard"],
    ttlMs: 60 * 60 * 1000
  });

  const ranked = await retrieveWithPolicy(question, documents, monitor, hooks);
  const initialDocuments = ranked.slice(0, options.contextK).map((documentIndex) => documents[documentIndex]);
  writeEvidence(memory, namespace, initialDocuments, ranked, documents);
  const initialEvidence = readEvidence(memory, namespace, "builder", options.contextK);
  const queen = memory.query({ scope: "mission", namespace, role: "builder", limit: 1 })[0];
  await hooks.emit("before_cell_run", { cell: "builder", evidenceCount: initialEvidence.length });
  const builderCall = await callModel({
    name: "adaptive-builder",
    instructions: "You are the Adaptive Hive Builder. Use only supplied evidence. Return valid JSON only with this exact shape: {\"answer\":\"short answer span\",\"confidence\":0.0,\"sources\":[\"exact document title\"]}. Confidence must reflect whether the evidence supports the full multi-hop chain. Use exact supplied titles. No markdown.",
    input: `${queen.content}\n\nQuestion: ${question}\n\nEvidence memory:\n${renderMemoryEvidence(initialEvidence)}`,
    maxOutputTokens: options.outputBudget
  });
  calls.push({ ...builderCall, cell: "build", role: "builder" });
  await controller.recordCall(builderCall);
  const draft = parseAdaptiveDraft(builderCall.text);
  const validSources = validateSources(draft.sources, initialEvidence);
  memory.write({
    scope: "agent",
    namespace,
    kind: "draft",
    content: draft.answer || builderCall.text,
    confidence: draft.confidence,
    visibility: ["builder"],
    ttlMs: 1
  });

  const decision = controller.evaluate({
    answer: draft.answer,
    confidence: draft.confidence,
    evidenceCount: validSources.length,
    conflict: false
  });
  let answer = draft.answer || builderCall.text;

  if (decision.stop) {
    monitor.earlyStopped = true;
    await hooks.emit("on_goal_reached", { reason: decision.reason, confidence: draft.confidence, evidenceCount: validSources.length });
    for (const row of initialEvidence.filter((candidate) => validSources.includes(candidate.metadata.title))) {
      memory.reinforce(row.id, { verified: true, successful: true });
    }
  } else {
    monitor.repairTriggered = true;
    await hooks.emit("on_low_confidence", { confidence: draft.confidence, evidenceCount: validSources.length });
    const expandedDocuments = ranked.slice(0, options.adaptiveContextK).map((documentIndex) => documents[documentIndex]);
    writeEvidence(memory, namespace, expandedDocuments, ranked, documents);
    const repairEvidence = readEvidence(memory, namespace, "guard", options.adaptiveContextK);
    const remainingOutputTokens = Math.max(1, options.outputBudget - (builderCall.usage?.output_tokens || 0));
    await hooks.emit("before_cell_run", { cell: "guard", evidenceCount: repairEvidence.length });
    const guardCall = await callModel({
      name: "adaptive-guard",
      instructions: shortAnswerInstruction("You are the Adaptive Hive Guard. Audit the draft against the complete supplied evidence, repair it when needed, and use no outside knowledge."),
      input: `Question: ${question}\n\nEvidence memory:\n${renderMemoryEvidence(repairEvidence)}\n\nBuilder draft: ${draft.answer}\nBuilder confidence: ${draft.confidence}\nBuilder sources: ${validSources.join(" | ") || "none"}`,
      maxOutputTokens: remainingOutputTokens
    });
    calls.push({ ...guardCall, cell: "verify", role: "guard" });
    await controller.recordCall(guardCall);
    answer = guardCall.text;
    const finalDecision = controller.evaluate({
      answer,
      confidence: answer.toLowerCase() === "unknown" ? 0 : 0.9,
      evidenceCount: repairEvidence.length,
      conflict: false
    });
    await hooks.emit("on_loop_stopped", { reason: finalDecision.reason });
  }

  const memoryBeforeCleanup = memory.snapshot();
  const agentDeleted = memory.deleteScope({ scope: "agent", namespace, reason: "cell_complete" });
  const teamDeleted = memory.deleteScope({ scope: "team", namespace, reason: "mission_complete" });
  const missionDeleted = memory.deleteScope({ scope: "mission", namespace, reason: "mission_complete" });
  await hooks.emit("on_session_end", { agentDeleted, teamDeleted, missionDeleted });

  const guardedAnswer = enforceAnswerContract(question, answer);
  if (guardedAnswer !== answer) await hooks.emit("on_output_sanitized", { rule: "binary_answer_span" });

  return {
    ...systemRecord(guardedAnswer, calls, performance.now() - startedAt),
    controller: controller.telemetry(),
    monitoring: {
      ...monitor,
      hookEvents: hooks.trace().length,
      memoryEvents: memoryEvents.length,
      memoryRecordsBeforeCleanup: memoryBeforeCleanup.length,
      memoryRecordsAfterCleanup: memory.snapshot().length,
      deletions: agentDeleted + teamDeleted + missionDeleted
    },
    draft
  };
}

async function retrieveWithPolicy(question, documents, monitor, hooks) {
  if (!monitor.allowedTools.includes("bm25_retrieve")) {
    monitor.policyDenials += 1;
    throw new Error("Adaptive Hive policy denied retrieval tool.");
  }
  await hooks.emit("before_tool_call", { tool: "bm25_retrieve" });
  const ranked = bm25Rank(question, documents);
  monitor.toolCalls += 1;
  await hooks.emit("after_retrieval", { tool: "bm25_retrieve", candidates: ranked.length });
  return ranked;
}

function writeEvidence(memory, namespace, selected, ranked, allDocuments) {
  const existingTitles = new Set(memory.snapshot({ includeContent: true }).map((row) => row.metadata?.title).filter(Boolean));
  for (const document of selected) {
    if (existingTitles.has(document.title)) continue;
    const rank = ranked.indexOf(allDocuments.indexOf(document));
    memory.write({
      scope: "team",
      namespace,
      kind: "evidence",
      content: document.text,
      confidence: 1,
      relevance: Math.max(0.55, 1 - rank * 0.07),
      sourceQuality: 1,
      verifiedUtility: 0.95,
      visibility: ["builder", "guard"],
      ttlMs: 60 * 60 * 1000,
      metadata: { title: document.title, rank }
    });
  }
}

function readEvidence(memory, namespace, role, limit) {
  return memory.query({ scope: "team", namespace, role, limit, minimumScore: 0.25 });
}

function renderMemoryEvidence(rows) {
  return rows.map((row, index) => `[${index + 1}] ${row.metadata.title}\n${row.content}`).join("\n\n");
}

function parseAdaptiveDraft(text) {
  try {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start < 0 || end <= start) throw new Error("no JSON object");
    const value = JSON.parse(text.slice(start, end + 1));
    return {
      answer: typeof value.answer === "string" ? value.answer.trim() : "",
      confidence: Math.max(0, Math.min(1, Number(value.confidence) || 0)),
      sources: Array.isArray(value.sources) ? value.sources.filter((item) => typeof item === "string") : [],
      parseSucceeded: true,
      raw: text
    };
  } catch {
    return { answer: text.trim(), confidence: 0, sources: [], parseSucceeded: false, raw: text };
  }
}

function validateSources(sources, evidence) {
  const available = new Map(evidence.map((row) => [row.metadata.title.toLowerCase(), row.metadata.title]));
  return [...new Set(sources.map((source) => available.get(source.trim().toLowerCase())).filter(Boolean))];
}

function validateAdaptiveInput(question) {
  if (typeof question !== "string" || !question.trim()) throw new Error("Adaptive Hive input guard rejected an empty question.");
  if (question.length > 5000) throw new Error("Adaptive Hive input guard rejected an oversized question.");
}

function hivePlan(question) {
  return createPlan({
    schemaVersion: 1,
    mission: {
      goal: `Answer this multi-hop question accurately: ${question}`,
      sourceLanguage: "English",
      responseLanguage: "English",
      must: ["Use the supplied corpus", "Return a short answer span"],
      avoid: ["Inventing unsupported facts", "Explanations in the final answer"],
      doneWhen: ["The guard returns only the corrected final answer"]
    },
    budget: { unit: "tokens", total: options.outputBudget, reservePercent: 0 },
    policy: { maxWorkers: 1, qualityFloor: "frontier" },
    models: {
      economy: { openai: options.model },
      balanced: { openai: options.model },
      frontier: { openai: options.model }
    },
    cells: [
      cell("survey", "Identify the two-hop evidence needed", "scout", 2, 2, 2, []),
      cell("forage", "Extract the minimum supported evidence chain", "forager", 5, 4, 4, ["survey"]),
      cell("build", "Produce a short answer from the evidence", "builder", 5, 3, 3, ["forage"]),
      cell("verify", "Audit and return the corrected final answer", "guard", 5, 4, 5, ["build"])
    ]
  }, new Date(0));
}

function hivePrompt(cell, question, documents, outputs, payload) {
  const shared = [`Question: ${question}`];
  if (cell.id === "survey") {
    shared.push(`Available document titles: ${documents.map((document) => document.title).join(" | ")}`);
  }
  if (cell.id === "forage") {
    shared.push(`Scout map:\n${outputs.survey}`, `Corpus:\n${renderDocuments(documents)}`);
  }
  if (cell.id === "build") shared.push(`Forager evidence:\n${outputs.forage}`);
  if (cell.id === "verify") shared.push(`Forager evidence:\n${outputs.forage}`, `Builder draft:\n${outputs.build}`);
  return `${payload}\n${shared.join("\n\n")}`;
}

function roleInstruction(role) {
  const instructions = {
    scout: "You are the Hive Scout. Map the minimum evidence needed. Be compact and do not answer the question.",
    forager: "You are the Hive Forager. Read the corpus, follow the scout map, and return only a compact evidence chain with exact document titles. Do not rely on outside knowledge.",
    builder: "You are the Hive Builder. Use only the forager evidence. Return only the short answer span, usually 1-8 words. No explanation.",
    guard: "You are the Hive Guard. Check the draft against the evidence, correct it if needed, and return only the final short answer span. No explanation or labels."
  };
  return instructions[role];
}

function cell(id, title, role, priority, complexity, risk, dependencies) {
  return { id, title, role, priority, complexity, risk, dependencies, required: true };
}

function systemRecord(answer, calls, endToEndLatencyMs) {
  return { answer, endToEndLatencyMs, usage: aggregateUsage(calls), calls };
}

function shortAnswerInstruction(prefix) {
  return `${prefix} Return only the answer span, usually 1-8 words. Do not explain, hedge, repeat the question, or add labels.`;
}

async function callModel({ name, instructions, input, maxOutputTokens }) {
  const startedAt = performance.now();
  const payload = await fetchJson("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: options.model,
      reasoning: { effort: options.reasoningEffort },
      max_output_tokens: maxOutputTokens,
      instructions,
      input,
      store: false
    })
  });
  const text = extractOutputText(payload);
  if (!text) throw new Error(`${name} returned no output text (${payload.incomplete_details?.reason || payload.status}).`);
  return {
    name,
    text,
    latencyMs: performance.now() - startedAt,
    usage: payload.usage,
    returnedModel: payload.model,
    status: payload.status
  };
}

function extractOutputText(payload) {
  return (payload.output || [])
    .flatMap((item) => item.content || [])
    .filter((item) => item.type === "output_text")
    .map((item) => item.text)
    .join("")
    .trim();
}

async function fetchHotpotRows(length) {
  const url = new URL("https://datasets-server.huggingface.co/rows");
  url.searchParams.set("dataset", "hotpotqa/hotpot_qa");
  url.searchParams.set("config", "distractor");
  url.searchParams.set("split", "validation");
  url.searchParams.set("offset", "0");
  url.searchParams.set("length", String(Math.min(100, length)));
  const payload = await fetchJson(url, {});
  return (payload.rows || []).map((entry) => entry.row);
}

function chooseExamples(rows, limit, seed) {
  const rng = createRng(seed);
  const shuffled = rows.map((row) => ({ row, key: rng() })).sort((left, right) => left.key - right.key);
  const chosen = [];
  for (const type of ["bridge", "comparison"]) {
    for (const candidate of shuffled.filter((item) => item.row.type === type)) {
      if (chosen.length >= limit || chosen.filter((row) => row.type === type).length >= Math.ceil(limit / 2)) break;
      chosen.push(candidate.row);
    }
  }
  for (const candidate of shuffled) {
    if (chosen.length >= limit) break;
    if (!chosen.some((row) => row.id === candidate.row.id)) chosen.push(candidate.row);
  }
  return chosen.slice(0, limit);
}

function documentsFromHotpot(row) {
  const titles = row.context?.title || [];
  const sentences = row.context?.sentences || [];
  return titles.map((title, index) => ({
    title,
    sentences: sentences[index] || [],
    text: `${title}. ${(sentences[index] || []).join(" ")}`
  }));
}

function renderDocuments(documents) {
  return documents.map((document, index) => `[${index + 1}] ${document.title}\n${document.text}`).join("\n\n");
}

async function fetchJson(url, init) {
  let lastError;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const response = await fetch(url, init);
      const payload = await response.json();
      if (response.ok) return payload;
      const message = payload.error?.message || `HTTP ${response.status}`;
      if (response.status !== 429 && response.status < 500) throw new Error(message);
      lastError = new Error(message);
    } catch (error) {
      lastError = error;
      if (attempt === 3) break;
    }
    await new Promise((resolve) => setTimeout(resolve, 700 * 2 ** attempt));
  }
  throw lastError;
}

async function persist() {
  const outputPath = path.resolve(root, options.output);
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
}

function rotate(values, offset) {
  const amount = offset % values.length;
  return [...values.slice(amount), ...values.slice(0, amount)];
}

function parseArguments(args) {
  const values = Object.fromEntries(args.map((argument) => {
    const [key, value = "true"] = argument.replace(/^--/, "").split("=");
    return [key, value];
  }));
  return {
    limit: integer(values.limit, 6),
    poolSize: integer(values.pool, 80),
    seed: integer(values.seed, 7419),
    contextK: integer(values["context-k"], 3),
    adaptiveContextK: integer(values["adaptive-context-k"], 10),
    adaptiveTotalTokenBudget: integer(values["adaptive-total-token-budget"], 2000),
    adaptiveLatencyBudget: integer(values["adaptive-latency-budget"], 15000),
    adaptiveConfidence: decimal(values["adaptive-confidence"], 0.9),
    excludedIds: String(values.exclude || "").split(",").map((value) => value.trim()).filter(Boolean),
    includedIds: String(values.include || "").split(",").map((value) => value.trim()).filter(Boolean),
    methods: String(values.methods || "directGpt56,ragGpt56,agentHive,adaptiveMemoryHive").split(",").map((value) => value.trim()).filter(Boolean),
    outputBudget: integer(values["output-budget"], 416),
    model: values.model || "gpt-5.6-sol",
    reasoningEffort: values.reasoning || "none",
    output: values.output || "benchmarks/hive-oracle/results/latest.json"
  };
}

function integer(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function decimal(value, fallback) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : fallback;
}

function createRng(seed) {
  let state = seed >>> 0;
  return () => {
    state |= 0;
    state = state + 0x6D2B79F5 | 0;
    let value = Math.imul(state ^ state >>> 15, 1 | state);
    value = value + Math.imul(value ^ value >>> 7, 61 | value) ^ value;
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}
