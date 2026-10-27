import unittest

from app import fixture_label, has_core_stats, safe_stat
from models.probabilities import estimate_live_goal_markets


class ScannerUnitTests(unittest.TestCase):
    def test_fixture_label_handles_missing_scores(self):
        fixture = {
            "teams": {
                "home": {"name": "A"},
                "away": {"name": "B"},
            },
            "goals": {"home": None, "away": 1},
            "fixture": {"status": {"elapsed": 33}},
            "league": {"name": "Liga X"},
        }
        label = fixture_label(fixture)
        self.assertIn("A", label)
        self.assertIn("B", label)
        self.assertIn("-–1", label)

    def test_safe_stat_finds_value_for_requested_team(self):
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"statistics": [{"type": "Corner Kicks", "value": 7}]},
        ]
        self.assertEqual(safe_stat(stats, "Corner Kicks", team_index=0), 4)
        self.assertEqual(safe_stat(stats, "Corner Kicks", team_index=1), 7)

    def test_safe_stat_does_not_fall_back_to_other_team(self):
        stats = [
            {"statistics": [{"type": "Total Shots", "value": None}]},
            {"statistics": [{"type": "Total Shots", "value": 7}]},
        ]
        self.assertIsNone(safe_stat(stats, "Total Shots", team_index=0))
        self.assertEqual(safe_stat(stats, "Total Shots", team_index=1), 7)

    def test_missing_core_stats_is_not_enough(self):
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"statistics": [{"type": "Total Shots", "value": 7}]},
        ]
        enough, missing = has_core_stats(stats)
        self.assertFalse(enough)
        self.assertIn("córners", missing)
        self.assertIn("tiros", missing)
        self.assertIn("tiros", missing)

    def test_team_specific_goal_thresholds_are_returned(self):
        data = {
            "minimum_matches_for_estimate": 1,
            "leagues": [{
                "country": "England",
                "country_aliases": ["Inglaterra"],
                "league": "Premier League",
                "aliases": [],
                "matches": 50,
                "avg_home_goals": 1.5,
                "avg_away_goals": 1.2,
            }],
        }
        estimate = estimate_live_goal_markets(
            country="England",
            league_name="Premier League",
            score_home=0,
            score_away=0,
            elapsed_minute=45,
            data=data,
        )
        self.assertTrue(estimate["available"])
        self.assertIn("2", estimate["home_final_goals_at_least"])
        self.assertIn("2", estimate["away_final_goals_at_least"])
        self.assertFalse(estimate["home_final_goals_at_least"]["2"]["already_settled"])
        self.assertGreaterEqual(estimate["home_final_goals_at_least"]["2"]["probability"], 0)
        self.assertLessEqual(estimate["home_final_goals_at_least"]["2"]["probability"], 1)

    def test_complete_core_stats_passes_gate(self):
        stats = [
            {"statistics": [
                {"type": "Corner Kicks", "value": 4},
                {"type": "Total Shots", "value": 7},
            ]},
            {"statistics": [
                {"type": "Corner Kicks", "value": 3},
                {"type": "Total Shots", "value": 5},
            ]},
        ]
        enough, missing = has_core_stats(stats)
        self.assertTrue(enough)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
