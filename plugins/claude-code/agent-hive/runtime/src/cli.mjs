import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { defaultMission, validateMission } from "./core/mission.mjs";
import { createPlan, explainCell } from "./core/planner.mjs";
import { compileAllPayloads } from "./core/protocol.mjs";
import { compareMissionVariants } from "./core/prompt-compiler.mjs";
import { createTokenCounter } from "./core/token-counter.mjs";
import { nextReadyCells, rebalancePlan, recordCellUsage, summarizeUsage } from "./core/usage.mjs";
import { appendAudit } from "./core/audit.mjs";
import { evaluateGate } from "./core/gate.mjs";
import { ScopedMemory } from "./core/memory.mjs";
import { runHive } from "./core/runner.mjs";
import { createClaudeDriver, createCodexDriver, createMockDriver } from "./drivers/cli-drivers.mjs";

export async function runCli(argv, io = console) {
  const [command = "help", ...args] = argv;
  switch (command) {
    case "init": return initCommand(args, io);
    case "plan": return planCommand(args, io);
    case "compile": return compileCommand(args, io);
    case "compare": return compareCommand(args, io);
    case "next": return nextCommand(args, io);
    case "record": return recordCommand(args, io);
    case "status": return statusCommand(args, io);
    case "rebalance": return rebalanceCommand(args, io);
    case "explain": return explainCommand(args, io);
    case "gate": return gateCommand(args, io);
    case "memory": return memoryCommand(args, io);
    case "run": return runCommand(args, io);
    case "validate": return validateCommand(args, io);
    case "help":
    case "--help":
    case "-h": io.log(helpText()); return;
    default: throw new Error(`Unknown command: ${command}\n\n${helpText()}`);
  }
}

async function initCommand(args, io) {
  const directory = path.resolve(args[0] || ".hive");
  await mkdir(directory, { recursive: true });
  const missionPath = path.join(directory, "mission.json");
  await writeJson(missionPath, defaultMission());
  io.log(`Created ${missionPath}`);
}

async function planCommand(args, io) {
  const missionPath = path.resolve(option(args, "--mission") || args[0] || ".hive/mission.json");
  const outPath = path.resolve(option(args, "--out") || ".hive/plan.json");
  const mission = await readJson(missionPath);
  const errors = validateMission(mission);
  if (errors.length) throw new Error(errors.join("\n"));
  const plan = createPlan(mission);
  await writeJson(outPath, plan);
  await appendAudit(auditPath(args, outPath), { event: "plan.created", planPath: outPath, cells: plan.cells.length, budget: plan.budget });
  io.log(`Planned ${plan.cells.length} cells in ${plan.waves.length} waves.`);
  io.log(`Allocated ${plan.budget.allocated} ${plan.budget.unit}; reserve ${plan.budget.reserve}.`);
  io.log(`Wrote ${outPath}`);
}

async function compileCommand(args, io) {
  const planPath = path.resolve(option(args, "--plan") || args[0] || ".hive/plan.json");
  const outDir = path.resolve(option(args, "--out-dir") || ".hive/payloads");
  const plan = await readJson(planPath);
  await mkdir(outDir, { recursive: true });
  const target = option(args, "--target") || "generic";
  if (!["generic", "codex", "claude"].includes(target)) {
    throw new Error("--target must be generic, codex, or claude.");
  }
  const payloads = compileAllPayloads(plan, { target });
  for (const [name, contents] of payloads) {
    await writeFile(path.join(outDir, name), contents, "utf8");
  }
  io.log(`Compiled ${payloads.size} HIVE/1 payloads for ${target} to ${outDir}`);
}

async function compareCommand(args, io) {
  const missionPath = path.resolve(option(args, "--mission") || positional(args)[0] || ".hive/mission.json");
  const raw = await readJson(missionPath);
  const mission = raw.mission?.goal ? raw.mission : raw;
  const counter = createTokenCounter({
    type: option(args, "--counter") || "heuristic",
    model: option(args, "--model")
  });
  const rows = await compareMissionVariants(mission, counter);
  io.table(rows.map(({ name, tokens, precision, counter: counterName, chars, bytes, literalsPreserved, note }) => ({
    variant: name, tokens, precision, counter: counterName, chars, bytes, preserved: literalsPreserved, note
  })));
  const best = rows.find((row) => row.literalsPreserved);
  const outPath = option(args, "--write-best");
  if (outPath && best) {
    const absolute = path.resolve(outPath);
    await mkdir(path.dirname(absolute), { recursive: true });
    await writeFile(absolute, `${best.text}\n`, "utf8");
    io.log(`Wrote lowest-count lossless variant (${best.name}) to ${absolute}`);
  }
  io.log("Precision is reported per row; heuristic counts are planning estimates, not provider tokenizer results.");
}

async function nextCommand(args, io) {
  const plan = await readJson(path.resolve(option(args, "--plan") || positional(args)[0] || ".hive/plan.json"));
  const usage = await readJsonIfPresent(path.resolve(option(args, "--usage") || ".hive/usage.json"), { cells: {} });
  const ready = nextReadyCells(plan, usage);
  if (!ready.length) {
    const summary = summarizeUsage(plan, usage);
    const spendable = summary.total - summary.effectiveReserve;
    io.log(summary.used >= spendable
      ? `Budget gate closed: used ${summary.used}/${spendable} spendable ${plan.budget.unit}.`
      : "No pending cell has all dependencies completed.");
    return;
  }
  io.table(ready.map((cell) => ({
    id: cell.id,
    role: cell.role,
    tier: cell.modelTier,
    allocation: cell.allocation,
    dependencies: cell.dependencies.join(",") || "none"
  })));
}

async function recordCommand(args, io) {
  const id = positional(args)[0];
  if (!id) throw new Error("record requires a cell id.");
  const status = option(args, "--status");
  if (!status) throw new Error("record requires --status.");
  const used = Number(option(args, "--used"));
  if (!Number.isInteger(used) || used < 0) throw new Error("record requires --used as a non-negative integer.");
  const plan = await readJson(path.resolve(option(args, "--plan") || ".hive/plan.json"));
  const usagePath = path.resolve(option(args, "--usage") || ".hive/usage.json");
  const usage = await readJsonIfPresent(usagePath, { cells: {} });
  const updated = recordCellUsage(plan, usage, {
    id,
    status,
    used,
    artifacts: options(args, "--artifact"),
    evidence: options(args, "--evidence"),
    blockers: options(args, "--blocker"),
    reusableContext: options(args, "--context"),
    attempts: optionalInteger(args, "--attempts"),
    metrics: metricsOptions(args)
  });
  await writeJson(usagePath, updated);
  const stored = updated.cells[id];
  await appendAudit(auditPath(args, usagePath), {
    event: "cell.recorded", cell: id, status: stored.status, used: stored.used,
    attempts: stored.attempts, metrics: stored.metrics,
    artifactCount: stored.artifacts.length, evidenceCount: stored.evidence.length, blockerCount: stored.blockers.length
  });
  io.log(`Recorded ${id}: ${status}, ${used} ${plan.budget.unit} used.`);
  io.log(`Wrote ${usagePath}`);
}

async function statusCommand(args, io) {
  const plan = await readJson(path.resolve(option(args, "--plan") || args[0] || ".hive/plan.json"));
  const usagePath = path.resolve(option(args, "--usage") || ".hive/usage.json");
  const usage = await readJsonIfPresent(usagePath, { cells: {} });
  const summary = summarizeUsage(plan, usage);
  io.table(summary.rows);
  io.log(`Used ${summary.used}/${summary.total} ${plan.budget.unit}; protected reserve ${summary.effectiveReserve}.`);
  io.log(`Calls ${summary.metrics.modelCalls}; input ${summary.metrics.inputTokens} (${summary.metrics.cachedInputTokens} cached); output ${summary.metrics.outputTokens}; reasoning ${summary.metrics.reasoningTokens}; latency ${summary.metrics.latencyMs}ms; cost $${summary.metrics.costUsd.toFixed(4)}.`);
  if (summary.alerts.length) io.table(summary.alerts);
  if (summary.used >= summary.total - summary.effectiveReserve) io.log("BUDGET GATE: closed; rebalance or explicitly release reserve.");
}

async function rebalanceCommand(args, io) {
  const planPath = path.resolve(option(args, "--plan") || args[0] || ".hive/plan.json");
  const usagePath = path.resolve(option(args, "--usage") || ".hive/usage.json");
  const outPath = path.resolve(option(args, "--out") || ".hive/plan.rebalanced.json");
  const plan = await readJson(planPath);
  const usage = await readJsonIfPresent(usagePath, { cells: {} });
  const revised = rebalancePlan(plan, usage, new Date(), { releaseReserve: args.includes("--release-reserve") });
  await writeJson(outPath, revised);
  await appendAudit(auditPath(args, outPath), { event: "plan.rebalanced", revision: revised.revision, reserveReleased: revised.budget.reserveReleased });
  io.log(`Rebalanced revision ${revised.revision}; wrote ${outPath}`);
}

async function explainCommand(args, io) {
  const planPath = path.resolve(option(args, "--plan") || ".hive/plan.json");
  const id = args.find((arg, index) => arg !== "--plan" && args[index - 1] !== "--plan");
  if (!id) throw new Error("explain requires a cell id.");
  io.log(explainCell(await readJson(planPath), id));
}

async function validateCommand(args, io) {
  const missionPath = path.resolve(option(args, "--mission") || args[0] || ".hive/mission.json");
  const errors = validateMission(await readJson(missionPath));
  if (errors.length) throw new Error(errors.join("\n"));
  io.log(`Valid mission: ${missionPath}`);
}

async function gateCommand(args, io) {
  const planPath = path.resolve(option(args, "--plan") || ".hive/plan.json");
  const plan = await readJson(planPath);
  const result = evaluateGate(plan, {
    action: option(args, "--action") || "read",
    paths: options(args, "--path") || [],
    humanApproved: args.includes("--human-approved")
  });
  await appendAudit(auditPath(args, planPath), { event: "gate.checked", ...result });
  io.log(JSON.stringify(result));
  if (!result.allowed) throw new Error(`Gate ${result.result}: ${result.reason}`);
  return result;
}

async function memoryCommand(args, io) {
  const [subcommand, ...rest] = args;
  const storePath = path.resolve(option(rest, "--store") || ".hive/memory.json");
  const saved = await readJsonIfPresent(storePath, { schemaVersion: 1, records: [] });
  const events = [];
  const memory = new ScopedMemory({ records: saved.records || [], onEvent: (event) => events.push(event) });
  const scope = option(rest, "--scope") || "mission";
  const namespace = option(rest, "--namespace") || "default";

  if (subcommand === "put") {
    const content = option(rest, "--content");
    if (!content) throw new Error("memory put requires --content.");
    const record = memory.write({
      scope, namespace, content,
      kind: option(rest, "--kind") || "context",
      trust: rest.includes("--trusted") ? "trusted" : "untrusted",
      visibility: options(rest, "--visibility"),
      ttlMs: optionalNumber(rest, "--ttl-ms"),
      sensitivity: numericOption(rest, "--sensitivity")
    });
    await writeJson(storePath, memory.export());
    await appendAudit(auditPath(rest, storePath), { event: "memory.put", memoryId: record.id, scope, namespace, kind: record.kind, trust: record.trust, visibility: record.visibility });
    io.log(`Stored ${record.id} in ${scope}/${namespace}.`);
    return record;
  }
  if (subcommand === "query") {
    const rows = memory.query({
      scope, namespace, role: option(rest, "--role"),
      limit: optionalInteger(rest, "--limit"),
      minimumScore: optionalNumber(rest, "--minimum-score"),
      maxSensitivity: rest.includes("--include-sensitive") ? 1 : optionalNumber(rest, "--max-sensitivity"),
      trustedOnly: rest.includes("--trusted-only")
    });
    await writeJson(storePath, memory.export());
    await appendAudit(auditPath(rest, storePath), { event: "memory.query", scope, namespace, role: option(rest, "--role") || "*", resultCount: rows.length, trustedOnly: rest.includes("--trusted-only") });
    io.table(rows.map((row) => ({ id: row.id, kind: row.kind, trust: row.trust, score: Math.round(row.retentionScore * 1000) / 1000, content: row.content })));
    return rows;
  }
  if (subcommand === "decay") {
    const summary = memory.decay();
    await writeJson(storePath, memory.export());
    await appendAudit(auditPath(rest, storePath), { event: "memory.decay", ...summary });
    io.log(JSON.stringify(summary));
    return summary;
  }
  if (subcommand === "delete") {
    const deleted = memory.deleteScope({ scope, namespace, reason: option(rest, "--reason") || "scope_expired" });
    await writeJson(storePath, memory.export());
    await appendAudit(auditPath(rest, storePath), { event: "memory.delete", scope, namespace, deleted });
    io.log(`Deleted ${deleted} records from ${scope}/${namespace}.`);
    return deleted;
  }
  throw new Error("memory requires put, query, decay, or delete.");
}

async function runCommand(args, io) {
  const requestedTarget = option(args, "--target");
  if (requestedTarget && !["codex", "claude", "mock"].includes(requestedTarget)) throw new Error("--target must be codex, claude, or mock.");
  const stateDir = path.resolve(option(args, "--state-dir") || ".hive");
  const requestedWorkspace = option(args, "--workspace");
  let workspace = path.resolve(requestedWorkspace || ".");
  const planPath = path.join(stateDir, "plan.json");
  const usagePath = path.join(stateDir, "usage.json");
  const runPath = path.join(stateDir, "run.json");
  const auditFile = path.resolve(option(args, "--audit") || path.join(stateDir, "audit.jsonl"));
  const payloadDir = path.join(stateDir, "payloads");
  const resume = args.includes("--resume");
  let plan;
  let usage;
  let runState;
  let target = requestedTarget || "codex";

  await mkdir(stateDir, { recursive: true });
  if (resume) {
    plan = await readJson(planPath);
    usage = await readJsonIfPresent(usagePath, { schemaVersion: 1, cells: {} });
    runState = await readJson(runPath);
    target = requestedTarget || runState.target;
    if (!["codex", "claude", "mock"].includes(target)) throw new Error("Saved run target is invalid; pass --target explicitly after inspecting run.json.");
    if (requestedTarget && runState.target !== requestedTarget) {
      throw new Error(`Cannot resume a ${runState.target} run with target ${requestedTarget}. Start a new state directory instead.`);
    }
    workspace = requestedWorkspace ? path.resolve(requestedWorkspace) : path.resolve(runState.workspace || ".");
    if (requestedWorkspace && runState.workspace && path.resolve(runState.workspace) !== workspace) {
      throw new Error(`Cannot resume workspace ${runState.workspace} in ${workspace}. Start a new state directory instead.`);
    }
  } else {
    const missionPath = path.resolve(option(args, "--mission") || positional(args)[0] || path.join(stateDir, "mission.json"));
    const mission = await readJson(missionPath);
    const errors = validateMission(mission);
    if (errors.length) throw new Error(errors.join("\n"));
    plan = createPlan(mission);
    usage = { schemaVersion: 1, updatedAt: new Date().toISOString(), cells: {} };
    await writeJson(planPath, plan);
    await writeJson(usagePath, usage);
    await appendAudit(auditFile, { event: "run.created", target, planPath, workspace, cells: plan.cells.length, budget: plan.budget });
  }

  await mkdir(payloadDir, { recursive: true });
  const compileTarget = target === "mock" ? "generic" : target;
  for (const [name, contents] of compileAllPayloads(plan, { target: compileTarget })) {
    await writeFile(path.join(payloadDir, name), contents, "utf8");
  }

  const dryRun = args.includes("--dry-run");
  const approvals = options(args, "--approve") || [];
  const invalidApproval = approvals.find((action) => !["delete", "push", "deploy", "external-write"].includes(action));
  if (invalidApproval) throw new Error(`Unsupported --approve action: ${invalidApproval}.`);
  const driver = await runDriver(target, args, dryRun);
  const result = await runHive({
    plan,
    usage,
    runState,
    target,
    driver,
    workspace,
    model: option(args, "--model"),
    timeoutMs: optionalNumber(args, "--timeout-ms"),
    approvals,
    dryRun,
    resumeBlocked: resume,
    onCheckpoint: async (event) => {
      await writeJson(usagePath, event.usage);
      await writeJson(runPath, event.state);
      await appendAudit(auditFile, {
        event: `run.${event.type}`,
        runId: event.state.runId,
        status: event.state.status,
        cell: event.detail.cell,
        result: event.detail.result,
        reason: event.detail.reason
      });
      if (["cell_started", "cell_finished", "cell_retry_scheduled"].includes(event.type)) {
        io.log(`${event.type}: ${event.detail.cell}${event.detail.result ? ` (${event.detail.result})` : ""}`);
      }
    }
  });
  io.log(`Hive run ${result.state.status}: ${result.state.reason}.`);
  io.log(`Used ${result.summary.used}/${result.summary.total} ${plan.budget.unit}; calls ${result.summary.metrics.modelCalls}; latency ${result.summary.metrics.latencyMs}ms.`);
  if (result.summary.alerts.length) io.table(result.summary.alerts);
  return result;
}

async function runDriver(target, args, dryRun) {
  if (target === "mock") {
    const mockPath = option(args, "--mock-results");
    if (!mockPath && !dryRun) throw new Error("Mock runs require --mock-results.");
    return createMockDriver(mockPath ? await readJson(path.resolve(mockPath)) : {});
  }
  if (target === "codex") {
    const sandbox = option(args, "--sandbox") || "workspace-write";
    if (!["read-only", "workspace-write"].includes(sandbox)) throw new Error("--sandbox must be read-only or workspace-write.");
    return createCodexDriver({ command: option(args, "--codex-command"), sandbox });
  }
  const permissionMode = option(args, "--permission-mode") || "default";
  if (!["default", "dontAsk", "plan", "acceptEdits", "auto"].includes(permissionMode)) {
    throw new Error("--permission-mode must be default, dontAsk, plan, acceptEdits, or auto.");
  }
  return createClaudeDriver({ command: option(args, "--claude-command"), permissionMode });
}

function option(args, name) {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
}

function options(args, name) {
  const values = args.flatMap((arg, index) => arg === name && args[index + 1] ? [args[index + 1]] : []);
  return values.length ? values : undefined;
}

function positional(args) {
  const values = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index].startsWith("--")) {
      if (!["--release-reserve", "--human-approved", "--trusted", "--trusted-only", "--include-sensitive", "--resume", "--dry-run"].includes(args[index])) index += 1;
    } else {
      values.push(args[index]);
    }
  }
  return values;
}

function numericOption(args, name) {
  const value = option(args, name);
  if (value === undefined) return 0;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) throw new Error(`${name} must be a non-negative number.`);
  return number;
}

function optionalNumber(args, name) {
  return option(args, name) === undefined ? undefined : numericOption(args, name);
}

function optionalInteger(args, name) {
  const value = option(args, name);
  if (value === undefined) return undefined;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0) throw new Error(`${name} must be a non-negative integer.`);
  return number;
}

function metricsOptions(args) {
  const fields = {
    modelCalls: "--model-calls",
    inputTokens: "--input-tokens",
    cachedInputTokens: "--cached-input-tokens",
    outputTokens: "--output-tokens",
    reasoningTokens: "--reasoning-tokens",
    latencyMs: "--latency-ms",
    costUsd: "--cost-usd"
  };
  if (!Object.values(fields).some((name) => option(args, name) !== undefined)) return undefined;
  return Object.fromEntries(Object.entries(fields).map(([field, name]) => [field, numericOption(args, name)]));
}

function auditPath(args, statePath) {
  return path.resolve(option(args, "--audit") || path.join(path.dirname(statePath), "audit.jsonl"));
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function readJsonIfPresent(filePath, fallback) {
  try {
    return await readJson(filePath);
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  }
}

async function writeJson(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function helpText() {
  return `Agent Hive CLI

Usage:
  hive init [directory]
  hive validate [mission.json]
  hive plan [mission.json] [--out plan.json]
  hive compile [plan.json] [--target generic|codex|claude] [--out-dir payloads]
  hive compare [mission.json] [--counter heuristic|openai|anthropic|auto] [--model id] [--write-best file]
  hive next [plan.json] [--usage usage.json]
  hive record <cell-id> --status pending|in_progress|done|partial|blocked|failed --used number
              [--attempts number] [--artifact path] [--evidence text] [--blocker text] [--context text]
              [--model-calls n] [--input-tokens n] [--cached-input-tokens n]
              [--output-tokens n] [--reasoning-tokens n] [--latency-ms n] [--cost-usd n]
  hive status [plan.json] [--usage usage.json]
  hive rebalance [plan.json] [--usage usage.json] [--out revised.json] [--release-reserve]
  hive explain <cell-id> [--plan plan.json]
  hive gate --action read|write|delete|push|deploy|external-write|network [--path path] [--human-approved]
  hive memory put|query|decay|delete [--store memory.json] [--scope scope] [--namespace id]
  hive run [mission.json] --target codex|claude|mock [--state-dir .hive] [--workspace path]
           [--resume] [--dry-run] [--approve action] [--model id] [--timeout-ms n]
           [--mock-results file] [--sandbox read-only|workspace-write]
           [--permission-mode default|dontAsk|plan|acceptEdits|auto]`;
}
