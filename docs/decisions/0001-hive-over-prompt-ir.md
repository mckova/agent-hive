# ADR 0001: Make Prompt IR a component of the hive

Status: accepted

## Context

A prompt intermediate representation can reduce repeated structure and make prompts easier to measure. By itself, however, it does not decide which work is necessary, expose dependencies, select a capability tier, protect verification budget, or react to actual usage.

## Decision

Agent Hive treats lossless Prompt IR as one compiler stage inside a broader orchestration system:

`Mission Genome → prompt variants → cells → model tiers → budget gate → worker evidence → rebalance`

The source-language mission remains authoritative. Compacted representations are candidates, never destructive replacements, and token claims carry a precision label.

## Consequences

- The repository demonstrates an end-to-end workflow rather than a prompt-format trick.
- Compression can be improved independently without changing the planning and accounting protocol.
- The core remains useful even when the cheapest safe representation is the original text.
- Translation or semantic paraphrasing must arrive with an equivalence check; token savings alone cannot authorize changed meaning.
