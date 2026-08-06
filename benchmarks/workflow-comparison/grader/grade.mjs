import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { runHiddenCases } from "./hidden-cases.mjs";

const target = path.resolve(process.argv[2] || "");
if (!process.argv[2]) throw new Error("Usage: node grade.mjs <arm-directory>");

const publicRun = spawnSync(process.execPath, ["--test", "./checks/public-cases.mjs"], {
  cwd: target,
  encoding: "utf8",
  windowsHide: true
});

let hidden;
try {
  hidden = await runHiddenCases(target);
} catch (error) {
  hidden = [{ name: "implementation loads", category: "functional", passed: false, error: error.message }];
}

const source = await readFile(path.join(target, "src", "rate-limiter.mjs"), "utf8").catch(() => "");
const packageJson = JSON.parse(await readFile(path.join(target, "package.json"), "utf8"));
const functional = hidden.filter((item) => item.category === "functional");
const security = hidden.filter((item) => item.category === "security");
const publicScore = publicRun.status === 0 ? 5 : 0;
const functionalScore = functional.length ? 20 * functional.filter((item) => item.passed).length / functional.length : 0;
const securityScore = security.length ? 10 * security.filter((item) => item.passed).length / security.length : 0;
const scopeChecks = {
  dependencyFree: Object.keys(packageJson.dependencies || {}).length === 0,
  usesMap: /new\s+Map\s*\(/.test(source),
  noTimers: !/setInterval|setTimeout/.test(source),
  boundedSize: /maxKeys/.test(source),
  readable: source.split(/\r?\n/).length <= 180 && source.length >= 200
};
const scopeScore = Object.values(scopeChecks).filter(Boolean).length;
const artifactScore = Math.round((publicScore + functionalScore + securityScore + scopeScore) * 100) / 100;

console.log(JSON.stringify({
  target,
  artifactScore,
  maxArtifactScore: 40,
  public: { passed: publicRun.status === 0, score: publicScore, output: `${publicRun.stdout}\n${publicRun.stderr}`.trim() },
  hidden,
  scores: {
    hiddenFunctional: Math.round(functionalScore * 100) / 100,
    hiddenSecurity: Math.round(securityScore * 100) / 100,
    scope: scopeScore
  },
  scopeChecks,
  sourceLines: source.split(/\r?\n/).length
}, null, 2));
