# Changelog

## Unreleased

## 0.4.1 - 2026-10-21

- Reject malformed `cells` values instead of silently replacing them with the default graph.
- Require downstream, read-only guard coverage for mutating work; make the optional default keeper read-only.
- Stop dispatch when a failed or interrupted invocation has unresolved usage. Add explicit outcome/usage reconciliation before retry or resume.
- Require complete input/output token totals for token accounting; keep reasoning as a diagnostic subset instead of counting it twice. Aggregate provider-reported turns and reject incomplete telemetry.
- Preserve cumulative cell spending when rebalancing and write checkpoint files atomically.
- Pass bounded, untrusted dependency summaries to downstream workers and invalidate completed descendants when upstream ledger outcomes change, retaining their spend and attempts.
- Exclude TTL-expired memory from queries, while retaining decay as storage cleanup.
- Align README, architecture, limitations, plugin guidance, and playground wording with the implemented Alpha scope: sequential CLI execution, no model calls in dry-run, between-call budget checks, and a planning-only HF demo.
- Preserve historical benchmark data and dates without extending its claims to the current release.

Compatibility: incomplete telemetry and invalid verification graphs now stop execution rather than proceeding with assumed usage or unchecked mutating work. Inspect interrupted outcomes and confirm cumulative usage before using `reconcile`; it is not authorization to repeat an action.

## 0.4.0 - 2026-08-06

- Migrated the CLI, deterministic core, provider drivers, tests, benchmarks, and bundled plugin runtimes from JavaScript to Python 3.11+.
- Added a standard-library-only Python package and `hive` console entry point while retaining optional `tiktoken` support for exact OpenAI text counts.
- Expanded CI across Python 3.11, 3.12, and 3.13 on Windows and Ubuntu.

## 0.3.0 - 2026-08-05

- Added `hive run` for checkpointed, resumable execution through local Codex and Claude Code CLIs.
- Added safe process drivers, a deterministic mock driver, timeout and output bounds, structured worker returns, retry caps, and explicit resume.
- Rechecks global and per-cell budgets between calls and stops when required usage telemetry is unavailable.
- Gate every declared cell action and path before dispatch; Claude permission bypass is refused.
- Require a guard cell and verifiable evidence before autonomous completion.
- Pin resumable runs to their original provider target and workspace.
- Align Claude host-native execution with economy, balanced, and frontier tier routing through six scoped workers.
- Added persisted run state, schema, audit events, payloads, and integration tests.
- Moved the colony-memory and 50–100 token research into the independent sibling project Agent Nest.
- Removed Micro Nest code and historical Micro results from the Hive oracle after verifying byte-identical copies in Agent Nest.
- Kept scoped memory, hooks, and guardrails as an independent Agent Hive implementation because they also improve the orchestration product.

## 0.2.0 - 2026-08-05

- Added deterministic path, network, approval, and attempt guardrails to Mission Genome and HIVE/1.
- Added scoped persistent memory with trust, visibility, sensitivity, TTL, decay, and verified reinforcement.
- Added per-cell token categories, model calls, latency, cost, alerts, and redacted JSONL audit events.
- Added a reproducible five-arm workflow comparison with hidden functional and security tests.
- Documented the host/runtime trust boundary and service-deployment security requirements.

## 0.1.0 - 2026-08-05

- Added deterministic Mission Genome planning, dependency waves, role and tier assignment.
- Added protected reserve, usage ledger, budget gates, and explicit rebalancing.
- Added lossless multilingual prompt variants with heuristic, OpenAI, and Anthropic counters.
- Added shared `HIVE/1` runtime and native Codex and Claude Code adapters.
- Added schemas, multilingual examples, benchmarks, tests, CI, and Claude marketplace metadata.
