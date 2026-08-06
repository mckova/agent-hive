const ROLES = new Set(["scout", "architect", "forager", "builder", "guard", "keeper"]);
const HUMAN_GATE_ACTIONS = ["delete", "push", "deploy", "external-write"];
const ACTIONS = new Set(["read", "write", "network", "delete", "push", "deploy", "external-write"]);

export function defaultMission() {
  return {
    schemaVersion: 1,
    mission: {
      goal: "Describe the outcome in any language.",
      sourceLanguage: "auto",
      responseLanguage: "same-as-user",
      must: [],
      avoid: [],
      doneWhen: []
    },
    budget: {
      unit: "tokens",
      total: 100000,
      reservePercent: 20
    },
    policy: {
      maxWorkers: 3,
      qualityFloor: "balanced"
    },
    guardrails: defaultGuardrails(),
    models: {},
    cells: defaultCells()
  };
}

export function defaultGuardrails() {
  return {
    allowedPathPrefixes: [],
    deniedPathPrefixes: [".env", ".git", "secrets", "credentials"],
    allowNetwork: false,
    humanApprovalActions: [...HUMAN_GATE_ACTIONS],
    maxAttemptsPerCell: 2,
    trustedInstructionSources: ["mission", "cell"]
  };
}

export function defaultCells() {
  return [
    cell("survey", "Map the territory", "scout", 5, 2, 2, [], true),
    cell("design", "Design the route", "architect", 5, 3, 3, ["survey"], true),
    cell("build", "Produce the required outcome", "builder", 5, 4, 3, ["design"], true),
    cell("verify", "Verify against the mission", "guard", 5, 3, 5, ["build"], true),
    cell("distill", "Distill reusable hive memory", "keeper", 3, 1, 1, ["verify"], false)
  ];
}

function cell(id, title, role, priority, complexity, risk, dependencies, required) {
  return { id, title, role, priority, complexity, risk, dependencies, required };
}

export function validateMission(input) {
  const errors = [];
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return ["Mission must be a JSON object."];
  }

  if (!input.mission || typeof input.mission.goal !== "string" || !input.mission.goal.trim()) {
    errors.push("mission.goal must be a non-empty string.");
  }

  const total = input.budget?.total;
  if (!Number.isInteger(total) || total <= 0) {
    errors.push("budget.total must be a positive integer.");
  }
  if (input.budget?.unit !== undefined && !["tokens", "usd-micros"].includes(input.budget.unit)) {
    errors.push("budget.unit must be tokens or usd-micros.");
  }

  const reserve = input.budget?.reservePercent;
  if (typeof reserve !== "number" || reserve < 0 || reserve >= 100) {
    errors.push("budget.reservePercent must be at least 0 and below 100.");
  }

  const maxWorkers = input.policy?.maxWorkers;
  if (!Number.isInteger(maxWorkers) || maxWorkers < 1 || maxWorkers > 32) {
    errors.push("policy.maxWorkers must be an integer from 1 to 32.");
  }

  if (input.policy?.qualityFloor !== undefined && !["economy", "balanced", "frontier"].includes(input.policy.qualityFloor)) {
    errors.push("policy.qualityFloor must be economy, balanced, or frontier.");
  }

  if (input.guardrails !== undefined) {
    if (!input.guardrails || typeof input.guardrails !== "object" || Array.isArray(input.guardrails)) {
      errors.push("guardrails must be an object.");
    } else {
      for (const field of ["allowedPathPrefixes", "deniedPathPrefixes", "humanApprovalActions", "trustedInstructionSources"]) {
        if (input.guardrails[field] !== undefined && !isStringList(input.guardrails[field])) {
          errors.push(`guardrails.${field} must be an array of strings.`);
        }
      }
      if (input.guardrails.allowNetwork !== undefined && typeof input.guardrails.allowNetwork !== "boolean") {
        errors.push("guardrails.allowNetwork must be a boolean.");
      }
      if (input.guardrails.maxAttemptsPerCell !== undefined
        && (!Number.isInteger(input.guardrails.maxAttemptsPerCell) || input.guardrails.maxAttemptsPerCell < 1 || input.guardrails.maxAttemptsPerCell > 20)) {
        errors.push("guardrails.maxAttemptsPerCell must be an integer from 1 to 20.");
      }
    }
  }

  for (const field of ["must", "avoid", "doneWhen"]) {
    if (input.mission?.[field] !== undefined && !isStringList(input.mission[field])) {
      errors.push(`mission.${field} must be an array of strings.`);
    }
  }

  for (const tier of ["economy", "balanced", "frontier"]) {
    const mapping = input.models?.[tier];
    if (mapping === undefined) continue;
    if (!mapping || typeof mapping !== "object" || Array.isArray(mapping)) {
      errors.push(`models.${tier} must be an object.`);
      continue;
    }
    for (const [target, model] of Object.entries(mapping)) {
      if (!target.trim() || typeof model !== "string" || !model.trim()) {
        errors.push(`models.${tier}.${target} must be a non-empty string.`);
      }
    }
  }

  const cells = input.cells?.length ? input.cells : defaultCells();
  const ids = new Set();
  for (const [index, candidate] of cells.entries()) {
    const prefix = `cells[${index}]`;
    if (!candidate || typeof candidate !== "object") {
      errors.push(`${prefix} must be an object.`);
      continue;
    }
    if (typeof candidate.id !== "string" || !/^[a-z0-9][a-z0-9-]*$/.test(candidate.id)) {
      errors.push(`${prefix}.id must be lower-case kebab-case.`);
    } else if (ids.has(candidate.id)) {
      errors.push(`${prefix}.id duplicates ${candidate.id}.`);
    } else {
      ids.add(candidate.id);
    }
    if (typeof candidate.title !== "string" || !candidate.title.trim()) {
      errors.push(`${prefix}.title must be a non-empty string.`);
    }
    if (!ROLES.has(candidate.role)) {
      errors.push(`${prefix}.role must be one of ${[...ROLES].join(", ")}.`);
    }
    for (const field of ["priority", "complexity", "risk"]) {
      if (!Number.isInteger(candidate[field]) || candidate[field] < 1 || candidate[field] > 5) {
        errors.push(`${prefix}.${field} must be an integer from 1 to 5.`);
      }
    }
    if (candidate.dependencies && !Array.isArray(candidate.dependencies)) {
      errors.push(`${prefix}.dependencies must be an array.`);
    }
    if (candidate.instructions !== undefined && !isStringList(candidate.instructions)) {
      errors.push(`${prefix}.instructions must be an array of strings.`);
    }
    if (candidate.paths !== undefined && !isStringList(candidate.paths)) {
      errors.push(`${prefix}.paths must be an array of workspace-relative strings.`);
    }
    if (candidate.actions !== undefined && (!isStringList(candidate.actions) || candidate.actions.some((action) => !ACTIONS.has(action)))) {
      errors.push(`${prefix}.actions must contain only ${[...ACTIONS].join(", ")}.`);
    }
  }

  for (const candidate of cells) {
    for (const dependency of candidate.dependencies ?? []) {
      if (!ids.has(dependency)) {
        errors.push(`Cell ${candidate.id} depends on missing cell ${dependency}.`);
      }
      if (dependency === candidate.id) {
        errors.push(`Cell ${candidate.id} cannot depend on itself.`);
      }
    }
  }

  if (!errors.length) {
    try {
      buildWaves(cells, maxWorkers);
    } catch (error) {
      errors.push(error.message);
    }
  }

  return errors;
}

export function normalizedMission(input) {
  const errors = validateMission(input);
  if (errors.length) {
    throw new Error(errors.join("\n"));
  }

  return {
    schemaVersion: 1,
    mission: {
      goal: input.mission.goal.trim(),
      sourceLanguage: input.mission.sourceLanguage || "auto",
      responseLanguage: input.mission.responseLanguage || "same-as-user",
      must: cleanStrings(input.mission.must),
      avoid: cleanStrings(input.mission.avoid),
      doneWhen: cleanStrings(input.mission.doneWhen)
    },
    budget: {
      unit: input.budget.unit || "tokens",
      total: input.budget.total,
      reservePercent: input.budget.reservePercent
    },
    policy: {
      maxWorkers: input.policy.maxWorkers,
      qualityFloor: input.policy.qualityFloor || "balanced"
    },
    guardrails: normalizeGuardrails(input.guardrails),
    models: normalizeModels(input.models),
    cells: (input.cells?.length ? input.cells : defaultCells()).map((candidate) => ({
      id: candidate.id,
      title: candidate.title.trim(),
      role: candidate.role,
      priority: candidate.priority,
      complexity: candidate.complexity,
      risk: candidate.risk,
      dependencies: [...(candidate.dependencies ?? [])],
      required: candidate.required !== false,
      instructions: cleanStrings(candidate.instructions),
      actions: cleanStrings(candidate.actions),
      paths: cleanStrings(candidate.paths)
    }))
  };
}

function normalizeGuardrails(input) {
  const defaults = defaultGuardrails();
  return {
    allowedPathPrefixes: cleanStrings(input?.allowedPathPrefixes),
    deniedPathPrefixes: input?.deniedPathPrefixes === undefined
      ? defaults.deniedPathPrefixes
      : cleanStrings(input.deniedPathPrefixes),
    allowNetwork: input?.allowNetwork === true,
    humanApprovalActions: input?.humanApprovalActions === undefined
      ? defaults.humanApprovalActions
      : cleanStrings(input.humanApprovalActions),
    maxAttemptsPerCell: input?.maxAttemptsPerCell ?? defaults.maxAttemptsPerCell,
    trustedInstructionSources: input?.trustedInstructionSources === undefined
      ? defaults.trustedInstructionSources
      : cleanStrings(input.trustedInstructionSources)
  };
}

function normalizeModels(models) {
  const result = {};
  for (const tier of ["economy", "balanced", "frontier"]) {
    if (!models?.[tier]) continue;
    result[tier] = Object.fromEntries(
      Object.entries(models[tier]).map(([target, model]) => [target.trim(), model.trim()])
    );
  }
  return result;
}

function cleanStrings(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
}

function isStringList(value) {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

export function buildWaves(cells, maxWorkers) {
  const remaining = new Map(cells.map((candidate) => [candidate.id, candidate]));
  const complete = new Set();
  const waves = [];

  while (remaining.size) {
    const ready = [...remaining.values()]
      .filter((candidate) => (candidate.dependencies ?? []).every((id) => complete.has(id)))
      .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));

    if (!ready.length) {
      throw new Error("Cell dependencies contain a cycle.");
    }

    for (let offset = 0; offset < ready.length; offset += maxWorkers) {
      const wave = ready.slice(offset, offset + maxWorkers).map((candidate) => candidate.id);
      waves.push(wave);
      for (const id of wave) {
        remaining.delete(id);
        complete.add(id);
      }
    }
  }

  return waves;
}
