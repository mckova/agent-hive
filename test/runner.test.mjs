import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runCli } from "../src/cli.mjs";
import { createPlan } from "../src/core/planner.mjs";
import { defaultMission } from "../src/core/mission.mjs";
import { runHive } from "../src/core/runner.mjs";
import { createMockDriver, parseClaudeOutput, parseCodexOutput, parseWorkerResult } from "../src/drivers/cli-drivers.mjs";

test("runner retries a partial cell, preserves usage, and completes through guard", async () => {
  const plan = createPlan(twoCellMission());
  const checkpoints = [];
  const result = await runHive({
    plan,
    target: "mock",
    workspace: ".",
    driver: createMockDriver({ cells: {
      build: [
        { status: "partial", blockers: ["missing edge case"], metrics: metric(100, 10) },
        { status: "done", artifacts: ["src/result.mjs"], evidence: ["tests pass"], metrics: metric(100, 20) }
      ],
      verify: { status: "done", evidence: ["guard pass"], metrics: metric(80, 10) }
    } }),
    onCheckpoint: async (event) => checkpoints.push(event.type)
  });
  assert.equal(result.state.status, "completed");
  assert.equal(result.usage.cells.build.attempts, 2);
  assert.equal(result.usage.cells.verify.attempts, 1);
  assert.equal(result.summary.used, 320);
  assert.equal(result.summary.metrics.modelCalls, 3);
  assert.deepEqual(result.usage.cells.build.artifacts, ["src/result.mjs"]);
  assert.ok(checkpoints.includes("cell_retry_scheduled"));
});

test("runner stops before a human-gated action", async () => {
  const mission = twoCellMission();
  mission.cells[0].actions = ["deploy"];
  const result = await runHive({
    plan: createPlan(mission),
    target: "mock",
    driver: createMockDriver({}),
    workspace: "."
  });
  assert.equal(result.state.status, "blocked");
  assert.equal(result.state.reason, "approval_required:deploy");
  assert.equal(result.summary.metrics.modelCalls, 0);
});

test("runner stops when a call crosses the spendable budget", async () => {
  const mission = twoCellMission();
  mission.budget = { unit: "tokens", total: 100, reservePercent: 20 };
  const result = await runHive({
    plan: createPlan(mission),
    target: "mock",
    driver: createMockDriver({ cells: {
      build: { status: "done", metrics: metric(85, 5) },
      verify: { status: "done", metrics: metric(1, 1) }
    } }),
    workspace: "."
  });
  assert.equal(result.state.status, "budget_exhausted");
  assert.equal(result.usage.cells.verify, undefined);
});

test("runner blocks successful claims when budget telemetry is missing", async () => {
  const result = await runHive({
    plan: createPlan(twoCellMission()),
    target: "mock",
    driver: createMockDriver({ cells: {
      build: { status: "done", artifacts: ["src/result.mjs"] }
    } })
  });
  assert.equal(result.state.status, "blocked");
  assert.match(result.usage.cells.build.blockers[0], /token usage/);
});

test("runner requires a guard and evidence before autonomous completion", async () => {
  const noGuard = twoCellMission();
  noGuard.cells = [noGuard.cells[0]];
  await assert.rejects(() => runHive({
    plan: createPlan(noGuard),
    target: "mock",
    driver: createMockDriver({})
  }), /required guard cell/);

  const noEvidence = await runHive({
    plan: createPlan(twoCellMission()),
    target: "mock",
    driver: createMockDriver({ cells: {
      build: { status: "done", metrics: metric(10, 2) }
    } })
  });
  assert.equal(noEvidence.state.status, "blocked");
  assert.equal(noEvidence.usage.cells.build.attempts, 2);
  assert.match(noEvidence.usage.cells.build.blockers[0], /without verifiable evidence/);
});

test("runner stops for explicit rebalance after a cell overruns its allocation", async () => {
  const plan = createPlan(twoCellMission());
  const buildAllocation = plan.cells.find((cell) => cell.id === "build").allocation;
  const result = await runHive({
    plan,
    target: "mock",
    driver: createMockDriver({ cells: {
      build: { status: "done", metrics: metric(buildAllocation, 1) }
    } })
  });
  assert.equal(result.state.status, "blocked");
  assert.equal(result.state.reason, "cell_allocation_overrun:build");
  assert.equal(result.usage.cells.verify, undefined);
});

test("explicit resume retries a previously blocked cell", async () => {
  const plan = createPlan(twoCellMission());
  const first = await runHive({
    plan,
    target: "mock",
    driver: createMockDriver({ cells: {
      build: { status: "done", evidence: ["build verified"], metrics: metric(10, 2) },
      verify: { status: "blocked", blockers: ["need fixture"], metrics: metric(5, 1) }
    } }),
    workspace: "."
  });
  assert.equal(first.state.status, "blocked");
  const resumeCheckpoints = [];
  const resumed = await runHive({
    plan,
    usage: first.usage,
    runState: first.state,
    resumeBlocked: true,
    target: "mock",
    driver: createMockDriver({ cells: {
      verify: { status: "done", evidence: ["fixture supplied"], metrics: metric(5, 1) }
    } }),
    workspace: ".",
    onCheckpoint: async (event) => resumeCheckpoints.push(event)
  });
  assert.equal(resumed.state.status, "completed");
  assert.equal(resumed.usage.cells.verify.attempts, 2);
  assert.equal(resumeCheckpoints.find((event) => event.type === "cell_started").state.finishedAt, null);
});

test("runner rechecks the global budget between cells in the same ready wave", async () => {
  const mission = twoCellMission();
  mission.policy.maxWorkers = 2;
  mission.budget = { unit: "tokens", total: 100, reservePercent: 20 };
  mission.cells[1].dependencies = [];
  mission.cells[1].priority = 4;
  const result = await runHive({
    plan: createPlan(mission),
    target: "mock",
    driver: createMockDriver({ cells: {
      build: { status: "done", metrics: metric(85, 5) },
      verify: { status: "done", metrics: metric(1, 1) }
    } })
  });
  assert.equal(result.state.status, "budget_exhausted");
  assert.equal(result.usage.cells.verify, undefined);
});

test("driver parsers require and extract the structured worker contract", () => {
  const contract = 'HIVE_RESULT_JSON:{"status":"done","artifacts":["a.md"],"evidence":["ok"],"blockers":[],"reusable_context":["fact"]}';
  const direct = parseWorkerResult(contract, { exitCode: 0, metrics: metric(1, 1) });
  assert.equal(direct.status, "done");
  assert.deepEqual(direct.reusableContext, ["fact"]);

  const codex = parseCodexOutput([
    JSON.stringify({ type: "item.completed", item: { type: "agent_message", text: contract } }),
    JSON.stringify({ type: "turn.completed", usage: { input_tokens: 10, cached_input_tokens: 4, output_tokens: 3, reasoning_output_tokens: 2 } })
  ].join("\n"), { exitCode: 0, elapsedMs: 20 });
  assert.equal(codex.status, "done");
  assert.equal(codex.metrics.cachedInputTokens, 4);

  const claude = parseClaudeOutput(JSON.stringify({
    result: contract,
    num_turns: 2,
    total_cost_usd: 0.01,
    usage: { input_tokens: 8, cache_read_input_tokens: 3, cache_creation_input_tokens: 2, output_tokens: 4 }
  }), { exitCode: 0, elapsedMs: 30 });
  assert.equal(claude.status, "done");
  assert.equal(claude.metrics.cachedInputTokens, 5);
  assert.equal(claude.metrics.inputTokens, 13);
  assert.equal(claude.metrics.modelCalls, 2);
  assert.equal(claude.metrics.costUsd, 0.01);

  const timedOut = parseWorkerResult(contract, { exitCode: 124, stderr: "Driver timed out." });
  assert.equal(timedOut.status, "failed");
  assert.match(timedOut.blockers[0], /timed out/);
});

test("CLI run with mock driver writes resumable state and payloads", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "agent-hive-run-"));
  const missionPath = path.join(directory, "mission.json");
  const scenarioPath = path.join(directory, "mock.json");
  const stateDir = path.join(directory, ".hive");
  const output = [];
  const io = { log: (value) => output.push(String(value)), table: (value) => output.push(value) };
  try {
    await writeFile(missionPath, JSON.stringify(twoCellMission()), "utf8");
    await writeFile(scenarioPath, JSON.stringify({ cells: {
      build: { status: "done", artifacts: ["result.mjs"], evidence: ["built"], metrics: metric(10, 2) },
      verify: { status: "done", evidence: ["verified"], metrics: metric(5, 1) }
    } }), "utf8");
    const result = await runCli(["run", missionPath, "--target", "mock", "--state-dir", stateDir, "--workspace", directory, "--mock-results", scenarioPath], io);
    assert.equal(result.state.status, "completed");
    assert.equal(JSON.parse(await readFile(path.join(stateDir, "run.json"), "utf8")).status, "completed");
    assert.equal(JSON.parse(await readFile(path.join(stateDir, "usage.json"), "utf8")).cells.verify.status, "done");
    assert.match(await readFile(path.join(stateDir, "payloads", "build.hive"), "utf8"), /HIVE\/1/);
    assert.ok(output.some((line) => line.includes("Hive run completed")));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("CLI resume reuses the saved target and completes a blocked mock run", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "agent-hive-resume-"));
  const missionPath = path.join(directory, "mission.json");
  const firstScenario = path.join(directory, "first.json");
  const resumeScenario = path.join(directory, "resume.json");
  const stateDir = path.join(directory, ".hive");
  const io = { log: () => {}, table: () => {} };
  try {
    await writeFile(missionPath, JSON.stringify(twoCellMission()), "utf8");
    await writeFile(firstScenario, JSON.stringify({ cells: {
      build: { status: "done", evidence: ["build verified"], metrics: metric(10, 2) },
      verify: { status: "blocked", blockers: ["fixture missing"], metrics: metric(5, 1) }
    } }), "utf8");
    const first = await runCli(["run", missionPath, "--target", "mock", "--state-dir", stateDir, "--workspace", directory, "--mock-results", firstScenario], io);
    assert.equal(first.state.status, "blocked");
    assert.equal(first.state.target, "mock");
    assert.equal(first.state.workspace, directory);

    await writeFile(resumeScenario, JSON.stringify({ cells: {
      verify: { status: "done", evidence: ["fixture verified"], metrics: metric(5, 1) }
    } }), "utf8");
    const resumed = await runCli(["run", "--resume", "--state-dir", stateDir, "--workspace", directory, "--mock-results", resumeScenario], io);
    assert.equal(resumed.state.status, "completed");
    assert.equal(resumed.usage.cells.verify.attempts, 2);
    await assert.rejects(() => runCli(["run", "--resume", "--state-dir", stateDir, "--workspace", path.join(directory, "other"), "--mock-results", resumeScenario], io), /Cannot resume workspace/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("CLI process exit codes distinguish success, invalid input, and a controlled stop", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "agent-hive-exit-"));
  const missionPath = path.join(directory, "mission.json");
  const gatedPath = path.join(directory, "gated.json");
  const binPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "bin", "hive.mjs");
  try {
    await writeFile(missionPath, JSON.stringify(twoCellMission()), "utf8");
    const gated = twoCellMission();
    gated.cells[0].actions = ["deploy"];
    await writeFile(gatedPath, JSON.stringify(gated), "utf8");

    const success = spawnSync(process.execPath, [binPath, "run", missionPath, "--target", "codex", "--dry-run", "--state-dir", path.join(directory, "clean"), "--workspace", directory], processOptions());
    assert.equal(success.status, 0, success.stderr);

    const controlled = spawnSync(process.execPath, [binPath, "run", gatedPath, "--target", "codex", "--dry-run", "--state-dir", path.join(directory, "gated"), "--workspace", directory], processOptions());
    assert.equal(controlled.status, 2, controlled.stderr);

    const invalid = spawnSync(process.execPath, [binPath, "run", path.join(directory, "missing.json"), "--dry-run"], processOptions());
    assert.equal(invalid.status, 1, invalid.stderr);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

function twoCellMission() {
  const mission = defaultMission();
  mission.budget = { unit: "tokens", total: 10000, reservePercent: 20 };
  mission.policy = { maxWorkers: 1, qualityFloor: "economy" };
  mission.cells = [
    { id: "build", title: "Build the artifact", role: "builder", priority: 5, complexity: 3, risk: 3, dependencies: [], required: true, actions: ["write"], paths: ["src"] },
    { id: "verify", title: "Verify the artifact", role: "guard", priority: 5, complexity: 2, risk: 5, dependencies: ["build"], required: true, actions: ["read"], paths: ["src"] }
  ];
  return mission;
}

function metric(inputTokens, outputTokens) {
  return { modelCalls: 1, inputTokens, cachedInputTokens: 0, outputTokens, reasoningTokens: 0, latencyMs: 10, costUsd: 0 };
}

function processOptions() {
  return { encoding: "utf8", windowsHide: true, timeout: 30000 };
}
