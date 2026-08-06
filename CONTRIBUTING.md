# Contributing

Agent Hive keeps a small, deterministic, provider-neutral core. Before opening a pull request:

1. Preserve mission text and literals exactly through compilation.
2. Label every token count by precision; never present a heuristic as an exact model count.
3. Keep Codex and Claude Code adapters behaviorally aligned.
4. Add focused tests for planner, accounting, protocol, or CLI changes.
5. Run `npm test`, `npm run benchmark`, `npm run sync:plugins`, and `npm run validate`.

Use an issue to discuss schema or protocol breaking changes. Do not commit provider keys, usage ledgers, generated `.hive` state, or user prompts.
