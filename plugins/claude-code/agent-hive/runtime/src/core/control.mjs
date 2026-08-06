import { redact } from "./audit.mjs";

export class HookBus {
  constructor(options = {}) {
    this.clock = options.clock || (() => new Date());
    this.handlers = new Map();
    this.events = [];
  }

  on(name, handler) {
    if (typeof handler !== "function") throw new Error("Hook handler must be a function.");
    const handlers = this.handlers.get(name) || [];
    handlers.push(handler);
    this.handlers.set(name, handlers);
    return () => this.handlers.set(name, handlers.filter((candidate) => candidate !== handler));
  }

  async emit(name, data = {}) {
    const event = { name, at: this.clock().toISOString(), data: redact(data) };
    this.events.push(event);
    for (const handler of this.handlers.get(name) || []) await handler(event);
    return event;
  }

  trace() {
    return this.events.map((event) => ({ ...event, data: { ...event.data } }));
  }
}

export class GoalController {
  constructor(contract, options = {}) {
    if (!contract || typeof contract.goal !== "string" || !contract.goal.trim()) {
      throw new Error("goal contract requires a non-empty goal.");
    }
    this.contract = {
      goal: contract.goal.trim(),
      success: {
        confidenceMin: bounded(contract.success?.confidenceMin, 0.85),
        evidenceMin: nonNegativeInteger(contract.success?.evidenceMin, 1)
      },
      budget: {
        maxModelCalls: positiveInteger(contract.budget?.maxModelCalls, 2),
        maxIterations: positiveInteger(contract.budget?.maxIterations, 2),
        maxOutputTokens: positiveInteger(contract.budget?.maxOutputTokens, 512),
        maxTotalTokens: positiveInteger(contract.budget?.maxTotalTokens, 2000),
        maxLatencyMs: positive(contract.budget?.maxLatencyMs, 15000)
      }
    };
    this.hooks = options.hooks || new HookBus(options);
    this.usage = { calls: 0, iterations: 0, inputTokens: 0, outputTokens: 0, totalTokens: 0, latencyMs: 0 };
    this.states = [];
  }

  async recordCall(call) {
    const usage = call.usage || {};
    this.usage.calls += 1;
    this.usage.iterations += 1;
    this.usage.inputTokens += usage.input_tokens || 0;
    this.usage.outputTokens += usage.output_tokens || 0;
    this.usage.totalTokens += usage.total_tokens || (usage.input_tokens || 0) + (usage.output_tokens || 0);
    this.usage.latencyMs += call.latencyMs || 0;
    await this.hooks.emit("after_model_call", { ...this.usage });
    return { ...this.usage };
  }

  evaluate(state = {}) {
    const normalized = {
      answer: String(state.answer || "").trim(),
      confidence: bounded(state.confidence, 0),
      evidenceCount: nonNegativeInteger(state.evidenceCount, 0),
      conflict: Boolean(state.conflict)
    };
    this.states.push(normalized);
    const success = normalized.answer
      && normalized.answer.toLowerCase() !== "unknown"
      && normalized.confidence >= this.contract.success.confidenceMin
      && normalized.evidenceCount >= this.contract.success.evidenceMin
      && !normalized.conflict;
    if (success) return { stop: true, reason: "goal_reached", success: true };
    const budgetReason = this.budgetReason();
    if (budgetReason) return { stop: true, reason: budgetReason, success: false };
    const previous = this.states.at(-2);
    if (previous && previous.answer === normalized.answer && previous.evidenceCount === normalized.evidenceCount) {
      return { stop: true, reason: "no_new_information", success: false };
    }
    return { stop: false, reason: "repair_allowed", success: false };
  }

  budgetReason() {
    const budget = this.contract.budget;
    if (this.usage.calls >= budget.maxModelCalls) return "model_call_budget";
    if (this.usage.iterations >= budget.maxIterations) return "iteration_budget";
    if (this.usage.outputTokens >= budget.maxOutputTokens) return "output_token_budget";
    if (this.usage.totalTokens >= budget.maxTotalTokens) return "total_token_budget";
    if (this.usage.latencyMs >= budget.maxLatencyMs) return "latency_budget";
    return null;
  }

  telemetry() {
    return {
      goal: this.contract.goal,
      success: { ...this.contract.success },
      budget: { ...this.contract.budget },
      usage: { ...this.usage },
      states: this.states.map((state) => ({ ...state })),
      events: this.hooks.trace()
    };
  }
}

function bounded(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
}

function positive(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function positiveInteger(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function nonNegativeInteger(value, fallback) {
  return Number.isInteger(value) && value >= 0 ? value : fallback;
}
