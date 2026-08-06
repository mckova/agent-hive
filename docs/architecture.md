# Architecture

```text
Goal in any language
        |
        v
Mission Genome -- immutable intent, constraints, guardrails
        |
        v
Lossless Prompt Compiler -- measured variants, original literals preserved
        |
        v
Honeycomb Planner -- cells, dependencies, work waves
        |
        v
Energy Governor -- allocation, reserve, rebalancing
        |
        v
Guardrail Gate -- paths, network, approvals, attempt caps
        |
        v
Resumable Runner -- checkpoints, retry caps, budget stops
        |
        v
Platform Driver -- host-native workers or local Codex/Claude CLI
        |
        v
HIVE/1 Payloads -- bounded context and explicit trust boundary
        |
        v
Usage + Run State + Audit + Scoped Memory
```

## Design rules

1. Preserve the source language. Translation is an optional renderer, not destructive normalization.
2. Keep accounting deterministic. An LLM may assess complexity, but code owns ledger totals.
3. Allocate for task success, not the shortest prompt.
4. Give each worker only its cell, dependencies, constraints, and return contract.
5. Protect verification reserve from routine implementation spend.
6. Keep model names in adapter configuration; the core uses economy, balanced, and frontier tiers.
7. Label count precision. Heuristics, tokenizer counts, and provider estimates are different evidence.
8. Stop dispatch at the spendable budget boundary.
9. Treat repository, web, tool, and recalled-memory content as data unless it is independently promoted to trusted memory.
10. Keep prompts, credentials, and memory content out of audit events.
11. Admit work to a swarm only when discovery, coordination, or independent verification can repay another model turn; an atomic task uses `builder -> guard`.
12. Never accept autonomous completion without a required guard and verifiable evidence from every completed cell.

Claude host-native mode ships read-only and mutating workers for each tier: economy maps to Haiku, balanced to Sonnet, and frontier to Opus. Codex host-native mode selects the user-authorized model when spawning a cell. Autonomous mode resolves exact model IDs from the Mission Genome for either provider.

## Worker roles

- `scout`: map the territory without changing it.
- `architect`: choose a route and expose dependencies.
- `forager`: gather external or repository evidence.
- `builder`: produce the requested artifact.
- `guard`: test correctness, safety, and mission compliance.
- `keeper`: distill only verified reusable context.

## Allocation and routing

Each cell receives a weight derived from priority, complexity, risk, and whether it is required. The distributable budget is the total minus protected reserve. Integer rounding is deterministic and preserves the exact total. Model tiers use the same factors, while adapters map tiers to models the user has authorized.

## Lifecycle

Manual/host-native: `plan -> compare -> compile -> gate -> next -> dispatch -> record -> status -> rebalance`

Autonomous terminal: `run -> checkpoint after every transition -> resume if explicitly requested`

`next` returns at most `policy.maxWorkers` pending cells whose dependencies are done. `gate` checks proposed actions before dispatch. `record` owns the usage ledger and host-reported metrics. `run` uses the same functions, executes ready cells sequentially in v0.3, and persists `.hive/run.json` plus `.hive/usage.json`. The governor, not an agent's completion prose, determines whether more work may start.
