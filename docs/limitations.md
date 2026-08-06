# Limitations

- Agent Hive allocates and gates a declared budget; it cannot force Codex or Claude Code to expose exact live usage when the host does not provide it.
- `utf8-bytes/4` is an offline planning heuristic, not a tokenizer. Use a provider/model counter for decisions that require precision.
- The OpenAI adapter counts encoded text and does not include message framing, tools, images, cached context, or output tokens.
- Anthropic's endpoint count is a provider estimate for the constructed one-message request; the final API usage can differ.
- The prompt compiler preserves literals and compares representations. It does not yet use a semantic model to paraphrase prose, because a cheaper prompt is not useful if it changes intent.
- Tier assignment is deterministic policy, not a benchmark of model quality. Users own the mapping from tiers to model IDs and plan limits.
- `hive run` can invoke an installed local Codex or Claude Code CLI, but it does not install, authenticate, or remotely configure either provider. Host-native skill execution remains available.
- The v0.3 runner executes ready cells sequentially for deterministic checkpoints. `policy.maxWorkers` still shapes planning and host-native dispatch, but autonomous parallel CLI execution is not implemented yet.
- A retry reruns the same cell with its blockers. Graph-level repair that automatically reopens an upstream builder after a guard rejection is not implemented yet.
- A cell allocation overrun stops autonomous execution for an explicit plan rebalance; v0.3 does not silently borrow from another cell.
- Provider CLI JSON formats can change. A missing worker contract or missing token/cost telemetry causes a safe stop instead of a fabricated success or zero-cost record.
- `modelCalls` is the number of provider turns exposed by the CLI format; providers may aggregate internal sampling differently.
- USD budgets require the driver to report `costUsd`; token budgets require token fields. Current Codex CLI output may not expose USD cost, so use a token budget there unless the host adds a trusted cost calculator.
- Starting `hive run --target codex|claude` from inside an existing provider session creates nested model calls. The installed skill therefore prefers host-native dispatch unless the user explicitly requests autonomous CLI execution.
- `hive gate` is a pre-dispatch policy decision, not an operating-system sandbox. A caller can lie about `--human-approved`; unattended deployments must bind approval to the host's real permission mechanism.
- The local JSONL audit trail is redacted but not tamper-evident or remotely shipped. Alerts appear through `status`; Agent Hive is not a background monitoring daemon.
- Scoped memory is a local JSON store, not encrypted storage or a semantic vector database. Namespace and visibility filters reduce accidental leakage but are not authentication boundaries for a multi-user service.
- Agent Hive is a local CLI, so it does not implement JWT, per-user RBAC, or per-IP HTTP rate limits. A server wrapper must add authentication, authorization, request throttling, and tenant-isolated storage.
