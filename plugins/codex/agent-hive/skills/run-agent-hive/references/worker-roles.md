# Worker roles

## Scout

Read-only. Locate the smallest relevant code and evidence surface. Return paths, symbols, unknowns, and a compact map. Use an economy model unless ambiguity is high.

## Architect

Read-only. Convert the mission and scout evidence into a dependency-aware route. Identify risks and verification gates. Use balanced or frontier according to the assigned tier.

## Forager

Read-only. Gather bounded external documentation, logs, or repository evidence. Return only facts needed by downstream cells with sources.

## Builder

Own an explicit, non-overlapping artifact set. Implement the cell, run focused checks, and report changed files plus evidence. Use balanced by default; use frontier only when assigned.

## Guard

Read-only unless the parent explicitly authorizes fixes. Verify mission constraints, regression risk, tests, security, and missing evidence. Never review from the builder's summary alone.

## Keeper

Read-only. Distill reusable decisions and evidence. Remove transient logs, duplication, abandoned hypotheses, and content already encoded in files.

## Spawn discipline

- One worker, one cell.
- Keep spawn prompts below 150 words plus the HIVE/1 payload.
- Do not spawn a worker for a search or edit the parent can finish with a few direct tool calls.
- Do not run dependent cells concurrently.
- Preserve a single writer for each file or artifact.
