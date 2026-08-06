import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { validateMission } from "../src/core/mission.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const jsonFiles = [
  ".claude-plugin/marketplace.json",
  "plugins/codex/agent-hive/.codex-plugin/plugin.json",
  "plugins/claude-code/agent-hive/.claude-plugin/plugin.json",
  "schemas/mission.schema.json",
  "schemas/run.schema.json",
  "schemas/usage.schema.json",
  "examples/missions/japanese-release.json",
  "examples/missions/arabic-api.json",
  "examples/missions/french-gated-deploy.json",
  "examples/missions/spanish-migration.json"
];

for (const relative of jsonFiles) {
  JSON.parse(await readFile(path.join(root, relative), "utf8"));
}

const packageJson = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
const marketplace = JSON.parse(await readFile(path.join(root, ".claude-plugin", "marketplace.json"), "utf8"));
const codexManifest = JSON.parse(await readFile(path.join(root, "plugins", "codex", "agent-hive", ".codex-plugin", "plugin.json"), "utf8"));
const claudeManifest = JSON.parse(await readFile(path.join(root, "plugins", "claude-code", "agent-hive", ".claude-plugin", "plugin.json"), "utf8"));
assert.equal(codexManifest.version, packageJson.version, "Codex plugin version differs from package.json.");
assert.equal(claudeManifest.version, packageJson.version, "Claude plugin version differs from package.json.");
assert.equal(marketplace.plugins[0].version, packageJson.version, "Claude marketplace version differs from package.json.");

const requiredAttribution = "Agent Hive — Copyright (c) 2026 May Sidon — https://github.com/mckova/agent-hive";
assert.equal(packageJson.author, "May Sidon", "Package author differs from the copyright holder.");
assert.equal(packageJson.license, "SEE LICENSE IN LICENSE", "Custom license metadata must point to LICENSE.");
for (const relative of ["LICENSE", "NOTICE", "README.md"]) {
  const contents = await readFile(path.join(root, relative), "utf8");
  assert.ok(contents.includes(requiredAttribution), `${relative} is missing the required attribution.`);
}

for (const relative of jsonFiles.filter((file) => file.startsWith("examples/missions/"))) {
  const mission = JSON.parse(await readFile(path.join(root, relative), "utf8"));
  assert.deepEqual(validateMission(mission), [], `Invalid example mission: ${relative}`);
}

const skillFiles = [
  "plugins/codex/agent-hive/skills/run-agent-hive/SKILL.md",
  "plugins/claude-code/agent-hive/skills/run-agent-hive/SKILL.md"
];
for (const relative of skillFiles) {
  const contents = await readFile(path.join(root, relative), "utf8");
  assert.match(contents, /^---\r?\n/);
  assert.doesNotMatch(contents, /\[TODO:/);
}
const openAiMetadata = await readFile(path.join(root, "plugins", "codex", "agent-hive", "skills", "run-agent-hive", "agents", "openai.yaml"), "utf8");
assert.match(openAiMetadata, /\$run-agent-hive/, "Codex UI metadata must invoke $run-agent-hive.");

const claudeAgentModels = {
  "hive-read-economy.md": "haiku",
  "hive-read-balanced.md": "sonnet",
  "hive-read-frontier.md": "opus",
  "hive-write-economy.md": "haiku",
  "hive-write-balanced.md": "sonnet",
  "hive-write-frontier.md": "opus"
};
const claudeAgentsDir = path.join(root, "plugins", "claude-code", "agent-hive", "agents");
const claudeAgentFiles = (await readdir(claudeAgentsDir)).filter((file) => file.endsWith(".md")).sort();
assert.deepEqual(claudeAgentFiles, Object.keys(claudeAgentModels).sort(), "Claude tier workers differ from the expected read/write matrix.");
for (const [file, model] of Object.entries(claudeAgentModels)) {
  const contents = await readFile(path.join(claudeAgentsDir, file), "utf8");
  assert.match(contents, new RegExp(`^model: ${model}$`, "m"), `${file} does not use ${model}.`);
  if (file.startsWith("hive-read-")) assert.match(contents, /^disallowedTools: .*Write.*Edit$/m, `${file} must remain read-only.`);
}

const runtimeFiles = [
  "bin/hive.mjs",
  "src/cli.mjs",
  "src/core/mission.mjs",
  "src/core/planner.mjs",
  "src/core/prompt-compiler.mjs",
  "src/core/protocol.mjs",
  "src/core/runner.mjs",
  "src/core/token-counter.mjs",
  "src/core/usage.mjs",
  "src/core/audit.mjs",
  "src/core/control.mjs",
  "src/core/gate.mjs",
  "src/core/memory.mjs",
  "src/drivers/cli-drivers.mjs"
];
for (const relative of runtimeFiles) {
  const source = await readFile(path.join(root, relative), "utf8");
  for (const plugin of ["codex", "claude-code"]) {
    const bundled = await readFile(path.join(root, "plugins", plugin, "agent-hive", "runtime", relative), "utf8");
    assert.equal(bundled, source, `${plugin} runtime is stale: ${relative}`);
  }
}

for (const markdownPath of await markdownFiles(root)) {
  const contents = await readFile(markdownPath, "utf8");
  for (const match of contents.matchAll(/\]\(([^)]+)\)/g)) {
    const rawTarget = match[1].trim().replace(/^<|>$/g, "").split(/\s+[\"']/)[0];
    if (!rawTarget || rawTarget.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(rawTarget)) continue;
    const target = decodeURIComponent(rawTarget.split("#")[0]);
    if (!target) continue;
    const resolved = target.startsWith("/")
      ? path.join(root, target.slice(1))
      : path.resolve(path.dirname(markdownPath), target);
    try {
      await stat(resolved);
    } catch {
      assert.fail(`Broken local Markdown link in ${path.relative(root, markdownPath)}: ${rawTarget}`);
    }
  }
}

console.log("Repository structure is valid.");

async function markdownFiles(directory) {
  const skipped = new Set([".git", ".hive", "node_modules", "tmp"]);
  const found = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (skipped.has(entry.name)) continue;
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) found.push(...await markdownFiles(fullPath));
    else if (entry.isFile() && entry.name.endsWith(".md")) found.push(fullPath);
  }
  return found;
}
