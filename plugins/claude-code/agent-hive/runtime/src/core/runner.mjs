import { randomUUID } from "node:crypto";
import { compilePayload } from "./protocol.mjs";
import { evaluateGate } from "./gate.mjs";
import { nextReadyCells, recordCellUsage, summarizeUsage } from "./usage.mjs";

const FINAL_STATUSES = new Set(["done", "partial", "blocked", "failed"]);

export async function runHive(options) {
  if (!options?.plan || !Array.isArray(options.plan.cells)) throw new Error("runHive requires a plan.");
  if (!options.driver || typeof options.driver.runCell !== "function") throw new Error("runHive requires a driver.");
  const plan = options.plan;
  if (!options.dryRun && !plan.cells.some((cell) => cell.role === "guard" && cell.required !== false)) {
    throw new Error("hive run requires at least one required guard cell.");
  }
  if (!["tokens", "usd-micros"].includes(plan.budget?.unit)) {
    throw new Error(`hive run supports budget units tokens or usd-micros, not ${plan.budget?.unit}.`);
  }
  const target = options.target || "generic";
  const clock = options.clock || (() => new Date());
  const checkpoint = options.onCheckpoint || (async () => {});
  const approvals = new Set(options.approvals || []);
  let usage = clone(options.usage || { schemaVersion: 1, cells: {} });
  usage.schemaVersion = 1;
  usage.cells ||= {};
  usage.updatedAt ||= clock().toISOString();
  let state = options.runState ? clone(options.runState) : newRunState(target, options.driver.name || target, options.workspace || null, clock);
  if (state.workspace && options.workspace && state.workspace !== options.workspace) {
    throw new Error(`Cannot resume workspace ${state.workspace} in ${options.workspace}.`);
  }
  state.history ||= [];
  state.repairs ||= {};
  state.target = target;
  state.driver = options.driver.name || target;
  state.workspace ||= options.workspace || null;
  state.status = options.dryRun ? "dry_run" : "running";
  state.reason = null;
  state.finishedAt = null;
  delete state.gate;
  state.updatedAt = clock().toISOString();

  if (options.resumeBlocked) usage = resetRetryableCells(plan, usage);
  if (options.dryRun) {
    state.schedule = plan.waves.map((wave) => [...wave]);
    state.gates = plan.cells.flatMap((cell) => gateCell(plan, cell, approvals));
    state.reason = state.gates.some((gate) => !gate.allowed) ? "gate_attention_required" : "ready";
    await emit(checkpoint, "dry_run", state, usage, {}, clock);
    return { state, usage, summary: summarizeUsage(plan, usage) };
  }

  const maxExecutions = Math.max(1, plan.cells.length * (plan.guardrails?.maxAttemptsPerCell ?? 2) * 2);
  let executions = 0;
  while (executions < maxExecutions) {
    const summary = summarizeUsage(plan, usage);
    const spendable = summary.total - summary.effectiveReserve;
    const ready = nextReadyCells(plan, usage);
    if (!ready.length) {
      const requiredDone = plan.cells.filter((cell) => cell.required !== false)
        .every((cell) => (usage.cells?.[cell.id]?.status || cell.status) === "done");
      if (requiredDone) return finish("completed", summary.used >= spendable ? "required_done_budget_closed" : "all_required_cells_done");
      if (summary.used >= spendable) return finish("budget_exhausted", "spendable_budget_reached");
      return finish("blocked", blockingReason(plan, usage));
    }

    for (const cell of ready) {
      const liveSummary = summarizeUsage(plan, usage);
      if (liveSummary.used >= liveSummary.total - liveSummary.effectiveReserve) {
        return finish("budget_exhausted", "spendable_budget_reached");
      }
      const previous = usage.cells?.[cell.id] || {};
      if ((previous.used || 0) >= cell.allocation) {
        return finish("blocked", `cell_allocation_exhausted:${cell.id}`);
      }
      const gates = gateCell(plan, cell, approvals);
      const denied = gates.find((gate) => !gate.allowed);
      if (denied) {
        state.currentCell = cell.id;
        state.gate = denied;
        return finish("blocked", denied.reason);
      }

      usage = recordCellUsage(plan, usage, {
        id: cell.id,
        status: "in_progress",
        used: previous.used || 0,
        attempts: previous.attempts || 0,
        metrics: previous.metrics,
        artifacts: previous.artifacts,
        evidence: previous.evidence,
        blockers: previous.blockers,
        reusableContext: previous.reusableContext
      }, clock());
      state.currentCell = cell.id;
      await emit(checkpoint, "cell_started", state, usage, { cell: cell.id }, clock);

      const startedAt = clock();
      let result;
      try {
        result = normalizeResult(await options.driver.runCell({
          cell,
          plan,
          target,
          workspace: options.workspace,
          model: options.model || plan.models?.[cell.modelTier]?.[target],
          prompt: compilePayload(plan, cell, { target }),
          repairContext: state.repairs?.[cell.id] || [],
          timeoutMs: options.timeoutMs
        }));
      } catch (error) {
        result = normalizeResult({ status: "failed", blockers: [error.message], metrics: {} });
      }
      if (["done", "partial"].includes(result.status) && plan.budget.unit === "tokens" && !result.telemetry.tokensReported) {
        result.status = "blocked";
        result.blockers.push("Driver did not report token usage; the token budget cannot be enforced safely.");
      }
      if (["done", "partial"].includes(result.status) && plan.budget.unit === "usd-micros" && !result.telemetry.costReported) {
        result.status = "blocked";
        result.blockers.push("Driver did not report costUsd; the cost budget cannot be enforced safely.");
      }
      if (result.status === "done" && !result.evidence.length) {
        result.status = "partial";
        result.blockers.push("Worker claimed done without verifiable evidence.");
      }
      const finishedAt = clock();
      if (!result.metrics.latencyMs) result.metrics.latencyMs = Math.max(0, finishedAt.getTime() - startedAt.getTime());
      const cumulativeMetrics = addMetrics(previous.metrics, result.metrics);
      const cumulativeUsed = (previous.used || 0) + spentFor(plan.budget.unit, result.metrics);
      usage = recordCellUsage(plan, usage, {
        id: cell.id,
        status: result.status,
        used: cumulativeUsed,
        attempts: (previous.attempts || 0) + 1,
        metrics: cumulativeMetrics,
        artifacts: unique([...(previous.artifacts || []), ...result.artifacts]),
        evidence: unique([...(previous.evidence || []), ...result.evidence]),
        blockers: result.blockers,
        reusableContext: unique([...(previous.reusableContext || []), ...result.reusableContext])
      }, finishedAt);
      executions += 1;
      state.history.push({
        cell: cell.id,
        attempt: usage.cells[cell.id].attempts,
        status: result.status,
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        metrics: result.metrics,
        artifactCount: result.artifacts.length,
        evidenceCount: result.evidence.length,
        blockerCount: result.blockers.length
      });
      await emit(checkpoint, "cell_finished", state, usage, { cell: cell.id, result: result.status }, clock);

      const afterCall = summarizeUsage(plan, usage);
      if (afterCall.used >= afterCall.total - afterCall.effectiveReserve) {
        return finish("budget_exhausted", "spendable_budget_reached");
      }
      if (cumulativeUsed > cell.allocation) {
        return finish("blocked", `cell_allocation_overrun:${cell.id}`);
      }

      if (["partial", "failed"].includes(result.status)
        && usage.cells[cell.id].attempts < (plan.guardrails?.maxAttemptsPerCell ?? 2)) {
        if (cumulativeUsed >= cell.allocation) {
          return finish("blocked", `cell_allocation_exhausted:${cell.id}`);
        }
        state.repairs ||= {};
        state.repairs[cell.id] = result.blockers.length ? result.blockers : ["Previous attempt did not satisfy the return contract."];
        usage = recordCellUsage(plan, usage, {
          id: cell.id,
          status: "pending",
          used: cumulativeUsed,
          attempts: usage.cells[cell.id].attempts,
          metrics: cumulativeMetrics,
          artifacts: usage.cells[cell.id].artifacts,
          evidence: usage.cells[cell.id].evidence,
          blockers: usage.cells[cell.id].blockers,
          reusableContext: usage.cells[cell.id].reusableContext
        }, finishedAt);
        await emit(checkpoint, "cell_retry_scheduled", state, usage, { cell: cell.id }, clock);
      } else if (result.status !== "done") {
        return finish("blocked", result.status === "blocked" ? "worker_requires_input" : "attempt_limit_reached");
      }
    }
  }
  return finish("blocked", "execution_safety_limit");

  async function finish(status, reason) {
    state.status = status;
    state.reason = reason;
    state.currentCell = null;
    state.updatedAt = clock().toISOString();
    if (["completed", "budget_exhausted", "blocked"].includes(status)) state.finishedAt = state.updatedAt;
    await emit(checkpoint, "run_finished", state, usage, { status, reason }, clock);
    return { state, usage, summary: summarizeUsage(plan, usage) };
  }
}

function newRunState(target, driver, workspace, clock) {
  const now = clock().toISOString();
  return {
    schemaVersion: 1,
    runId: randomUUID(),
    target,
    driver,
    workspace,
    status: "pending",
    reason: null,
    currentCell: null,
    startedAt: now,
    updatedAt: now,
    finishedAt: null,
    repairs: {},
    history: []
  };
}

function gateCell(plan, cell, approvals) {
  const actions = cell.actions?.length ? cell.actions : defaultActions(cell.role);
  return actions.map((action) => evaluateGate(plan, {
    action,
    paths: cell.paths || [],
    humanApproved: approvals.has(action)
  }));
}

function defaultActions(role) {
  return [role === "builder" ? "write" : "read"];
}

function normalizeResult(input = {}) {
  const status = FINAL_STATUSES.has(input.status) ? input.status : "partial";
  const rawMetrics = input.metrics || {};
  return {
    status,
    artifacts: strings(input.artifacts),
    evidence: strings(input.evidence),
    blockers: strings(input.blockers),
    reusableContext: strings(input.reusableContext || input.reusable_context),
    metrics: metrics(rawMetrics),
    telemetry: {
      tokensReported: ["inputTokens", "outputTokens", "reasoningTokens"].some((field) => finiteNonNegative(rawMetrics[field])),
      costReported: finiteNonNegative(rawMetrics.costUsd)
    }
  };
}

function metrics(value = {}) {
  return {
    modelCalls: nonNegative(value.modelCalls, 1),
    inputTokens: nonNegative(value.inputTokens),
    cachedInputTokens: nonNegative(value.cachedInputTokens),
    outputTokens: nonNegative(value.outputTokens),
    reasoningTokens: nonNegative(value.reasoningTokens),
    latencyMs: nonNegative(value.latencyMs),
    costUsd: nonNegativeNumber(value.costUsd)
  };
}

function addMetrics(left = {}, right = {}) {
  const a = metrics({ ...left, modelCalls: left?.modelCalls ?? 0 });
  const b = metrics({ ...right, modelCalls: right?.modelCalls ?? 0 });
  return Object.fromEntries(Object.keys(a).map((key) => [key, a[key] + b[key]]));
}

function spentFor(unit, value) {
  if (unit === "usd-micros") return Math.round(value.costUsd * 1_000_000);
  if (unit !== "tokens") throw new Error(`hive run supports budget units tokens or usd-micros, not ${unit}.`);
  return value.inputTokens + value.outputTokens + value.reasoningTokens;
}

function resetRetryableCells(plan, usage) {
  const result = clone(usage);
  for (const cell of plan.cells) {
    const record = result.cells?.[cell.id];
    if (!record || !["blocked", "partial", "failed"].includes(record.status)) continue;
    if ((record.attempts || 0) < (plan.guardrails?.maxAttemptsPerCell ?? 2)) record.status = "pending";
  }
  return result;
}

function blockingReason(plan, usage) {
  const row = plan.cells.find((cell) => ["blocked", "partial", "failed"].includes(usage.cells?.[cell.id]?.status));
  return row ? `cell_${usage.cells[row.id].status}:${row.id}` : "no_ready_cells";
}

async function emit(checkpoint, type, state, usage, detail = {}, clock = () => new Date()) {
  state.updatedAt = clock().toISOString();
  await checkpoint({ type, state: clone(state), usage: clone(usage), detail });
}

function strings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim()) : [];
}

function unique(value) {
  return [...new Set(value)];
}

function nonNegative(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.trunc(number) : fallback;
}

function nonNegativeNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : 0;
}

function finiteNonNegative(value) {
  return value !== undefined && value !== null && Number.isFinite(Number(value)) && Number(value) >= 0;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}
