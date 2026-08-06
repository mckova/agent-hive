from __future__ import annotations

import unittest

from benchmarks.hive_oracle.lib import aggregate_methods, aggregate_usage, answer_metrics, bm25_rank, enforce_answer_contract


class HiveOracleTests(unittest.TestCase):
    def test_bm25_ranks_query_evidence_before_noise(self):
        documents = [{"text": "A document about gardens and trees."},
                     {"text": "Ada Lovelace wrote notes about the analytical engine."}]
        self.assertEqual(bm25_rank("Who wrote notes about the analytical engine?", documents), [1, 0])

    def test_task_loss_is_one_minus_token_f1(self):
        self.assertEqual(answer_metrics("The Apollo 11.", "Apollo 11"),
                         {"exactMatch": 1, "tokenF1": 1, "exactLoss": 0, "taskLoss": 0})
        self.assertAlmostEqual(answer_metrics("Apollo", "Apollo 11")["taskLoss"], 1 - 2 / 3)

    def test_output_guard_enforces_short_binary_answer(self):
        self.assertEqual(enforce_answer_contract("Are both airports in Nevada?", "No, only one is in Nevada."), "no")
        self.assertEqual(enforce_answer_contract("Which band recorded the song?", "No Doubt"), "No Doubt")

    def test_usage_aggregates_all_hive_cells(self):
        self.assertEqual(aggregate_usage([{"latencyMs": 10, "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}},
                                          {"latencyMs": 20, "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11}}]),
                         {"inputTokens": 13, "outputTokens": 5, "reasoningTokens": 0, "totalTokens": 18, "modelLatencyMs": 30})

    def test_method_aggregation_reports_quality_latency_and_tokens(self):
        methods = aggregate_methods([{"systems": {"direct": {"quality": {"exactMatch": 1, "tokenF1": 0.75,
            "exactLoss": 0, "taskLoss": 0.25}, "endToEndLatencyMs": 100, "calls": [{}, {}],
            "usage": {"inputTokens": 10, "outputTokens": 4, "reasoningTokens": 0, "totalTokens": 14}}}}])
        self.assertEqual(methods["direct"]["taskLoss"], 0.25); self.assertEqual(methods["direct"]["calls"], 2)
        self.assertEqual(methods["direct"]["averageTokensPerExample"], 14)


if __name__ == "__main__":
    unittest.main()
