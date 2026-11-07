import unittest

from ai_engine.pipeline import analyze_experimental_models


class ExperimentalPipelineTests(unittest.TestCase):
    def _features(self):
        return {
            "fixture_id": 101,
            "league_id": 39,
            "league_name": "Premier League",
            "home_team_id": 1,
            "away_team_id": 2,
            "teams": {"home": "Arsenal", "away": "Chelsea"},
            "referee": "Ref A",
            "goals": {
                "home_goals_for_avg": 1.8, "home_goals_against_avg": 0.9,
                "away_goals_for_avg": 1.2, "away_goals_against_avg": 1.1,
                "home_goal_sample": 8, "away_goal_sample": 7,
            },
            "corners": {
                "home_corners_for_avg": 5.2, "home_corners_against_avg": 3.1,
                "away_corners_for_avg": 4.0, "away_corners_against_avg": 4.2,
                "home_corner_sample": 8, "away_corner_sample": 7,
                "live_home_corners": 5, "live_away_corners": 3,
            },
            "live": {"minute": 67},
            "data_quality": {"history_available": True},
        }

    def _history(self):
        rows = []
        for index in range(6):
            rows.extend([
                {"league_id": 39, "home_team_id": 1, "away_team_id": 10 + index,
                 "home_yellow_cards": 2, "away_yellow_cards": 1, "referee": "Ref A"},
                {"league_id": 39, "home_team_id": 20 + index, "away_team_id": 2,
                 "home_yellow_cards": 1, "away_yellow_cards": 3, "referee": "Ref B"},
            ])
        return {"card_history_rows": rows}

    def test_runs_only_eligible_prematch_models_and_keeps_policy_closed(self):
        result = analyze_experimental_models(
            self._features(), self._history(), minimum_team_sample=5
        )
        self.assertTrue(result["models"]["prematch_goals"]["available"])
        self.assertTrue(result["models"]["prematch_corners"]["available"])
        self.assertTrue(result["models"]["prematch_yellow_cards"]["available"])
        self.assertFalse(result["models"]["live_remaining_corners"]["available"])
        self.assertEqual(result["models"]["live_remaining_corners"]["status"], "abstain")
        self.assertFalse(result["policy"]["betting_signals_enabled"])
        for model in result["models"].values():
            self.assertFalse(model.get("may_emit_betting_signal", False))

    def test_missing_samples_cause_abstention_without_running_models(self):
        features = self._features()
        features["goals"]["away_goal_sample"] = 1
        result = analyze_experimental_models(features, self._history())
        self.assertFalse(result["models"]["prematch_goals"]["available"])
        self.assertEqual(result["models"]["prematch_goals"]["status"], "abstain")
        self.assertTrue(result["models"]["prematch_corners"]["available"])

    def test_live_corner_pipeline_uses_competition_name_history(self):
        features = self._features()
        rows = []
        for _ in range(8):
            rows.append({
                "league": "Premier League", "team": "Arsenal", "venue": "home",
                "minute": 67, "corners_for": 5, "corners_against": 3,
                "corners_for_after": 1, "corners_against_after": 0,
            })
        result = analyze_experimental_models(
            features, self._history(), live_corner_history_rows=rows
        )
        self.assertTrue(result["models"]["live_remaining_corners"]["available"])
        self.assertEqual(result["models"]["live_remaining_corners"]["sample"]["perspectives_used"], ["home"])

    def test_pipeline_is_safe_with_empty_inputs(self):
        result = analyze_experimental_models({})
        self.assertTrue(all(not model["available"] for model in result["models"].values()))
        self.assertFalse(result["policy"]["recommendations_enabled"])


if __name__ == "__main__":
    unittest.main()
