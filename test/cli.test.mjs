import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { runCli } from "../src/cli.mjs";
import { defaultMission } from "../src/core/mission.mjs";

test("CLI completes a plan, next, record, and compare lifecycle", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "agent-hive-test-"));
  const missionPath = path.join(directory, "mission.json");
  const planPath = path.join(directory, "plan.json");
  const usagePath = path.join(directory, "usage.json");
  const output = [];
  const io = { log: (value) => output.push(String(value)), table: (value) => output.push(value) };
  try {
    await writeFile(missionPath, JSON.stringify(defaultMission()), "utf8");
    await runCli(["plan", missionPath, "--out", planPath], io);
    await runCli(["next", planPath, "--usage", usagePath], io);
    await runCli(["record", "survey", "--status", "done", "--used", "123", "--artifact", "map.md", "--plan", planPath, "--usage", usagePath], io);
    await runCli(["compare", missionPath, "--counter", "heuristic"], io);
    const usage = JSON.parse(await readFile(usagePath, "utf8"));
    assert.equal(usage.cells.survey.status, "done");
    assert.equal(usage.cells.survey.used, 123);
    assert.equal(usage.cells.survey.attempts, 1);
    assert.deepEqual(usage.cells.survey.artifacts, ["map.md"]);
    assert.ok(output.some((value) => Array.isArray(value) && value.some((row) => row.id === "survey")));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
