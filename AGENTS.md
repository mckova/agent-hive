# Agent Hive repository guidance

- Keep the deterministic core provider-neutral and dependency-free.
- Preserve user text exactly across Mission Genome and HIVE/1 payloads.
- Never claim heuristic token estimates are exact model counts.
- Keep Codex and Claude Code adapters behaviorally aligned while respecting their different plugin formats.
- Run `npm.cmd test` and `npm.cmd run validate` on Windows before handing off changes.
