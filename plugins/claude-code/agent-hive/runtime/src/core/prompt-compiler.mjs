import { createHash } from "node:crypto";

export function missionFingerprint(mission) {
  const canonical = JSON.stringify({
    goal: mission.goal,
    sourceLanguage: mission.sourceLanguage,
    responseLanguage: mission.responseLanguage,
    must: mission.must,
    avoid: mission.avoid,
    doneWhen: mission.doneWhen
  });
  return createHash("sha256").update(canonical).digest("hex").slice(0, 16);
}

export function renderMissionVariants(mission) {
  const fingerprint = missionFingerprint(mission);
  const join = (items) => items?.length ? items.join(" | ") : "none";
  const source = [
    mission.goal,
    mission.must?.length ? `Must: ${mission.must.join("; ")}` : "",
    mission.avoid?.length ? `Avoid: ${mission.avoid.join("; ")}` : "",
    mission.doneWhen?.length ? `Done when: ${mission.doneWhen.join("; ")}` : ""
  ].filter(Boolean).join("\n");
  const hive = [
    `G:${mission.goal}`,
    `M:${join(mission.must)}`,
    `A:${join(mission.avoid)}`,
    `D:${join(mission.doneWhen)}`,
    `L:${mission.sourceLanguage}>${mission.responseLanguage}`,
    `F:${fingerprint}`
  ].join("\n");
  const json = JSON.stringify({
    g: mission.goal,
    m: mission.must,
    a: mission.avoid,
    d: mission.doneWhen,
    l: [mission.sourceLanguage, mission.responseLanguage],
    f: fingerprint
  });

  return [
    variant("source", source, mission, fingerprint),
    variant("hive-ir", hive, mission, fingerprint),
    variant("compact-json", json, mission, fingerprint)
  ];
}

function variant(name, text, mission, fingerprint) {
  const decoded = name === "compact-json" ? JSON.parse(text) : null;
  const preserved = name === "compact-json"
    ? literals(mission).every((value) => [decoded.g, ...decoded.m, ...decoded.a, ...decoded.d].includes(value))
    : literals(mission).every((value) => text.includes(value));
  return {
    name,
    text,
    fingerprint,
    chars: [...text].length,
    bytes: Buffer.byteLength(text, "utf8"),
    literalsPreserved: preserved
  };
}

function literals(mission) {
  return [mission.goal, ...(mission.must ?? []), ...(mission.avoid ?? []), ...(mission.doneWhen ?? [])]
    .filter(Boolean);
}

export async function compareMissionVariants(mission, counter) {
  const variants = renderMissionVariants(mission);
  const rows = [];
  for (const candidate of variants) {
    const counted = await counter(candidate.text);
    rows.push({
      ...candidate,
      tokens: counted.tokens,
      precision: counted.precision,
      counter: counted.counter,
      note: counted.note || ""
    });
  }
  rows.sort((a, b) => Number(b.literalsPreserved) - Number(a.literalsPreserved) || a.tokens - b.tokens);
  return rows;
}
