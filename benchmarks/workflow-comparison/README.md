# Workflow comparison benchmark

This benchmark compares five approaches on the same implementation task and model:

1. A normal, well-scoped prompt.
2. [`JuliusBrussee/caveman`](https://github.com/JuliusBrussee/caveman).
3. [`PageAI-Pro/ralph-loop`](https://github.com/PageAI-Pro/ralph-loop).
4. [`cobusgreyling/loop-engineering`](https://github.com/cobusgreyling/loop-engineering).
5. Agent Hive from this repository.

Latest committed analysis: [results/REPORT.md](results/REPORT.md).

The methods operate at different layers. Caveman compresses communication, Ralph repeats fresh-context task iterations, Loop Engineering supplies loop primitives and governance patterns, and Agent Hive plans dependency-aware worker cells with a budget ledger. The benchmark therefore reports separate dimensions instead of forcing one misleading number.

## Dimensions

- Final artifact: public and hidden behavioral tests, scope compliance, maintainability.
- Efficiency: input, cached input, output, and reasoning tokens; wall-clock latency; number of model turns.
- Security and guardrails: isolation, tool/path controls, injection handling, human gates, attempt/budget breakers, secret policy.
- Monitoring: task state, usage and latency telemetry, audit trail, evidence, alerts.
- Memory and context: short-term state, durable cross-run memory, private/shared worker context, selective recall, stale/leaky-memory controls.

See [RUBRIC.md](RUBRIC.md). Generated run directories live under `C:\tmp`; only summarized, provenance-stamped results belong in this repository.

## Fairness rules

- Same fixture, initial task, model, reasoning effort, Codex host, and hidden grader.
- No arm may read another arm or the hidden grader.
- Repository-based methods are pinned by commit SHA in the result.
- Method-specific orchestration overhead counts. Deterministic local planning does not consume model tokens but does count toward wall time.
- A verifier can trigger a bounded repair pass. The extra tokens and time count.
- Hidden tests run only after an arm stops.
- Provider usage fields are reported separately; cached tokens are never presented as ordinary uncached input.

The first live run uses GPT-5.5 because the installed Codex CLI cannot invoke GPT-5.6. Claude Code was unavailable because its local OAuth token had expired.

The initial Agent Hive profile deliberately used `scout -> builder -> guard`. A post-benchmark compact profile applies swarm admission and uses `builder -> guard` for this atomic, fully specified task. It is reported as a forward test, not silently substituted into the original five-arm run.
