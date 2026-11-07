import unittest

from ai_engine.live_corner_model import estimate_live_remaining_corners


class LiveRemainingCornerModelTests(unittest.TestCase):
    def features(self):
        return {
            "league_id": 140,
            "teams": {"home": "Home FC", "away": "Away FC"},
            "corners": {"live_home_corners": 4, "live_away_corners": 2},
            "live": {
                "minute": 65, "home_shots_total": 12, "away_shots_total": 7,
                "home_shots_on_target": 5, "away_shots_on_target": 2,
                "home_possession": 61, "away_possession": 39,
            },
        }

    def estimator(self, rows, *, team, venue, corners_for, corners_against,
                  league, minute, minimum_matches):
        if team == "Home FC":
            return {"available": True, "sample_size": 10, "mean_corners_after": 3.0,
                    "prob_at_least_1_corner": 0.8, "prob_at_least_2_corners": 0.6,
                    "prob_team_gets_corner": 0.7}
        return {"available": True, "sample_size": 5, "mean_corners_after": 4.0,
                "prob_at_least_1_corner": 1.0, "prob_at_least_2_corners": 0.8,
                "prob_team_gets_corner": 0.9}

    def test_blends_two_views_of_same_match_without_adding_them(self):
        result = estimate_live_remaining_corners(self.features(), [], estimator=self.estimator)
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["expected_remaining_corners"], 10 / 3)
        self.assertAlmostEqual(result["projected_final_total_corners"], 28 / 3)
        self.assertEqual(result["current_corners"]["total"], 6)
        self.assertEqual(result["sample"]["perspectives_used"], ["home", "away"])

    def test_uses_one_available_perspective(self):
        def one_side(rows, **kwargs):
            if kwargs["team"] == "Home FC":
                return self.estimator(rows, **kwargs)
            return {"available": False, "sample_size": 2}
        result = estimate_live_remaining_corners(self.features(), [], estimator=one_side)
        self.assertTrue(result["available"])
        self.assertEqual(result["expected_remaining_corners"], 3.0)
        self.assertIsNone(result["team_probability_gets_corner"]["away"])

    def test_abstains_when_current_corners_are_missing(self):
        features = self.features()
        features["corners"]["live_away_corners"] = None
        result = estimate_live_remaining_corners(features, [], estimator=self.estimator)
        self.assertFalse(result["available"])
        self.assertIn("córners actuales", result["reason"])

    def test_abstains_when_minute_is_missing(self):
        features = self.features()
        features["live"]["minute"] = None
        result = estimate_live_remaining_corners(features, [], estimator=self.estimator)
        self.assertFalse(result["available"])
        self.assertIn("minuto", result["reason"])

    def test_abstains_when_both_historical_views_are_unavailable(self):
        def unavailable(rows, **kwargs):
            return {"available": False, "sample_size": 0}
        result = estimate_live_remaining_corners(self.features(), [], estimator=unavailable)
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
