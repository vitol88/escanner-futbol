import unittest

from models.backtest import evaluate_binary_predictions


class BacktestMetricTests(unittest.TestCase):
    def test_scores_only_verified_binary_outcomes(self):
        rows = [
            {"estimated_probability_exploratory": "0.8", "outcome": "1", "outcome_verified": "true"},
            {"estimated_probability_exploratory": "0.25", "outcome": "0", "outcome_verified": "yes"},
            {"estimated_probability_exploratory": "0.99", "outcome": "", "outcome_verified": ""},
            {"estimated_probability_exploratory": "0.5", "outcome": "1", "outcome_verified": "false"},
        ]
        result = evaluate_binary_predictions(rows)
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["excluded"], 2)
        self.assertEqual(result["hit_rate"], 0.5)
        self.assertAlmostEqual(result["brier_score"], ((0.8 - 1) ** 2 + (0.25 - 0) ** 2) / 2)

    def test_invalid_probability_is_excluded(self):
        result = evaluate_binary_predictions([
            {"estimated_probability_exploratory": "1.4", "outcome": "1", "outcome_verified": "true"}
        ])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["brier_score"])

    def test_empty_input_returns_no_metrics(self):
        result = evaluate_binary_predictions([])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["hit_rate"])


if __name__ == "__main__":
    unittest.main()
