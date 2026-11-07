import unittest

from ai_engine.feature_builder import build_model_features


class FeatureBuilderTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "match": {
                "fixture_id": 123,
                "league": {"id": 39, "name": "Premier League", "season": 2026, "referee": "Referee Test"},
                "teams": {
                    "home": {"name": "Arsenal"},
                    "away": {"name": "Chelsea"},
                },
                "status": {"elapsed": 67},
                "goals": {"home": 1, "away": 0},
            },
            "statistics": {
                "available": True,
                "missing_teams": [],
                "home": {"values": {
                    "corners": {"value": 5},
                    "shots_total": {"value": 12},
                    "shots_on_target": {"value": 4},
                    "possession": {"value": 58, "unit": "percent"},
                    "yellow_cards": {"value": 1},
                }},
                "away": {"values": {
                    "corners": {"value": 2},
                    "shots_total": {"value": 7},
                    "shots_on_target": {"value": 2},
                    "possession": {"value": 42, "unit": "percent"},
                    "yellow_cards": {"value": 2},
                }},
            },
        }

    def test_builds_goal_corner_and_live_features(self):
        history = {
            "available": True,
            "home_goals_for": 1.8,
            "home_goals_against": 0.9,
            "away_goals_for": 1.2,
            "away_goals_against": 1.4,
            "home_goal_sample": 8,
            "away_goal_sample": 7,
            "home_corners_for": 6.1,
            "home_corners_against": 3.2,
            "away_corners_for": 4.4,
            "away_corners_against": 5.0,
            "home_corner_sample": 6,
            "away_corner_sample": 5,
        }
        result = build_model_features(self._snapshot(), history)
        self.assertEqual(result["fixture_id"], 123)
        self.assertEqual(result["referee"], "Referee Test")
        self.assertEqual(result["league_name"], "Premier League")
        self.assertEqual(result["goals"]["home_goals_for_avg"], 1.8)
        self.assertEqual(result["corners"]["away_corners_for_avg"], 4.4)
        self.assertEqual(result["live"]["minute"], 67)
        self.assertEqual(result["live"]["home_possession"], 58)
        self.assertEqual(result["data_quality"]["goal_sample"], 7)
        self.assertEqual(result["data_quality"]["corner_sample"], 5)
        self.assertFalse(result["data_quality"]["card_history_available"])
        self.assertEqual(result["data_quality"]["card_history_sample"], 0)


    def test_reports_card_history_and_referee_sample_by_league(self):
        history = {
            "card_history_rows": [
                {"league_id": 39, "home_yellow_cards": 2, "away_yellow_cards": 3, "referee": "Referee Test"},
                {"league_id": 39, "home_yellow_cards": 1, "away_yellow_cards": 1, "referee": "Other Referee"},
                {"league_id": 140, "home_yellow_cards": 4, "away_yellow_cards": 2, "referee": "Referee Test"},
                {"league_id": 39, "home_yellow_cards": None, "away_yellow_cards": 2, "referee": "Referee Test"},
            ]
        }
        result = build_model_features(self._snapshot(), history)
        self.assertTrue(result["data_quality"]["card_history_available"])
        self.assertEqual(result["data_quality"]["card_history_sample"], 2)
        self.assertEqual(result["data_quality"]["referee_card_history_sample"], 1)
        self.assertEqual(result["cards"]["historical_sample"], 2)
        self.assertEqual(result["cards"]["referee_historical_sample"], 1)

    def test_missing_history_and_statistics_stay_missing(self):
        snapshot = self._snapshot()
        snapshot["statistics"] = {
            "available": False, "missing_teams": ["home", "away"],
            "home": {"values": {}}, "away": {"values": {}},
        }
        result = build_model_features(snapshot, {})
        self.assertIsNone(result["goals"]["home_goals_for_avg"])
        self.assertIsNone(result["corners"]["live_home_corners"])
        self.assertIsNone(result["live"]["home_shots_total"])
        self.assertIn("home_goals_for_avg", result["data_quality"]["goal_history_missing"])
        self.assertFalse(result["data_quality"]["statistics_available"])

    def test_invalid_numeric_values_are_not_coerced_to_zero(self):
        snapshot = self._snapshot()
        snapshot["match"]["status"]["elapsed"] = "ND"
        snapshot["statistics"]["home"]["values"]["corners"]["value"] = "N/A"
        result = build_model_features(snapshot, {})
        self.assertIsNone(result["live"]["minute"])
        self.assertIsNone(result["corners"]["live_home_corners"])


if __name__ == "__main__":
    unittest.main()
