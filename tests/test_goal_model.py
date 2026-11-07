import unittest

from ai_engine.goal_model import estimate_prematch_goals


class PrematchGoalModelTests(unittest.TestCase):
    def _features(self):
        return {
            "goals": {
                "home_goals_for_avg": 1.8,
                "home_goals_against_avg": 0.8,
                "away_goals_for_avg": 1.2,
                "away_goals_against_avg": 1.4,
                "home_goal_sample": 10,
                "away_goal_sample": 9,
            },
            "data_quality": {"history_available": True},
        }

    def test_returns_consistent_poisson_markets(self):
        result = estimate_prematch_goals(self._features())
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["expected_home_goals"], 1.6)
        self.assertAlmostEqual(result["expected_away_goals"], 1.0)
        self.assertAlmostEqual(
            sum(result["probability_1x2"].values()), 1.0, places=10
        )
        self.assertGreaterEqual(result["probability_btts"], 0.0)
        self.assertLessEqual(result["probability_btts"], 1.0)
        self.assertGreaterEqual(result["probability_total_goals"]["2.5"]["over"], 0.0)
        self.assertLessEqual(result["probability_total_goals"]["2.5"]["over"], 1.0)

    def test_withholds_estimate_when_sample_is_small(self):
        features = self._features()
        features["goals"]["away_goal_sample"] = 3
        result = estimate_prematch_goals(features)
        self.assertFalse(result["available"])
        self.assertIn("Muestra insuficiente", result["reason"])

    def test_withholds_estimate_when_average_is_missing(self):
        features = self._features()
        features["goals"]["home_goals_for_avg"] = None
        result = estimate_prematch_goals(features)
        self.assertFalse(result["available"])
        self.assertIn("Faltan promedios", result["reason"])

    def test_rejects_negative_rates(self):
        features = self._features()
        features["goals"]["away_goals_for_avg"] = -1
        result = estimate_prematch_goals(features)
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
