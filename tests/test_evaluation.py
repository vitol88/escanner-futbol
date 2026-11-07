import math
import unittest

from ai_engine.evaluation import evaluate_binary_forecasts


class BinaryForecastEvaluationTests(unittest.TestCase):
    def test_perfect_forecasts_have_zero_brier_and_log_loss(self):
        rows = [
            {"estimated_probability_exploratory": 1, "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": 0, "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows, minimum_sample=2)
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["brier_score"], 0)
        self.assertEqual(result["log_loss"], 0)
        self.assertTrue(result["minimum_sample_reached"])

    def test_unverified_and_invalid_rows_are_excluded(self):
        rows = [
            {"estimated_probability_exploratory": 0.8, "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": 0.2, "outcome": 0, "outcome_verified": False},
            {"estimated_probability_exploratory": "bad", "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": math.inf, "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": 0.4, "outcome": "unknown", "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows)
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["excluded"], 4)
        self.assertFalse(result["minimum_sample_reached"])

    def test_reliability_bins_include_probability_one(self):
        rows = [
            {"estimated_probability_exploratory": 0.05, "outcome": 0, "outcome_verified": True},
            {"estimated_probability_exploratory": 1.0, "outcome": 1, "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows, bins=10)
        self.assertEqual(len(result["reliability"]), 2)
        self.assertEqual(result["reliability"][-1]["upper_bound"], 1.0)

    def test_empty_data_returns_null_metrics(self):
        result = evaluate_binary_forecasts([{"outcome": 1, "outcome_verified": False}])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["brier_score"])
        self.assertEqual(result["reliability"], [])

    def test_invalid_configuration_raises(self):
        with self.assertRaises(ValueError):
            evaluate_binary_forecasts([], bins=0)
        with self.assertRaises(ValueError):
            evaluate_binary_forecasts([], minimum_sample=0)


    def test_grouped_evaluation_separates_markets_and_ignores_unverified(self):
        from ai_engine.evaluation import evaluate_forecasts_by_group

        rows = [
            {"market": "Corners", "estimated_probability_exploratory": 0.8, "outcome": 1, "outcome_verified": True},
            {"market": "Corners", "estimated_probability_exploratory": 0.3, "outcome": 0, "outcome_verified": True},
            {"market": "Goals", "estimated_probability_exploratory": 0.7, "outcome": 1, "outcome_verified": True},
            {"market": "Goals", "estimated_probability_exploratory": 0.6, "outcome": 1, "outcome_verified": False},
            {"market": "", "estimated_probability_exploratory": 0.5, "outcome": 1, "outcome_verified": True},
        ]
        result = evaluate_forecasts_by_group(rows, group_key="market", minimum_sample=2)
        self.assertEqual([item["group"] for item in result], ["Corners", "Goals"])
        self.assertEqual(result[0]["sample_size"], 2)
        self.assertEqual(result[1]["sample_size"], 1)
        self.assertFalse(result[1]["minimum_sample_reached"])

    def test_grouped_evaluation_rejects_empty_group_key(self):
        from ai_engine.evaluation import evaluate_forecasts_by_group

        with self.assertRaises(ValueError):
            evaluate_forecasts_by_group([], group_key=" ")


if __name__ == "__main__":
    unittest.main()
