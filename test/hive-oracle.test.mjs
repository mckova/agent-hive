import test from "node:test";
import assert from "node:assert/strict";
import { aggregateMethods, aggregateUsage, answerMetrics, bm25Rank, enforceAnswerContract } from "../benchmarks/hive-oracle/lib.mjs";

test("BM25 ranks query evidence before noise", () => {
  const documents = [
    { text: "A document about gardens and trees." },
    { text: "Ada Lovelace wrote notes about the analytical engine." }
  ];
  assert.deepEqual(bm25Rank("Who wrote notes about the analytical engine?", documents), [1, 0]);
});

test("task loss is one minus token F1", () => {
  assert.deepEqual(answerMetrics("The Apollo 11.", "Apollo 11"), {
    exactMatch: 1,
    tokenF1: 1,
    exactLoss: 0,
    taskLoss: 0
  });
  assert.equal(answerMetrics("Apollo", "Apollo 11").taskLoss, 1 - 2 / 3);
});

test("output guard enforces a short binary answer without corrupting named entities", () => {
  assert.equal(enforceAnswerContract("Are both airports in Nevada?", "No, only one is in Nevada."), "no");
  assert.equal(enforceAnswerContract("Which band recorded the song?", "No Doubt"), "No Doubt");
});

test("usage aggregates all Hive cells", () => {
  assert.deepEqual(aggregateUsage([
    { latencyMs: 10, usage: { input_tokens: 5, output_tokens: 2, total_tokens: 7 } },
    { latencyMs: 20, usage: { input_tokens: 8, output_tokens: 3, total_tokens: 11 } }
  ]), {
    inputTokens: 13,
    outputTokens: 5,
    reasoningTokens: 0,
    totalTokens: 18,
    modelLatencyMs: 30
  });
});

test("method aggregation reports quality, loss, latency, and tokens", () => {
  const methods = aggregateMethods([{ systems: { direct: {
    quality: { exactMatch: 1, tokenF1: 0.75, exactLoss: 0, taskLoss: 0.25 },
    endToEndLatencyMs: 100,
    calls: [{}, {}],
    usage: { inputTokens: 10, outputTokens: 4, reasoningTokens: 0, totalTokens: 14 }
  } } }]);
  assert.equal(methods.direct.taskLoss, 0.25);
  assert.equal(methods.direct.calls, 2);
  assert.equal(methods.direct.averageTokensPerExample, 14);
});
