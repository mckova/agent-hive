# Architecture

```text
Goal in any language
        |
        v
Mission Genome -- source-language goal, constraints, declared policy
        |
        v
Prompt Compiler -- counted variants and literal-preservation checks
        |
        v
Deterministic Planner -- explicit cells or six-role template, dependencies, waves
        |
        v
Energy Governor -- allocation, reserve, rebalancing
        |
        v
Guardrail Gate -- paths, network, approvals, attempt caps
        |
        v
Sequential Runner -- checkpoints, retry caps, between-call budget checks
        |
        v
CLI Driver -- local Codex/Claude process or offline mock
        |
        v
HIVE/1 Payloads -- bounded context and explicit trust boundary
        |
        v
Usage + Run State + Audit + optional Scoped Memory
```

## Design rules

1. Keep the source language. Current normalization trims surrounding whitespace; generated role text also collapses whitespace. Arbitrary input is not preserved byte-for-byte.
2. Keep accounting deterministic. An LLM may assess complexity, but code owns ledger totals.
3. Allocate for task success, not the shortest prompt.
4. Give workers a bounded cell prompt, constraints, and return contract. Terminal handoff includes bounded untrusted dependency summaries and artifact references, not artifact file contents.
5. Exclude the reserve from routine allocations; release it only through an explicit rebalance decision.
6. Keep model names in adapter configuration; the core uses economy, balanced, and frontier tiers.
7. Label count precision. Heuristics, tokenizer counts, and provider estimates are different evidence.
8. Check reported spending before and after each call. A provider call can overrun its allocation before the runner can stop.
9. Treat repository, web, tool, and recalled-memory content as data unless it is independently promoted to trusted memory.
10. Keep prompts, credentials, and memory content out of audit events.
11. For atomic, specified tasks, the skills recommend explicitly defining `builder -> guard`; the runtime does not automatically shrink the default graph.
12. Require downstream guard coverage for mutating work and reported evidence for completed cells. Run cited checks independently when assurance matters; a worker's evidence string is not an executed test.

The plugin skills describe a separate host-native workflow: the host dispatches ready cells, passes relevant dependency artifacts, gates actions, and records actual usage. Claude host-native workers map economy/balanced/frontier to Haiku/Sonnet/Opus aliases. Codex model selection follows the host's available, user-authorized models. Terminal mode resolves model IDs from Mission Genome or an explicit `--model`; without either, the provider CLI uses its default. The deterministic core is not tied to a model generation.

## Worker roles

- `scout`: map the territory without changing it.
- `architect`: choose a route and expose dependencies.
- `forager`: gather permitted external or repository evidence.
- `builder`: produce the requested artifact.
- `guard`: test correctness, safety, and mission compliance.
- `keeper`: return verified reusable context; the default keeper is read-only.

## Allocation and routing

Each cell receives a weight derived from priority, complexity, risk, and whether it is required. The distributable budget is the total minus protected reserve. Integer rounding is deterministic and preserves the exact total. Model tiers use the same factors, while adapters map tiers to models the user has authorized.

## Lifecycle

Manual/host-native: `plan -> compare -> compile -> gate -> next -> dispatch -> record -> status -> rebalance`

Autonomous terminal: `run -> checkpoint after every transition -> resume if explicitly requested`

`next` returns at most `policy.maxWorkers` pending cells whose dependencies are done. Planning waves can contain independent cells; the terminal `run` command still executes them sequentially. Only host-managed dispatch can run independent, disjoint cells concurrently.

`gate` validates declared actions and paths before dispatch; provider permissions enforce actual tool/process boundaries. `record` maintains the usage ledger. Changing an upstream outcome invalidates completed descendants while retaining spend and attempts. Terminal dependency handoff is bounded JSON, marked untrusted and explicitly truncated when needed; it contains IDs, status, artifact references, evidence, and reusable context, and does not read files.

The runner records local checkpoints, blocks unresolved accounting, and requires inspected outcome/usage reconciliation before redispatching an interrupted invocation. Checkpoint writes are atomic per file, not a multi-file transaction or concurrent-run guarantee. Neither a checkpoint nor a role prompt replaces artifact review, provider billing, or an operating-system sandbox. See [limitations](limitations.md) for the recovery and accounting contract.
