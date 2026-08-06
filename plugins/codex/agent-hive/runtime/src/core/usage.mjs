import { allocate } from "./planner.mjs";

export function summarizeUsage(plan, usage = {}) {
  const records = usage.cells ?? {};
  const rows = plan.cells.map((cell) => {
    const record = records[cell.id] ?? {};
    const used = Math.max(0, Number(record.used) || 0);
    return {
      id: cell.id,
      role: cell.role,
      status: record.status || cell.status || "pending",
      allocation: cell.allocation,
      used,
      remaining: Math.max(0, cell.allocation - used),
      burnPercent: cell.allocation ? Math.round(used / cell.allocation * 100) : 0,
      attempts: Math.max(0, Number(record.attempts) || 0),
      metrics: normalizeMetrics(record.metrics)
    };
  });
  const result = {
    rows,
    used: rows.reduce((sum, row) => sum + row.used, 0),
    total: plan.budget.total,
    reserve: plan.budget.reserve,
    effectiveReserve: plan.budget.reserveReleased ? 0 : plan.budget.reserve,
    reserveReleased: Boolean(plan.budget.reserveReleased),
    metrics: rows.reduce((total, row) => addMetrics(total, row.metrics), normalizeMetrics())
  };
  result.alerts = usageAlerts(plan, result);
  return result;
}

export function usageAlerts(plan, summary) {
  const alerts = [];
  const spendable = Math.max(1, summary.total - summary.effectiveReserve);
  const burn = summary.used / spendable;
  if (burn >= 1) alerts.push({ severity: "critical", code: "budget_gate_closed", message: `Used ${summary.used}/${spendable} spendable ${plan.budget.unit}.` });
  else if (burn >= 0.8) alerts.push({ severity: "warning", code: "budget_near_limit", message: `Used ${Math.round(burn * 100)}% of spendable budget.` });
  for (const row of summary.rows) {
    if (row.used > row.allocation) alerts.push({ severity: "warning", code: "cell_overrun", cell: row.id, message: `${row.id} used ${row.used}/${row.allocation}.` });
    if (["blocked", "failed"].includes(row.status)) alerts.push({ severity: "warning", code: `cell_${row.status}`, cell: row.id, message: `${row.id} is ${row.status}.` });
    if (row.attempts >= (plan.guardrails?.maxAttemptsPerCell ?? 2) && row.status !== "done") {
      alerts.push({ severity: "critical", code: "attempt_limit", cell: row.id, message: `${row.id} reached its attempt limit.` });
    }
  }
  return alerts;
}

export function nextReadyCells(plan, usage = {}) {
  const records = usage.cells ?? {};
  const summary = summarizeUsage(plan, usage);
  const spendable = plan.budget.total - summary.effectiveReserve;
  if (summary.used >= spendable) return [];
  const done = new Set(plan.cells
    .filter((cell) => (records[cell.id]?.status || cell.status) === "done")
    .map((cell) => cell.id));
  return plan.cells
    .filter((cell) => {
      const status = records[cell.id]?.status || cell.status || "pending";
      return status === "pending" && cell.dependencies.every((id) => done.has(id));
    })
    .sort((a, b) => b.priority - a.priority || b.risk - a.risk || a.id.localeCompare(b.id))
    .slice(0, plan.policy.maxWorkers);
}

export function recordCellUsage(plan, usage = {}, record, now = new Date()) {
  if (!plan.cells.some((cell) => cell.id === record.id)) throw new Error(`Unknown cell: ${record.id}`);
  if (!["pending", "in_progress", "done", "partial", "blocked", "failed"].includes(record.status)) {
    throw new Error(`Invalid cell status: ${record.status}`);
  }
  if (!Number.isInteger(record.used) || record.used < 0) throw new Error("used must be a non-negative integer.");
  const previous = usage.cells?.[record.id] ?? {};
  const completedAttempt = ["done", "partial", "blocked", "failed"].includes(record.status) ? 1 : 0;
  const attempts = record.attempts ?? ((previous.attempts ?? 0) + completedAttempt);
  if (!Number.isInteger(attempts) || attempts < 0) throw new Error("attempts must be a non-negative integer.");
  if (attempts > (plan.guardrails?.maxAttemptsPerCell ?? 2)) {
    throw new Error(`Attempt limit exceeded for ${record.id}.`);
  }
  return {
    schemaVersion: 1,
    updatedAt: now.toISOString(),
    cells: {
      ...(usage.cells ?? {}),
      [record.id]: {
        ...previous,
        status: record.status,
        used: record.used,
        attempts,
        metrics: normalizeMetrics(record.metrics ?? previous.metrics),
        artifacts: record.artifacts ?? usage.cells?.[record.id]?.artifacts ?? [],
        evidence: record.evidence ?? usage.cells?.[record.id]?.evidence ?? [],
        blockers: record.blockers ?? usage.cells?.[record.id]?.blockers ?? [],
        reusableContext: record.reusableContext ?? usage.cells?.[record.id]?.reusableContext ?? []
      }
    }
  };
}

function normalizeMetrics(value = {}) {
  const integer = (field) => Math.max(0, Number.isFinite(Number(value?.[field])) ? Math.trunc(Number(value[field])) : 0);
  const number = (field) => Math.max(0, Number.isFinite(Number(value?.[field])) ? Number(value[field]) : 0);
  return {
    modelCalls: integer("modelCalls"),
    inputTokens: integer("inputTokens"),
    cachedInputTokens: integer("cachedInputTokens"),
    outputTokens: integer("outputTokens"),
    reasoningTokens: integer("reasoningTokens"),
    latencyMs: integer("latencyMs"),
    costUsd: number("costUsd")
  };
}

function addMetrics(left, right) {
  return Object.fromEntries(Object.keys(left).map((key) => [key, left[key] + right[key]]));
}

export function rebalancePlan(plan, usage = {}, now = new Date(), options = {}) {
  const summary = summarizeUsage(plan, usage);
  const records = usage.cells ?? {};
  const pending = plan.cells.filter((cell) => (records[cell.id]?.status || cell.status) !== "done");
  const reserveReleased = Boolean(options.releaseReserve || plan.budget.reserveReleased);
  const protectedReserve = reserveReleased ? 0 : plan.budget.reserve;
  const futureBudget = Math.max(0, plan.budget.total - protectedReserve - summary.used);
  const allocations = pending.length ? allocate(futureBudget, pending) : new Map();

  return {
    ...plan,
    revision: (plan.revision || 1) + 1,
    rebalancedAt: now.toISOString(),
    budget: {
      ...plan.budget,
      allocated: summary.used + futureBudget,
      reserveReleased
    },
    cells: plan.cells.map((cell) => {
      const record = records[cell.id] ?? {};
      const used = Math.max(0, Number(record.used) || 0);
      const status = record.status || cell.status || "pending";
      if (status === "done") {
        return { ...cell, status: "done", allocation: used };
      }
      return { ...cell, status, allocation: used + (allocations.get(cell.id) ?? 0) };
    })
  };
}
