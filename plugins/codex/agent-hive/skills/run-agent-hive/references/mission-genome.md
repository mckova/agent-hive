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

Use `tokens` for provider-reported input/output/reasoning usage, or `usd-micros` for integer millionths of a US dollar. Autonomous USD enforcement requires the driver to report `costUsd`; never invent a conversion rate.

Cell fields:

```json
{
  "id": "kebab-case",
  "title": "Bounded outcome",
  "role": "scout",
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

`models` is optional. It maps abstract tiers to model IDs the user has explicitly allowed for each target. Omit a mapping to inherit the host model; never guess product names or cross a provider boundary.

Leave `cells` empty for the general survey → design → build → verify → distill workflow. Define cells when the project has known deliverables or parallel workstreams.
