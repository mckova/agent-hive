import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { normalizedMission } from "../src/core/mission.mjs";
import { compareMissionVariants } from "../src/core/prompt-compiler.mjs";
import { heuristicCount } from "../src/core/token-counter.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const samples = ["japanese-release.json", "arabic-api.json", "spanish-migration.json"];
const rows = [];

for (const sample of samples) {
  const raw = JSON.parse(await readFile(path.join(root, "examples", "missions", sample), "utf8"));
  const mission = normalizedMission(raw).mission;
  const compared = await compareMissionVariants(mission, async (text) => heuristicCount(text));
  const source = compared.find((row) => row.name === "source");
  const best = compared[0];
  rows.push({
    sample,
    language: mission.sourceLanguage,
    sourceEstimate: source.tokens,
    bestVariant: best.name,
    bestEstimate: best.tokens,
    estimatedChange: `${Math.round((best.tokens - source.tokens) / source.tokens * 100)}%`,
    literalsPreserved: best.literalsPreserved
  });
}

console.table(rows);
console.log("All counts use the utf8-bytes/4 planning heuristic. They are not model tokenizer benchmarks.");
