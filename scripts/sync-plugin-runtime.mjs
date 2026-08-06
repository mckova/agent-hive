import { cp, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const targets = [
  path.join(root, "plugins", "codex", "agent-hive", "runtime"),
  path.join(root, "plugins", "claude-code", "agent-hive", "runtime")
];

for (const target of targets) {
  await mkdir(target, { recursive: true });
  await cp(path.join(root, "src"), path.join(target, "src"), { recursive: true, force: true });
  await cp(path.join(root, "bin"), path.join(target, "bin"), { recursive: true, force: true });
  await writeFile(path.join(target, "package.json"), "{\n  \"type\": \"module\"\n}\n", "utf8");
}

console.log(`Synced runtime to ${targets.length} plugins.`);
