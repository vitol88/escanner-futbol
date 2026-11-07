import unittest

from ai_engine.eligibility import build_model_eligibility


class ModelEligibilityTests(unittest.TestCase):
    def _features(self):
        return {
            "fixture_id": 100,
            "league_id": 39,
            "teams": {"home": "Arsenal", "away": "Chelsea"},
            "goals": {
                "home_goals_for_avg": 1.8, "home_goals_against_avg": 0.9,
                "away_goals_for_avg": 1.2, "away_goals_against_avg": 1.1,
            },
            "corners": {
                "home_corners_for_avg": 5.2, "home_corners_against_avg": 3.1,
                "away_corners_for_avg": 4.0, "away_corners_against_avg": 4.2,
                "live_home_corners": 5, "live_away_corners": 3,
            },
            "cards": {},
            "live": {"minute": 67},
        }

    def _coverage(self):
        return {
            "ready": {
                "prematch_goals": True,
                "prematch_corners": True,
                "prematch_yellow_cards": True,
                "referee_adjustment": False,
                "live_remaining_corners": True,
            },
            "markets": {"prematch_yellow_cards": {}},
        }

    def test_all_prematch_baselines_can_run_but_no_betting_signals(self):
        result = build_model_eligibility(self._features(), self._coverage())
        models = result["models"]
        self.assertTrue(models["prematch_goals"]["eligible"])
        self.assertTrue(models["prematch_corners"]["eligible"])
        self.assertTrue(models["prematch_yellow_cards"]["eligible"])
        for gate in models.values():
            self.assertFalse(gate["may_emit_betting_signal"])
        self.assertFalse(result["global_policy"]["betting_signals_enabled"])

    def test_live_model_abstains_without_its_separate_history_source(self):
        result = build_model_eligibility(self._features(), self._coverage())
        self.assertFalse(result["models"]["live_remaining_corners"]["eligible"])
        self.assertEqual(result["models"]["live_remaining_corners"]["status"], "abstain")

    def test_live_model_requires_history_and_current_match_state(self):
        rows = [{"league": "Premier League"}]
        result = build_model_eligibility(
            self._features(), self._coverage(), live_corner_history_rows=rows
        )
        self.assertTrue(result["models"]["live_remaining_corners"]["eligible"])
        features = self._features()
        features["corners"]["live_home_corners"] = None
        result = build_model_eligibility(
            features, self._coverage(), live_corner_history_rows=rows
        )
        self.assertFalse(result["models"]["live_remaining_corners"]["eligible"])

    def test_missing_average_blocks_model_even_if_coverage_says_ready(self):
        features = self._features()
        features["goals"]["away_goals_against_avg"] = None
        result = build_model_eligibility(features, self._coverage())
        self.assertFalse(result["models"]["prematch_goals"]["eligible"])
        self.assertTrue(result["models"]["prematch_corners"]["eligible"])

    def test_referee_adjustment_remains_abstained_without_independent_prior(self):
        result = build_model_eligibility(self._features(), self._coverage())
        self.assertFalse(result["referee_adjustment"]["eligible"])
        self.assertFalse(result["referee_adjustment"]["may_emit_betting_signal"])


if __name__ == "__main__":
    unittest.main()
