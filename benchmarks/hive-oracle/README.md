# Agent Hive system oracle

This live benchmark compares four complete systems on the same seeded HotpotQA multi-hop questions:

1. **Direct GPT-5.6** — one model call without supplied evidence.
2. **RAG + GPT-5.6** — local BM25 top-k retrieval followed by one model call.
3. **Agent Hive** — four dependent HIVE/1 cells: scout, forager, builder, and guard.
4. **Adaptive Memory Hive** — scoped memory, hooks, goal budgets, early stop, and at most one repair.

Every model call uses the same configured model and reasoning effort. The oracle records end-to-end latency, model-call latency, provider-reported token usage, exact match, token F1, and task loss (`1 - tokenF1`).

```powershell
$env:OPENAI_KEY = "..."
npm.cmd run benchmark:hive-oracle -- --limit=6
```

Use `--include=id1,id2` or `--exclude=id1,id2` for explicit development and holdout partitions. Small runs are smoke tests, not statistical proof.

The low-token atomic-evidence research that temporarily lived here has moved to the independent sibling project `agent-nest`.
