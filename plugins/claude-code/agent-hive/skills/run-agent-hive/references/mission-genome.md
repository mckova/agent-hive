# Mission Genome

Create `.hive/mission.json` with `mission`, `budget`, `policy`, and `cells`.

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
  "budget": { "unit": "tokens", "total": 100000, "reservePercent": 20 },
  "policy": { "maxWorkers": 3, "qualityFloor": "balanced" },
  "models": {
    "economy": { "codex": "allowed-model-id", "claude": "allowed-model-id" },
    "balanced": { "codex": "allowed-model-id", "claude": "allowed-model-id" },
    "frontier": { "codex": "allowed-model-id", "claude": "allowed-model-id" }
  },
  "cells": []
}
```

Budget unit is `tokens` or integer `usd-micros` (millionths of a US dollar). Autonomous USD enforcement requires driver-reported `costUsd`; never invent a conversion rate.

Cell fields: `id`, `title`, `role`, `priority`, `complexity`, `risk`, `dependencies`, `required`, and optional `instructions`, `actions`, and workspace-relative `paths`.

Valid roles: `scout`, `architect`, `forager`, `builder`, `guard`, `keeper`. Valid actions are `read`, `write`, `network`, `delete`, `push`, `deploy`, and `external-write`. A write under an allowlist must declare at least one path. Numeric factors range from 1 to 5. Leave `cells` empty for the general workflow.

`models` is optional. It maps abstract tiers to model IDs the user has explicitly allowed for each target. Omit a mapping to inherit the host model; never guess product names or cross a provider boundary.
