import unittest

from ai_engine.corner_model import estimate_prematch_corners


class PrematchCornerModelTests(unittest.TestCase):
    def _features(self):
        return {
            "corners": {
                "home_corners_for_avg": 6.2,
                "home_corners_against_avg": 3.1,
                "away_corners_for_avg": 4.4,
                "away_corners_against_avg": 5.0,
                "home_corner_sample": 12,
                "away_corner_sample": 10,
            },
            "data_quality": {"history_available": True},
        }

    def test_returns_expected_corners_and_market_probabilities(self):
        result = estimate_prematch_corners(self._features())
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["expected_home_corners"], 5.6)
        self.assertAlmostEqual(result["expected_away_corners"], 3.75)
        self.assertAlmostEqual(result["expected_total_corners"], 9.35)
        market = result["probability_total_corners"]["8.5"]
        self.assertAlmostEqual(market["over"] + market["under"], 1.0, places=8)
        self.assertGreaterEqual(market["over"], 0.0)
        self.assertLessEqual(market["over"], 1.0)

    def test_withholds_estimate_when_sample_is_small(self):
        features = self._features()
        features["corners"]["away_corner_sample"] = 3
        result = estimate_prematch_corners(features)
        self.assertFalse(result["available"])
        self.assertIn("Muestra insuficiente", result["reason"])

    def test_withholds_estimate_when_average_is_missing(self):
        features = self._features()
        features["corners"]["home_corners_for_avg"] = None
        result = estimate_prematch_corners(features)
        self.assertFalse(result["available"])
        self.assertIn("Faltan promedios", result["reason"])

    def test_rejects_negative_rates(self):
        features = self._features()
        features["corners"]["away_corners_for_avg"] = -1
        result = estimate_prematch_corners(features)
        self.assertFalse(result["available"])

    def test_zero_rates_are_valid(self):
        features = self._features()
        for key in (
            "home_corners_for_avg", "home_corners_against_avg",
            "away_corners_for_avg", "away_corners_against_avg",
        ):
            features["corners"][key] = 0
        result = estimate_prematch_corners(features)
        self.assertTrue(result["available"])
        self.assertEqual(result["expected_total_corners"], 0)


if __name__ == "__main__":
    unittest.main()
