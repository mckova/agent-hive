# Workflow comparison: quality, tokens, security, monitoring, and memory

Date: 2026-08-05. Model: GPT-5.5, medium reasoning. Host: Codex CLI 0.130.0.

## Bottom line

All five primary methods produced a fully correct artifact: public tests passed, all 12 hidden cases passed, all six hidden security/resource cases passed, and every implementation met the scope checks. On this small, well-specified task, more orchestration bought no additional artifact quality.

The normal prompt and Caveman were the efficiency leaders and are effectively tied in a single run. Loop Engineering was the strongest production-governance workflow. Initial Agent Hive over-orchestrated the task. The post-test `builder -> guard` admission rule preserved 40/40 quality while reducing Hive token fields by roughly 39%-42%, although wall-clock time did not improve in that run.

## Reproducibility

- Fixture: dependency-free JavaScript token-bucket rate limiter with input validation, fractional refill, monotonic time, LRU bounds, prototype-like keys, reset/peek API, and no background handles.
- Same initial fixture, host, model, reasoning effort, and hidden grader for every primary arm.
- Pinned repositories: [Caveman](https://github.com/JuliusBrussee/caveman/tree/ec83e5bace4c20484d704dea21e12fc4eb94e9aa), [Ralph Loop](https://github.com/PageAI-Pro/ralph-loop/tree/eba65ebbb0a78c4a7fd25aab28e94966eddbca5b), and [Loop Engineering](https://github.com/cobusgreyling/loop-engineering/tree/eb4b4061895d6981936add1611acbf116ab76f8f).
- The Loop Engineering result uses the clean two-turn rerun. The first harness incorrectly interpreted a verifier's explanatory use of the word `REJECT` as a rejection and launched two unnecessary turns; that parser bug was fixed before the reported run.
- Exact data is in [2026-08-05-gpt-5.5.json](2026-08-05-gpt-5.5.json). The task and grader are committed beside this report.

## Final artifact quality

| Method | Artifact | Public | Hidden | Hidden security | Source lines |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal prompt | 40/40 | pass | 12/12 | 10/10 | 101 |
| Caveman | 40/40 | pass | 12/12 | 10/10 | 105 |
| Ralph Loop | 40/40 | pass | 12/12 | 10/10 | 107 |
| Loop Engineering | 40/40 | pass | 12/12 | 10/10 | 88 |
| Agent Hive 0.1, full | 40/40 | pass | 12/12 | 10/10 | 127 |
| Agent Hive 0.2, compact forward test | 40/40 | pass | 12/12 | 10/10 | 112 |

There is no empirical basis in this fixture to claim that any method produced a better final implementation. The differentiator is workflow overhead and operational control.

## Live token and time measurements

`input` is the provider-reported cumulative input across tool-driven turns. `uncached` is `input - cached input`; cached input is not treated as free. These values are not context-window sizes.

| Method | Turns | Input | Cached | Uncached | Output | Reasoning | Output + reasoning | Time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal prompt | 1 | 168,464 | 144,000 | 24,464 | 2,334 | 284 | 2,618 | 79.6s |
| Caveman | 1 | 152,206 | 129,280 | 22,926 | 2,554 | 497 | 3,051 | 78.4s |
| Ralph Loop | 2 | 401,340 | 350,592 | 50,748 | 4,397 | 1,145 | 5,542 | 161.2s |
| Loop Engineering | 2 | 420,114 | 391,552 | 28,562 | 5,386 | 1,418 | 6,804 | 163.9s |
| Agent Hive 0.1, full | 3 | 632,236 | 562,560 | 69,676 | 10,559 | 1,462 | 12,021 | 320.8s |

The 20-point normalized efficiency scores were: Caveman 19.29, normal prompt 19.16, Loop Engineering 10.18, Ralph 8.98, and initial Agent Hive 5.34.

### What happened with Caveman

Caveman reduced visible agent-message characters from 1,394 to 863 (-38%), but provider-reported output plus reasoning rose from 2,618 to 3,051 (+16.5%). Full and uncached input were lower, and runtime was 1.2 seconds shorter. In one sample these opposing changes are a statistical tie, not proof of savings.

That result matches Caveman's own honest limitation: it primarily compresses narration, adds skill instructions to input, and may go net-negative on already terse coding workloads. Caveman is a communication compressor, not a project governor.

## Security, guardrails, monitoring, and memory audit

The live host sandbox was common to all arms and is excluded from method-owned scores. Static scores use the rubric and require repository or runtime evidence.

| Method as run | Security /20 | Monitoring /10 | Memory /10 | Main evidence |
| --- | ---: | ---: | ---: | --- |
| Normal prompt | 0 | 0 | 0 | No reusable method-owned controls. |
| Caveman | 1 | 3 | 3 | Destructive-operation clarity, session token/USD stats, manual memory-file compression; no orchestration sandbox, retry breaker, scoped recall, or task audit. |
| Ralph Loop | 12 | 7 | 5 | Docker sandbox, max iterations, `BLOCKED`/`DECIDE`, task state, timing and history logs, fresh contexts. |
| Loop Engineering | 20 | 10 | 9 | Worktree/sandbox, path gate, constraints, maker/checker, budget kill switch, run log, alerts, durable state, context circuit breaker. Role-private memory is less explicit than its shared state. |
| Agent Hive 0.1 | 6 | 7 | 5 | Hard token/reserve gate, evidence contract, usage state, bounded cell payloads, reusable context; no mechanical path gate, latency field, audit trail, or poisoned-memory policy yet. |

The convenience composite for the versions actually run was: Loop Engineering 89.18, Ralph 72.98, Caveman 66.29, Agent Hive 0.1 63.34, and normal prompt 59.16. This number mixes an empirical artifact/efficiency test with a static capability audit and should not hide the dimensional results above.

## Agent Hive forward test after the findings

Version 0.2 adds:

- swarm admission: atomic, specified work uses `builder -> guard`;
- deterministic path/workspace/network/human-action gate;
- per-cell attempt cap and budget alerts;
- explicit untrusted-input boundary in every HIVE/1 payload;
- recursive secret/prompt redaction and JSONL audit events;
- token categories, model calls, latency, optional cost, task state, evidence, and alerts;
- persistent scoped memory with trust, role visibility, sensitivity, TTL, decay, selective recall, and verified reinforcement.

The compact forward test retained 40/40 quality and changed the initial Hive measurements as follows:

| Metric | Full Hive | Compact Hive | Change |
| --- | ---: | ---: | ---: |
| Turns | 3 | 2 | -33.3% |
| Input | 632,236 | 369,033 | -41.63% |
| Uncached input | 69,676 | 42,761 | -38.63% |
| Output + reasoning | 12,021 | 7,120 | -40.77% |
| Time | 320.8s | 340.2s | +6.07% |

The later run's indicative efficiency score is 8.27 and its current static governance audit is 15/20 security, 10/10 monitoring, and 10/10 memory. Its indicative composite is 83.27, but it is not substituted into the original five-arm ranking because it was a later single run. The remaining security gap is deliberate: Agent Hive uses the host sandbox rather than pretending its CLI gate is OS isolation, and `--human-approved` is a caller assertion rather than cryptographic approval evidence.

Version 0.3 subsequently added the checkpointed `hive run` CLI, Codex/Claude drivers, safe timeout and output bounds, explicit resume, per-cell allocation stops, required guard evidence, and nonzero exit codes for controlled incomplete runs. Those controls passed deterministic and dry-run forward tests, but v0.3 has not been substituted into the live quality/token table without a new paid multi-run benchmark.

## Which method is better for what

| Situation | Best fit from this evidence |
| --- | --- |
| One small, explicit coding task | Normal prompt; add Caveman only if shorter human-facing narration matters. |
| Repeated backlog work with fresh contexts | Ralph Loop. |
| Mature unattended production loop governance | Loop Engineering. |
| Multilingual, provider-neutral budget allocation across Codex and Claude Code | Agent Hive, with compact admission for atomic tasks. |
| Prompt/output compression | Caveman as a complement to another workflow, not a replacement. |

Loop Engineering is currently the strongest reference for operational maturity. Agent Hive's useful differentiation is narrower: multilingual intent preservation, named model-tier routing across Codex and Claude Code, deterministic token allocation and reserve, and compact role payloads. Its portfolio story is stronger when it acknowledges Loop Engineering and demonstrates where the Hive is materially different.

## What must be tested next

1. Run at least five randomized-order repetitions per arm and report median plus dispersion.
2. Repeat on small, medium, and multi-component tasks; one rate limiter cannot validate swarm benefits.
3. Re-run with Claude Code after OAuth is restored, using the same fixture and model class.
4. Price cached and uncached input with the actual provider plan instead of assuming a universal discount.
5. Add adversarial prompt-injection, secret-exfiltration, stale-memory, cross-namespace, tool-misuse, and infinite-loop scenarios to the live harness.
