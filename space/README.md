---
title: Agent Hive Playground
emoji: 🐝
colorFrom: yellow
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Preview agent plans for Codex and Claude Code.
---

# Agent Hive Playground

Agent Hive is an Alpha Python orchestration toolkit with Codex and Claude Code integrations. This Space previews its deterministic planner: a **Queen** mission contract, six role-specific cells, model tiers, budget allocations, and HIVE/1 prompt payloads.

## What the demo shows

Enter a goal in any language or edit the loaded example. The planner populates a fixed six-role template with that goal and its constraints:

1. **Mission contract** - goal, requirements, forbidden outcomes, and completion criteria.
2. **Role prompts** - proposed tasks, instructions, expected results, and model tiers.
3. **Dependency waves** - which cells are independent and which depend on earlier cells.
4. **HIVE/1 previews** - copyable worker payloads to review before execution.
5. **Budget and policy** - reserve, per-cell allocations, declared paths/actions, approval rules, and attempt limits.

| Hive role | Intended responsibility | Expected result in a real run |
|---|---|---|
| Scout | Map requirements and unknowns | Requirement and risk map |
| Forager | Gather relevant evidence | Cited project assets and references |
| Architect | Plan implementation | Route and acceptance criteria |
| Builder | Produce the requested artifact | Changes and focused checks |
| Guard | Review the implementation | Pass/fail evidence and blockers |
| Keeper | Summarize verified context | Compact reusable facts |

Scout and Forager share the first planned wave. A host-native workflow can dispatch independent cells concurrently; the terminal runner executes them sequentially. The demo does neither. In a real workflow, dependency artifacts must be persisted in the workspace or passed by the host.

## What happens when you press Decompose

The Python planner creates role prompts, assigns tiers using deterministic scores, allocates the budget excluding its reserve, orders dependency waves, and renders payloads. It does not inspect a repository, discover implementation paths, call a planning model, or execute a worker. Review and specialize the tasks and writable paths before using them in a project. Small tasks can use an explicitly defined builder/guard pair in the full toolkit; the demo shows the six-role template.

This Static Space loads Pyodide from a CDN and runs the Python planner in your browser. It does not send prompts to a model, invoke Codex or Claude Code, execute project tools, persist prompts, or accept API keys. Input normalization trims surrounding whitespace; generated role text also normalizes whitespace.

Token estimates use an offline heuristic, not a provider tokenizer or bill. Allocations are planning values, not hard provider spend ceilings. Tier assignment does not establish model quality or savings. The displayed path/network/approval policy is a declaration for review, not an operating-system sandbox; real execution depends on the host's permissions.

The complete Python package, tests, security model, benchmarks, and installation adapters are maintained in the canonical [Agent Hive GitHub repository](https://github.com/mckova/agent-hive).

## License

MIT License. Copyright (c) 2026 May Sidon | Agent Hive | https://github.com/mckova/agent-hive
