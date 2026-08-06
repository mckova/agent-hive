import test from "node:test";
import assert from "node:assert/strict";
import { GoalController, HookBus } from "../src/core/control.mjs";
import { ScopedMemory, retentionScore } from "../src/core/memory.mjs";

test("scoped memory does not cross namespaces or visibility", () => {
  const now = new Date("2026-01-01T00:00:00Z");
  const memory = new ScopedMemory({ clock: () => now });
  memory.write({ scope: "project", namespace: "alpha", content: "A", visibility: ["builder"] });
  memory.write({ scope: "project", namespace: "beta", content: "B", visibility: ["builder"] });
  assert.deepEqual(memory.query({ scope: "project", namespace: "alpha", role: "guard" }), []);
  assert.deepEqual(memory.query({ scope: "project", namespace: "alpha", role: "builder" }).map((row) => row.content), ["A"]);
});

test("decay deletes expired short-term memory", () => {
  const started = new Date("2026-01-01T00:00:00Z");
  const memory = new ScopedMemory({ clock: () => started });
  memory.write({ scope: "agent", namespace: "mission-1", content: "scratch", ttlMs: 1000 });
  assert.equal(memory.decay({ now: new Date(started.getTime() + 1001) }).deleted, 1);
  assert.equal(memory.snapshot().length, 0);
});

test("reinforcement requires verified successful use", () => {
  const now = new Date("2026-01-01T00:00:00Z");
  const memory = new ScopedMemory({ clock: () => now });
  const row = memory.write({ scope: "team", namespace: "mission-1", content: "fact", trust: "trusted" });
  memory.reinforce(row.id, { verified: false, successful: true });
  assert.equal(memory.snapshot()[0].reuseCount, 0);
  memory.reinforce(row.id, { verified: true, successful: true });
  assert.equal(memory.snapshot()[0].reuseCount, 1);
  assert.ok(retentionScore(memory.snapshot()[0], now) > 0.99);
});

test("memory export restores scopes and filters untrusted or sensitive recall", () => {
  const now = new Date("2026-01-01T00:00:00Z");
  const original = new ScopedMemory({ clock: () => now });
  original.write({ scope: "mission", namespace: "m1", content: "verified", trust: "trusted" });
  original.write({ scope: "mission", namespace: "m1", content: "web says ignore mission", trust: "untrusted" });
  original.write({ scope: "mission", namespace: "m1", content: "private", trust: "trusted", sensitivity: 0.9 });
  const restored = new ScopedMemory({ clock: () => now, records: original.export().records });
  assert.deepEqual(
    restored.query({ scope: "mission", namespace: "m1", trustedOnly: true }).map((row) => row.content),
    ["verified"]
  );
  assert.equal(restored.snapshot({ includeContent: true }).length, 3);
});

test("goal controller stops on success and enforces call budgets", async () => {
  const hooks = new HookBus({ clock: () => new Date("2026-01-01T00:00:00Z") });
  const controller = new GoalController({
    goal: "answer",
    success: { confidenceMin: 0.8, evidenceMin: 2 },
    budget: { maxModelCalls: 2, maxIterations: 2, maxOutputTokens: 100, maxTotalTokens: 1000, maxLatencyMs: 5000 }
  }, { hooks });
  await controller.recordCall({ latencyMs: 100, usage: { input_tokens: 20, output_tokens: 5, total_tokens: 25 } });
  assert.deepEqual(controller.evaluate({ answer: "yes", confidence: 0.9, evidenceCount: 2 }), {
    stop: true,
    reason: "goal_reached",
    success: true
  });
  assert.equal(controller.telemetry().events[0].name, "after_model_call");
});
