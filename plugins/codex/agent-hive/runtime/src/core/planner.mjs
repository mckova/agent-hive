import { buildWaves, normalizedMission } from "./mission.mjs";

const TIER_RANK = { economy: 1, balanced: 2, frontier: 3 };

export function createPlan(rawMission, now = new Date()) {
  const mission = normalizedMission(rawMission);
  const reserve = Math.floor(mission.budget.total * mission.budget.reservePercent / 100);
  const distributable = mission.budget.total - reserve;
  const allocations = allocate(distributable, mission.cells);
  const floorRank = TIER_RANK[mission.policy.qualityFloor] ?? TIER_RANK.balanced;

  const cells = mission.cells.map((candidate) => {
    const score = taskScore(candidate);
    return {
      ...candidate,
      modelTier: tierFor(score, floorRank),
      allocation: allocations.get(candidate.id),
      status: "pending",
      factors: {
        score: round(score),
        weight: round(taskWeight(candidate)),
        required: candidate.required
      }
    };
  });

  return {
    schemaVersion: 1,
    revision: 1,
    generatedAt: now.toISOString(),
    mission: mission.mission,
    policy: mission.policy,
    guardrails: mission.guardrails,
    models: mission.models,
    budget: {
      unit: mission.budget.unit,
      total: mission.budget.total,
      reserve,
      allocated: distributable,
      reservePercent: mission.budget.reservePercent,
      reserveReleased: false
    },
    waves: buildWaves(cells, mission.policy.maxWorkers),
    cells
  };
}

export function taskWeight(candidate) {
  const requiredMultiplier = candidate.required ? 1.25 : 0.7;
  return requiredMultiplier * (
    candidate.priority * 0.45 +
    candidate.complexity * 0.35 +
    candidate.risk * 0.2
  );
}

export function taskScore(candidate) {
  return candidate.complexity * 0.45 + candidate.risk * 0.4 + candidate.priority * 0.15;
}

function tierFor(score, floorRank) {
  const scoreRank = score >= 4 ? 3 : score >= 2.75 ? 2 : 1;
  const rank = Math.max(scoreRank, floorRank);
  return Object.keys(TIER_RANK).find((key) => TIER_RANK[key] === rank);
}

export function allocate(total, cells) {
  const weights = cells.map((candidate) => ({ id: candidate.id, weight: taskWeight(candidate) }));
  const weightTotal = weights.reduce((sum, item) => sum + item.weight, 0);
  const rows = weights.map((item) => {
    const exact = total * item.weight / weightTotal;
    return { ...item, exact, value: Math.floor(exact), fraction: exact - Math.floor(exact) };
  });
  let remainder = total - rows.reduce((sum, row) => sum + row.value, 0);
  rows.sort((a, b) => b.fraction - a.fraction || a.id.localeCompare(b.id));
  for (let index = 0; index < remainder; index += 1) {
    rows[index % rows.length].value += 1;
  }
  return new Map(rows.map((row) => [row.id, row.value]));
}

export function explainCell(plan, id) {
  const cell = plan.cells.find((candidate) => candidate.id === id);
  if (!cell) throw new Error(`Unknown cell: ${id}`);
  const share = plan.budget.allocated ? cell.allocation / plan.budget.allocated * 100 : 0;
  return [
    `${cell.id}: ${cell.title}`,
    `role=${cell.role} tier=${cell.modelTier} allocation=${cell.allocation} ${plan.budget.unit}`,
    `priority=${cell.priority}/5 complexity=${cell.complexity}/5 risk=${cell.risk}/5 required=${cell.required}`,
    `weight=${cell.factors.weight} score=${cell.factors.score} share=${share.toFixed(1)}%`,
    `dependencies=${cell.dependencies.length ? cell.dependencies.join(",") : "none"}`
  ].join("\n");
}

function round(value) {
  return Math.round(value * 100) / 100;
}
