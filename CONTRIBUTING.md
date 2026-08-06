# Contributing

Agent Hive keeps a small, deterministic, provider-neutral core. Before opening a pull request:

1. Preserve mission text and literals exactly through compilation.
2. Label every token count by precision; never present a heuristic as an exact model count.
3. Keep Codex and Claude Code adapters behaviorally aligned.
4. Add focused tests for planner, accounting, protocol, or CLI changes.
5. Run `python -m unittest discover -s tests -t . -v`, `python scripts/benchmark.py`, `python scripts/sync_plugin_runtime.py`, and `python scripts/validate_repo.py`.

Use an issue to discuss schema or protocol breaking changes. Do not commit provider keys, usage ledgers, generated `.hive` state, or user prompts.
