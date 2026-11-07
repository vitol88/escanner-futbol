import unittest

from ai_engine.coverage import build_data_coverage_report


class DataCoverageTests(unittest.TestCase):
    def _features(self):
        return {
            "fixture_id": 900,
            "league_id": 39,
            "league_name": "Premier League",
            "home_team_id": 1,
            "away_team_id": 2,
            "teams": {"home": "Arsenal", "away": "Chelsea"},
            "referee": "Ref A",
            "goals": {"home_goal_sample": 7, "away_goal_sample": 4},
            "corners": {"home_corner_sample": 8, "away_corner_sample": 6},
            "cards": {},
            "live": {"minute": 67},
            "data_quality": {},
        }

    def _card_rows(self):
        return [
            {"league_id": 39, "home_team_id": 1, "away_team_id": 3,
             "home_yellow_cards": 2, "away_yellow_cards": 1, "referee": "Ref A"},
            {"league_id": 39, "home_team_id": 4, "away_team_id": 2,
             "home_yellow_cards": 3, "away_yellow_cards": 2, "referee": "Ref B"},
            {"league_id": 39, "home_team_id": 1, "away_team_id": 5,
             "home_yellow_cards": 1, "away_yellow_cards": 2, "referee": "Ref A"},
            {"league_id": 39, "home_team_id": 6, "away_team_id": 2,
             "home_yellow_cards": 2, "away_yellow_cards": 3, "referee": "Ref A"},
            {"league_id": 140, "home_team_id": 1, "away_team_id": 2,
             "home_yellow_cards": 5, "away_yellow_cards": 5, "referee": "Ref A"},
        ]

    def test_reports_samples_and_sufficiency_separately(self):
        report = build_data_coverage_report(
            self._features(), {"card_history_rows": self._card_rows()},
            minimum_team_sample=2, minimum_referee_sample=3,
        )
        self.assertTrue(report["ready"]["prematch_goals"] is False)
        self.assertTrue(report["markets"]["prematch_goals"]["home"]["sufficient"])
        self.assertEqual(report["markets"]["prematch_goals"]["away"]["status"], "partial")
        self.assertTrue(report["ready"]["prematch_corners"])
        self.assertTrue(report["ready"]["prematch_yellow_cards"])
        self.assertEqual(report["markets"]["prematch_yellow_cards"]["home_team_at_home"]["sample"], 2)
        self.assertEqual(report["markets"]["prematch_yellow_cards"]["away_team_away"]["sample"], 2)
        self.assertEqual(report["markets"]["prematch_yellow_cards"]["referee"]["sample"], 3)
        self.assertFalse(report["ready"]["referee_adjustment"])
        self.assertFalse(report["markets"]["prematch_yellow_cards"]["league_referee_prior"]["available"])

    def test_live_corner_coverage_uses_league_team_venue_and_exact_minute(self):
        rows = [
            {"league": "Premier League", "team": "Arsenal", "venue": "home", "minute": 67,
             "corners_for": 5, "corners_against": 2, "corners_for_after": 1, "corners_against_after": 0},
            {"league": "Premier League", "team": "Arsenal", "venue": "home", "minute": 67,
             "corners_for": 4, "corners_against": 2, "corners_for_after": 0, "corners_against_after": 1},
            {"league": "Premier League", "team": "Arsenal", "venue": "home", "minute": 68,
             "corners_for": 5, "corners_against": 2, "corners_for_after": 1, "corners_against_after": 0},
            {"league": "Premier League", "team": "Chelsea", "venue": "away", "minute": 67,
             "corners_for": 2, "corners_against": 5, "corners_for_after": 1, "corners_against_after": 1},
            {"league": "La Liga", "team": "Arsenal", "venue": "home", "minute": 67,
             "corners_for": 5, "corners_against": 2, "corners_for_after": 1, "corners_against_after": 0},
        ]
        report = build_data_coverage_report(
            self._features(), {}, live_corner_history_rows=rows,
            minimum_live_corner_sample=2,
        )
        self.assertEqual(report["markets"]["live_remaining_corners"]["home"]["sample"], 2)
        self.assertEqual(report["markets"]["live_remaining_corners"]["away"]["sample"], 1)
        self.assertTrue(report["ready"]["live_remaining_corners"])

    def test_missing_history_is_missing_not_zero_confidence(self):
        report = build_data_coverage_report(self._features(), {})
        self.assertEqual(report["markets"]["prematch_yellow_cards"]["home_team_at_home"]["status"], "missing")
        self.assertEqual(report["markets"]["live_remaining_corners"]["home"]["status"], "missing")
        self.assertFalse(report["ready"]["prematch_goals"])
        self.assertFalse(report["ready"]["prematch_corners"])
        self.assertFalse(report["ready"]["prematch_yellow_cards"])

    def test_ignores_invalid_and_other_league_card_rows(self):
        rows = self._card_rows() + [
            {"league_id": 39, "home_team_id": 1, "away_team_id": 2,
             "home_yellow_cards": None, "away_yellow_cards": 2, "referee": "Ref A"},
        ]
        report = build_data_coverage_report(
            self._features(), {"card_history_rows": rows},
            minimum_team_sample=1, minimum_referee_sample=1,
        )
        self.assertEqual(report["markets"]["prematch_yellow_cards"]["home_team_at_home"]["sample"], 2)
        self.assertEqual(report["markets"]["prematch_yellow_cards"]["away_team_away"]["sample"], 2)


if __name__ == "__main__":
    unittest.main()
