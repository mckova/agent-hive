import { spawnSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const runRoot = path.resolve(process.argv[2] || "");
if (!process.argv[2]) throw new Error("Usage: node grade-all.mjs <run-root>");
const grader = path.join(path.dirname(fileURLToPath(import.meta.url)), "grade.mjs");
const arms = ["normal", "caveman", "ralph", "loop-engineering", "agent-hive"];
const grades = [];

for (const arm of arms) {
  const result = spawnSync(process.execPath, [grader, path.join(runRoot, arm)], {
    encoding: "utf8",
    windowsHide: true
  });
  if (result.status !== 0) {
    grades.push({ arm, artifactScore: 0, graderError: result.stderr || `exit ${result.status}` });
    continue;
  }
  grades.push({ arm, ...JSON.parse(result.stdout) });
}

const report = { schemaVersion: 1, generatedAt: new Date().toISOString(), runRoot, grades };
await writeFile(path.join(runRoot, "grades.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.table(grades.map((grade) => ({
  arm: grade.arm,
  artifact: `${grade.artifactScore || 0}/40`,
  public: grade.public?.passed || false,
  hiddenPassed: grade.hidden?.filter((item) => item.passed).length || 0,
  hiddenTotal: grade.hidden?.length || 0,
  security: grade.scores?.hiddenSecurity || 0,
  scope: grade.scores?.scope || 0,
  sourceLines: grade.sourceLines || 0
})));
