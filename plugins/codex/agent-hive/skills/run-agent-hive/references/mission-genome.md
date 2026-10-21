# Mission Genome

Create `.hive/mission.json` with this shape:

```json
{
  "schemaVersion": 1,
  "mission": {
    "goal": "Original goal in any language",
    "sourceLanguage": "auto",
    "responseLanguage": "same-as-user",
    "must": [],
    "avoid": [],
    "doneWhen": []
  },
  "budget": {
    "unit": "tokens",
    "total": 100000,
    "reservePercent": 20
  },
  "policy": {
    "maxWorkers": 3,
    "qualityFloor": "balanced"
  },
  "models": {
    "economy": { "codex": "allowed-model-id", "claude": "allowed-model-id" },
    "balanced": { "codex": "allowed-model-id", "claude": "allowed-model-id" },
    "frontier": { "codex": "allowed-model-id", "claude": "allowed-model-id" }
  },
  "cells": []
}
```

Use `tokens` for complete provider-reported input plus output totals (reasoning is a diagnostic subset), or `usd-micros` for integer millionths of a US dollar. Autonomous USD enforcement requires the driver to report `costUsd`; never invent a conversion rate.

Cell fields:

```json
{
  "id": "kebab-case",
  "title": "Bounded outcome",
  "role": "builder",
  "priority": 1,
  "complexity": 1,
  "risk": 1,
  "dependencies": [],
  "required": true,
  "instructions": [],
  "actions": ["write"],
  "paths": ["src"]
}
```

Valid roles: `scout`, `architect`, `forager`, `builder`, `guard`, `keeper`. Priority, complexity, and risk range from 1 to 5. Valid actions are `read`, `write`, `network`, `delete`, `push`, `deploy`, and `external-write`. Paths must be workspace-relative; a write under an allowlist must declare at least one path.

`models` is optional. It maps abstract tiers to model IDs the user has explicitly allowed for each target. Without a terminal mapping/override the provider CLI uses its default; host-native selection follows the host configuration; never guess product names or cross a provider boundary.


Empty or omitted `cells` selects `(survey, forage) -> design -> build -> verify -> optional distill`; malformed values are rejected. Small specified tasks can explicitly define `builder -> guard`. Writable cells need concrete workspace-relative paths when an allow-list is configured. Each write/delete/external-write cell requires a required downstream guard limited to read/network actions. The default keeper is read-only.
