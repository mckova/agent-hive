# Adaptive Memory Hive — disjoint holdout oracle

Run date: 2026-08-05

Dataset: HotpotQA validation/distractor

Holdout: 6 seeded multi-hop questions, excluding all development questions

Model: `gpt-5.6-sol`, reasoning effort `none`

Loss: `1 - token F1` (lower is better)

| System | Calls | Avg latency | Avg tokens/question | Exact match | Token F1 | Task loss |
|---|---:|---:|---:|---:|---:|---:|
| Direct GPT-5.6 | 6 | 1.848 s | 71.7 | 50.0% | 0.705 | 0.295 |
| BM25 RAG + GPT-5.6 | 6 | 1.320 s | 492.0 | 33.3% | 0.487 | 0.513 |
| Agent Hive | 24 | 9.524 s | 2,418.0 | 50.0% | 0.820 | 0.180 |
| **Adaptive Memory Hive** | **10** | **2.898 s** | **1,457.8** | **83.3%** | **0.976** | **0.024** |

Against the fixed four-cell Hive, the adaptive controller used 58.3% fewer model calls, reduced average latency by 69.6%, and used 39.7% fewer tokens. It improved quality relative to BM25 RAG but did not beat RAG on raw cost.

The run exercised mission/team/agent memory isolation, ranked evidence recall, confidence and budget stop conditions, a local retrieval allow-list, trace hooks, output contracts, and end-of-mission memory deletion. All active memory records were removed after each question.

This six-question holdout is an oracle, not statistical proof. A publishable claim requires at least 100 disjoint examples, repeated seeds, confidence intervals, a stronger retriever baseline, and a separate adversarial security evaluation.
