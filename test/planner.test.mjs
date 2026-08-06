import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createPlan } from "../src/core/planner.mjs";
import { compilePayload } from "../src/core/protocol.mjs";
import { compareMissionVariants, renderMissionVariants } from "../src/core/prompt-compiler.mjs";
import { anthropicMessageCount, heuristicCount } from "../src/core/token-counter.mjs";
import { nextReadyCells, rebalancePlan, recordCellUsage } from "../src/core/usage.mjs";
import { defaultMission, validateMission } from "../src/core/mission.mjs";

test("allocation preserves total and protected reserve", () => {
  const mission = defaultMission();
  mission.budget.total = 100003;
  const plan = createPlan(mission, new Date("2026-01-01T00:00:00Z"));
  const allocated = plan.cells.reduce((sum, cell) => sum + cell.allocation, 0);
  assert.equal(plan.budget.reserve, 20000);
  assert.equal(allocated, plan.budget.total - plan.budget.reserve);
});

test("dependency graph produces ordered waves", () => {
  const plan = createPlan(defaultMission());
  assert.deepEqual(plan.waves, [["survey"], ["design"], ["build"], ["verify"], ["distill"]]);
});

test("HIVE/1 preserves non-Latin mission text", async () => {
  const mission = JSON.parse(await readFile(new URL("../examples/missions/japanese-release.json", import.meta.url), "utf8"));
  const plan = createPlan(mission);
  const payload = compilePayload(plan, plan.cells[0]);
  assert.match(payload, /既存のログイン機能を壊さずに/);
  assert.match(payload, /^HIVE\/1/);
});

test("target payload resolves the configured model tier", () => {
  const mission = defaultMission();
  mission.models = { frontier: { codex: "gpt-example", claude: "claude-example" } };
  const plan = createPlan(mission);
  const cell = plan.cells.find((candidate) => candidate.modelTier === "frontier");
  assert.match(compilePayload(plan, cell, { target: "codex" }), /TARGET: codex\nMODEL: gpt-example/);
});

test("prompt variants preserve multilingual literals and compare deterministically", async () => {
  const mission = {
    goal: "צור API בשם user_id",
    sourceLanguage: "he",
    responseLanguage: "he",
    must: ["אל תשנה user_id"],
    avoid: ["מחיקת נתונים"],
    doneWhen: ["הבדיקות עוברות"]
  };
  const first = renderMissionVariants(mission);
  const second = renderMissionVariants(mission);
  assert.equal(first[0].fingerprint, second[0].fingerprint);
  assert.ok(first.every((candidate) => candidate.literalsPreserved));
  const compared = await compareMissionVariants(mission, async (text) => heuristicCount(text));
  assert.ok(compared.every((candidate) => candidate.precision === "heuristic"));
  assert.ok(compared[0].tokens <= compared.at(-1).tokens);
});

test("Anthropic counter reports provider estimate from token count endpoint", async () => {
  const calls = [];
  const result = await anthropicMessageCount("hola", "claude-test", {
    apiKey: "test-key",
    fetch: async (url, init) => {
      calls.push({ url, init });
      return { ok: true, json: async () => ({ input_tokens: 7 }) };
    }
  });
  assert.equal(result.tokens, 7);
  assert.equal(result.precision, "provider-estimate");
  assert.match(calls[0].url, /\/v1\/messages\/count_tokens$/);
  assert.equal(JSON.parse(calls[0].init.body).messages[0].content, "hola");
});

test("rebalance protects reserve and moves remaining energy", () => {
  const plan = createPlan(defaultMission(), new Date("2026-01-01T00:00:00Z"));
  const revised = rebalancePlan(plan, {
    cells: {
      survey: { used: 5000, status: "done" },
      design: { used: 10000, status: "in_progress" }
    }
  }, new Date("2026-01-02T00:00:00Z"));
  const openAllocation = revised.cells
    .filter((cell) => cell.status !== "done")
    .reduce((sum, cell) => {
      const used = cell.id === "design" ? 10000 : 0;
      return sum + cell.allocation - used;
    }, 0);
  assert.equal(openAllocation, plan.budget.total - plan.budget.reserve - 15000);
  assert.equal(revised.cells.reduce((sum, cell) => sum + cell.allocation, 0), plan.budget.allocated);
  assert.equal(revised.revision, 2);
});

test("lifecycle unlocks dependencies and reserve release is explicit", () => {
  const plan = createPlan(defaultMission(), new Date("2026-01-01T00:00:00Z"));
  assert.deepEqual(nextReadyCells(plan).map((cell) => cell.id), ["survey"]);
  const usage = recordCellUsage(plan, {}, {
    id: "survey", status: "done", used: 1000, artifacts: ["map.md"], evidence: ["test"]
  }, new Date("2026-01-01T01:00:00Z"));
  assert.deepEqual(nextReadyCells(plan, usage).map((cell) => cell.id), ["design"]);
  assert.equal(usage.cells.survey.artifacts[0], "map.md");
  const revised = rebalancePlan(plan, usage, new Date("2026-01-02T00:00:00Z"), { releaseReserve: true });
  assert.equal(revised.budget.reserveReleased, true);
  assert.equal(revised.budget.allocated, plan.budget.total);
});

test("validation detects dependency cycles", () => {
  const mission = defaultMission();
  mission.cells = [
    { id: "a", title: "A", role: "scout", priority: 1, complexity: 1, risk: 1, dependencies: ["b"] },
    { id: "b", title: "B", role: "builder", priority: 1, complexity: 1, risk: 1, dependencies: ["a"] }
  ];
  assert.ok(validateMission(mission).some((error) => error.includes("cycle")));
});
