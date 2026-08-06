# Agent Hive repository guidance

- Keep the deterministic core provider-neutral and dependency-free.
- Preserve user text exactly across Mission Genome and HIVE/1 payloads.
- Never claim heuristic token estimates are exact model counts.
- Keep Codex and Claude Code adapters behaviorally aligned while respecting their different plugin formats.
- Support Python 3.11 or newer without required third-party runtime dependencies.
- Run `python -m unittest discover -s tests -t . -v`, `python scripts/benchmark.py`, `python scripts/sync_plugin_runtime.py`, and `python scripts/validate_repo.py` before handing off changes.
