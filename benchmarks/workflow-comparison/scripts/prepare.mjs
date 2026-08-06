import { cp, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createPlan } from "../../../src/core/planner.mjs";
import { compileAllPayloads } from "../../../src/core/protocol.mjs";

const benchmarkRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(benchmarkRoot, "..", "..");
const runRoot = path.resolve(process.argv[2] || path.join("C:\\tmp", `agent-hive-workflow-bench-${Date.now()}`));
const cavemanRepo = path.resolve(process.argv[3] || "C:\\tmp\\bench-caveman");
const ralphRepo = path.resolve(process.argv[4] || "C:\\tmp\\bench-ralph-loop");
const loopRepo = path.resolve(process.argv[5] || "C:\\tmp\\bench-loop-engineering");
const hiveProfile = process.argv[6] || "full";
const arms = ["normal", "caveman", "ralph", "loop-engineering", "agent-hive"];

await mkdir(runRoot, { recursive: false });
for (const arm of arms) {
  await cp(path.join(benchmarkRoot, "fixture"), path.join(runRoot, arm), { recursive: true });
  await mkdir(path.join(runRoot, arm, ".bench"), { recursive: true });
}

await mkdir(path.join(runRoot, "caveman", ".agents", "skills"), { recursive: true });
await cp(path.join(cavemanRepo, "skills", "caveman"), path.join(runRoot, "caveman", ".agents", "skills", "caveman"), { recursive: true });

const ralphDir = path.join(runRoot, "ralph", ".agent");
await mkdir(path.join(ralphDir, "tasks"), { recursive: true });
await cp(path.join(ralphRepo, ".agent", "PROMPT.md"), path.join(ralphDir, "UPSTREAM_PROMPT.md"));
await writeJson(path.join(ralphDir, "tasks.json"), [
  { id: "TASK-001", priority: 1, title: "Implement the rate limiter", passes: false },
  { id: "TASK-002", priority: 2, title: "Verify requirements and repair gaps", passes: false }
]);
await writeJson(path.join(ralphDir, "tasks", "TASK-001.json"), {
  id: "TASK-001", objective: "Implement every requirement in TASK.md and run npm test.", allowedFiles: ["src/rate-limiter.mjs", ".agent/tasks.json"]
});
await writeJson(path.join(ralphDir, "tasks", "TASK-002.json"), {
  id: "TASK-002", objective: "Independently audit the implementation against TASK.md, repair any gap, and run npm test.", allowedFiles: ["src/rate-limiter.mjs", ".agent/tasks.json"]
});
await writeFile(path.join(ralphDir, "BENCHMARK_PROMPT.md"), `# Ralph benchmark adaptation\n\nFollow the upstream one-task-per-fresh-context method in UPSTREAM_PROMPT.md. This fixture has no dev server, screenshots, formatter, or git repository.\n\n1. Read tasks.json and choose the lowest-priority-number item whose passes is false.\n2. Read that task file and TASK.md.\n3. Complete only that task. Never inspect parent or sibling directories.\n4. Run npm test. Do not edit package.json or checks/.\n5. Set only the completed task's passes to true after tests pass.\n6. End with TASK-{ID}:DONE, BLOCKED:reason, or DECIDE:question.\n`, "utf8");

const loopArm = path.join(runRoot, "loop-engineering");
await mkdir(path.join(loopArm, ".agents", "skills"), { recursive: true });
for (const skill of ["minimal-fix", "loop-verifier"]) {
  await cp(path.join(loopRepo, "skills", skill), path.join(loopArm, ".agents", "skills", skill), { recursive: true });
}
await writeFile(path.join(loopArm, "LOOP.md"), `# Benchmark loop\n\nDiscover TASK.md, hand it to a maker, verify independently, record state, and stop. Maximum repair attempts: 2. Human review required for destructive or out-of-scope changes.\n`, "utf8");
await writeFile(path.join(loopArm, "STATE.md"), `# State\n\nstatus: pending\nattempt: 0\nlast_verdict: none\n`, "utf8");
await writeFile(path.join(loopArm, "loop-budget.md"), `# Budget\n\nMaximum model turns: 4. Stop on the second rejected repair. Record every turn in .bench/.\n`, "utf8");
await writeFile(path.join(loopArm, "loop-constraints.md"), `# Constraints\n\n- Never inspect parent or sibling directories.\n- Only src/rate-limiter.mjs and STATE.md may be edited.\n- Never edit tests, package.json, credentials, or environment files.\n- Run npm test.\n- Verifier must not trust maker claims.\n`, "utf8");

const hiveArm = path.join(runRoot, "agent-hive");
const hiveDir = path.join(hiveArm, ".hive");
await mkdir(path.join(hiveDir, "payloads"), { recursive: true });
await cp(path.join(repositoryRoot, "plugins", "codex", "agent-hive", "skills", "run-agent-hive"), path.join(hiveArm, ".bench", "run-agent-hive"), { recursive: true });
const mission = {
  schemaVersion: 1,
  mission: {
    goal: "ממשו במדויק את TASK.md, שמרו על אבטחה, מגבלת זיכרון ובדיקות.",
    sourceLanguage: "he",
    responseLanguage: "he",
    must: ["אין לשנות package.json או checks/", "אין לקרוא תיקיות אב או sibling", "יש להריץ npm test"],
    avoid: ["dependencies", "timers", "object עם user-controlled keys"],
    doneWhen: ["כל הבדיקות הציבוריות עוברות", "guard מאמת כל סעיף ב-TASK.md"]
  },
  budget: { unit: "tokens", total: 80000, reservePercent: 20 },
  policy: { maxWorkers: 1, qualityFloor: "economy" },
  models: {},
  cells: hiveProfile === "compact" ? [
    { id: "build", title: "Implement TASK.md in src/rate-limiter.mjs and run public tests", role: "builder", priority: 5, complexity: 4, risk: 4, dependencies: [], required: true },
    { id: "verify", title: "Independently verify code, public tests, security, scope, and every TASK.md requirement", role: "guard", priority: 5, complexity: 3, risk: 5, dependencies: ["build"], required: true }
  ] : [
    { id: "survey", title: "Map requirements, edge cases, and security risks; write .hive/survey.md", role: "scout", priority: 5, complexity: 2, risk: 3, dependencies: [], required: true },
    { id: "build", title: "Implement TASK.md in src/rate-limiter.mjs and run public tests", role: "builder", priority: 5, complexity: 4, risk: 4, dependencies: ["survey"], required: true },
    { id: "verify", title: "Independently verify code, public tests, security, scope, and every TASK.md requirement", role: "guard", priority: 5, complexity: 3, risk: 5, dependencies: ["build"], required: true }
  ]
};
await writeJson(path.join(hiveDir, "mission.json"), mission);
const plan = createPlan(mission, new Date());
await writeJson(path.join(hiveDir, "plan.json"), plan);
if (hiveProfile === "compact") {
  await writeFile(path.join(hiveDir, "survey.md"), "# Swarm admission\n\nScout omitted: TASK.md already provides bounded requirements and acceptance tests.\n", "utf8");
}
for (const [name, contents] of compileAllPayloads(plan, { target: "codex" })) {
  await writeFile(path.join(hiveDir, "payloads", name), contents, "utf8");
}

const provenance = {
  schemaVersion: 1,
  createdAt: new Date().toISOString(),
  runRoot,
  model: "gpt-5.5",
  reasoningEffort: "medium",
  host: "codex-cli 0.130.0",
  repositories: {
    caveman: repoInfo(cavemanRepo),
    ralphLoop: repoInfo(ralphRepo),
    loopEngineering: repoInfo(loopRepo),
    agentHive: { path: repositoryRoot, version: "0.3.0", profile: hiveProfile }
  }
};
await writeJson(path.join(runRoot, "provenance.json"), provenance);
console.log(runRoot);

function repoInfo(directory) {
  const commit = spawnSync("git", ["rev-parse", "HEAD"], { cwd: directory, encoding: "utf8", windowsHide: true });
  return { path: directory, commit: commit.stdout.trim() || "unknown" };
}

async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
