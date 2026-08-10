---
title: Agent Hive Playground
emoji: 🐝
colorFrom: yellow
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Guard agent workflows for Codex and Claude Code.
---

# Agent Hive Playground

Agent Hive turns one central prompt into a controlled team of specialized coding agents. The **Queen** keeps the original goal and constraints immutable; every other bee receives a smaller, role-specific worker contract.

## What the live demo proves

Enter a goal in any language—or use the result that loads automatically. The Space shows the complete transformation:

1. **Queen contract** — the exact goal, must-have constraints, forbidden outcomes, and verifiable completion criteria.
2. **Worker decomposition** — a concrete assignment, instructions, required return value, dependency wave, model tier, and token ceiling for every bee.
3. **Execution route** — which cells can run in parallel and which must wait for verified upstream evidence.
4. **Copy-ready HIVE/1 contracts** — the exact compact payload that Codex, Claude Code, or another worker receives.
5. **Budget and guardrails** — protected reserve, per-cell allocations, denied network/path actions, human gates, and retry limits.

| Hive role | What it receives from the queen | What it must return |
|---|---|---|
| Scout | Mission and hard constraints | Requirement, unknown, and risk map |
| Forager | Mission and search boundary | Cited evidence pack with relevant project assets |
| Architect | Scout map + Forager evidence | Dependency-aware implementation route and acceptance matrix |
| Builder | Approved route | Focused artifact/change set with checks and actual usage |
| Guard | Built result + Queen criteria | Independent pass/fail evidence matrix |
| Keeper | Verified run only | Compact reusable context without secrets or stale claims |

Scout and Forager can work in parallel. Architect waits for both; Builder waits for Architect; Guard can block completion; Keeper stores only verified reusable context.

## What happens when you press Decompose

The Python planner derives mission-specific worker tasks from your prompt, assigns capability tiers by complexity and risk, distributes only the spendable token budget, protects the reserve, orders dependency waves, and generates the worker contracts. It does **not** pretend that the tasks have already been executed.

This free Static Space runs the deterministic Python planner locally in the browser through Pyodide. JavaScript is limited to loading Python and connecting the browser form to its result. The Space does not call models, execute tools, invoke Codex or Claude Code, retain prompts, or accept API keys.

The complete Python package, tests, security model, benchmarks, and installation adapters are maintained in the canonical [Agent Hive GitHub repository](https://github.com/mckova/agent-hive).

## License

MIT License. Copyright (c) 2026 May Sidon | Agent Hive | https://github.com/mckova/agent-hive
