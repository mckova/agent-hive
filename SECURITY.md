# Security policy

Please report vulnerabilities privately to the repository owner instead of opening a public issue. Include affected versions, reproduction steps, impact, and the smallest safe proof of concept.

Never include API keys, private prompts, repository secrets, or generated `.hive/usage.json` data in a report. Agent Hive reads `ANTHROPIC_API_KEY` only when the Anthropic token counter is explicitly selected and does not persist the key.

The default guardrail policy denies `.env`, `.git`, `secrets`, and `credentials` paths and disables network access at the orchestration-policy layer. Keep the Codex or Claude Code sandbox enabled: `hive gate` is a deterministic pre-dispatch check, not an operating-system boundary.

`hive run` does not use a shell to launch provider CLIs, refuses Claude `bypassPermissions`, bounds captured output, and can enforce a per-call timeout. These controls do not replace the provider sandbox or human approval UI.

Memory and audit files live under `.hive/`, which is gitignored. Memory content is not encrypted; do not store credentials or regulated data. Audit events redact common credential, prompt, and memory-content fields, but the local log is not tamper-evident.

See [docs/security-and-observability.md](docs/security-and-observability.md) for the complete trust model and deployment requirements.
