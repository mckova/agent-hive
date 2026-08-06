# Security, guardrails, and observability

Agent Hive is a local orchestration CLI. Its threat model is a coding agent operating on a user-controlled workspace, not an internet-facing multi-user API.

## Trust boundary

Trusted instructions are limited to the Mission Genome, the compiled cell payload, platform policy, and an explicit human decision. Repository files, issue text, web pages, tool output, dependency metadata, and recalled memory are untrusted data. HIVE/1 states this boundary in every worker payload.

Memory is untrusted by default. `--trusted` is reserved for a user-approved fact or evidence independently verified by a guard. A memory can inform a decision; it cannot override mission constraints or platform permissions.

## Enforced in the deterministic runtime

| Control | Behavior |
| --- | --- |
| Workspace boundary | `hive gate` denies absolute paths and `..` traversal. |
| Path policy | Denied prefixes win; an optional allowlist narrows the writable surface. |
| Network policy | Denied by default and changed only in Mission Genome. |
| High-risk actions | Delete, push, deploy, and external writes require a human-gate decision by default. |
| Attempt breaker | The ledger rejects an attempt count above `maxAttemptsPerCell`; `status` alerts at the cap. |
| Token budget | `next` stops dispatch at the spendable boundary; reserve release is explicit. |
| Run budget | `hive run` rechecks global and per-cell spend before every call and refuses success without the telemetry required by the selected budget unit. |
| Resume binding | Run state pins the original target and absolute workspace; resume refuses an explicit target or workspace change. |
| Process launch | Provider drivers use argument arrays without a shell, bound output, enforce optional timeouts, and keep provider permission systems enabled. |
| Secret-safe telemetry | Recursive redaction removes prompts/content and common credentials while retaining numeric usage. |
| Memory leakage | Scope/namespace matching, role visibility, sensitivity ceiling, TTL/decay, and trusted-only recall. |

`--human-approved` is an assertion by the caller, not cryptographic proof. A production unattended wrapper should emit it only after a real host approval event.

## Delegated to Codex or Claude Code

Process isolation, filesystem enforcement, command approval, network sandboxing, and provider authentication remain host responsibilities. The skill requires workers to remain inside that sandbox and to run `hive gate` before dispatch, but Agent Hive does not claim an OS boundary it does not own. The Codex driver permits only `read-only` or `workspace-write` sandbox modes. The Claude driver explicitly refuses `bypassPermissions`; it uses `default` unless the caller selects another non-bypass mode.

`--approve` is a caller assertion, just like the lower-level `--human-approved` flag. Use it only after a real user decision. Command override flags select an executable directly without a shell; they are intended for testing or an explicitly trusted local wrapper.

An autonomous run also requires a required guard cell. A worker's `done` result is downgraded unless it includes verifiable evidence; controlled incomplete runs return process exit code `2` for monitoring and CI.

## Monitoring model

`.hive/run.json` stores resumable execution state, sanitized attempt history, stop reason, and gate decisions. `.hive/usage.json` stores the latest cell state, attempts, evidence, blockers, artifacts, token categories, model calls, latency, and optional USD cost. `.hive/audit.jsonl` records planning, run transitions, cell records, gates, rebalances, and memory operations without prompts, model output, or memory content. `hive status` aggregates metrics and raises budget, overrun, failure, blocked-cell, and attempt-limit alerts.

The audit file is local and editable by any process with workspace access. Ship it to an external append-only system when tamper evidence or centralized alert delivery is required. Do not commit `.hive/`; the directory is ignored by default.

## If exposed as a service

A server wrapper must add TLS, authentication, tenant-scoped RBAC, per-user and per-IP rate limits, encrypted secret management, tenant-isolated memory, durable audit storage, and alert delivery. Adding JWT code to this local CLI would not provide those guarantees.
