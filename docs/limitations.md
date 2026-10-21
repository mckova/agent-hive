# Limitations and recovery

Agent Hive is an Alpha local orchestration toolkit. Its deterministic planning and ledger make execution reviewable; they do not establish autonomous production readiness or a general improvement in quality, speed, or cost.

## Planning and execution

- Empty or omitted `cells` selects a six-role template. The planner does not inspect a repository or call a planning model; callers must supply concrete paths and task-specific instructions. Malformed `cells` values are rejected.
- The terminal runner executes ready cells sequentially. `policy.maxWorkers` shapes planning waves and host-native scheduling, not parallel subprocess execution.
- Host-native skills can dispatch independent cells with disjoint write scopes; that scheduling belongs to the host. The terminal runner provides bounded, untrusted dependency summaries and artifact references, not artifact file contents.
- The builder implements. Each declared write/delete/external-write cell, including an optional one, requires a required downstream guard limited to read/network actions. Validation checks the graph and declarations, not whether a model actually performed each cited test. Completion still relies on reported evidence that a reviewer can verify. Push/deploy retain human gates without an automatic deployment-outcome verification guarantee.
- Retries repeat the same cell with its blockers within its attempt/allocation limits. A guard rejection does not automatically reopen an upstream builder.
- Updating an upstream ledger outcome invalidates completed descendants without erasing their spend/attempts. It does not detect arbitrary filesystem changes.
- The core retains the source language but trims surrounding whitespace in mission strings; generated role text also collapses whitespace. It does not guarantee arbitrary byte preservation or semantically paraphrase the mission.

## Usage and budgets

- Spending checks happen between calls. A single call can exceed its allocation or the remaining budget before the runner stops; the declared allocation is not a provider-side hard spend cap.
- Token budgets require complete input/output totals. Cached input remains included in input; reasoning is reported separately as a subset of output and is not added again. Provider CLI formats may change and can omit usage.
- Missing telemetry after any invocation, including failure, blocks dispatch with unknown usage. Known spending is only a lower bound while an invocation remains unresolved. The runner does not assume that a failed call was free.
- `modelCalls` counts provider turns exposed in the CLI response, not every internal model sample. USD budgets require `costUsd`; the Codex parser does not currently supply it.
- `utf8-bytes/4` is an offline planning heuristic. Optional OpenAI text counts exclude API message framing, tools, images, and output. Anthropic counting calls a remote endpoint for a constructed message; actual final request usage can differ. None of these prompt counts is a billing total.
- Tier assignment is deterministic policy, not a model-quality benchmark. Available models and billing depend on the host/provider; the core does not automatically switch arbitrary providers or choose a universally cheapest language.
- Rebalance preserves recorded spending and reallocates future capacity. It writes a separate file by default; inspect and deliberately select the revision used by a saved run. Reserve release must be explicit.

## Checkpoint and reconciliation

Resume is bound to the saved provider target and workspace. A new run must use a fresh state directory rather than silently replacing an existing run. Checkpoint files use atomic individual writes; they are not a multi-file transaction or a concurrent-run guarantee.

An invocation interrupted after dispatch may already have changed files or consumed tokens. Resume quarantines it rather than silently repeating it. Inspect the actual artifacts and provider usage, then record the confirmed cumulative usage, attempt count, outcome, and evidence:

```text
hive reconcile <cell-id> --state-dir .hive --status done|pending|blocked|failed --used <confirmed-cumulative-units> --attempts <confirmed-invocations> --evidence "Inspected outcome and usage source"
```

Use an actual status, never the pipe-separated placeholder. `done` requires known completed dependencies; `pending` permits a retry only when attempts and budget remain. Reconciliation cannot decrease confirmed spending/attempts or exceed the attempt cap; a duplicate reconciliation is rejected. Ordinary `record` cannot clear unknown accounting. Reconciliation records an inspected outcome; it does not authorize another call. Resume only after the unknown outcome is resolved and any required action approval exists.

These files are not a substitute for provider billing records, workspace backups, or external transactional storage. If actual usage cannot be established, leave the run blocked instead of inventing a zero-cost result.

## Host permissions and local state

- `hive run` requires an installed, authenticated, compatible Codex or Claude Code CLI. It does not install or configure the provider. Starting it inside an active provider session creates nested model calls; the skills prefer host-native dispatch there.
- `hive gate` validates declared actions and paths before dispatch. It is not an operating-system sandbox or per-tool network firewall. Host filesystem, command, and network permissions remain the execution boundary.
- `--human-approved` and `--approve` assert an actual caller-observed approval. They are not authenticated human consent; wrappers must bind them to the host's real approval process.
- Scoped memory uses local deterministic filters, not encryption, semantic retrieval, or multi-user authentication. Queries exclude TTL-expired records, while decay removes them from storage. Recall into workers is explicit.
- JSONL audit events are locally redacted but editable by a process with file access. Alerts appear through `status`; Agent Hive is not a background monitoring daemon.
- A service wrapper would need authentication, authorization, tenant-isolated storage, throttling, secret management, and durable audit delivery. The local CLI does not provide those service boundaries.

The [Hugging Face playground](https://huggingface.co/spaces/mckova/agent-hive) is a browser planner preview. It does not execute workers or prove the live coding runner. Committed benchmark reports retain their original dates, models, fixtures, and small-sample limitations.
