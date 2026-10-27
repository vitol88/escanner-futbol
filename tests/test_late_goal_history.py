import unittest

from models.late_goal_history import estimate_late_goals_from_history


class LateGoalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for i in range(10):
            self.rows.append({
                "league": "Serie A", "team": "Roma", "minute": 70,
                "score_for": 2, "score_against": 1,
                "goals_for_after": 1 if i < 4 else 0,
                "goals_against_after": 1 if i < 2 else 0,
            })

    def test_exact_score_state_uses_empirical_frequencies(self):
        result = estimate_late_goals_from_history(
            self.rows, league="Serie A", team="Roma", minute=70,
            score_for=2, score_against=1, minimum_matches=8
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["matched_exact_score"])
        self.assertEqual(result["sample_size"], 10)
        self.assertAlmostEqual(result["prob_at_least_1_goal"], 0.4)
        self.assertAlmostEqual(result["prob_at_least_2_goals"], 0.2)
        self.assertAlmostEqual(result["prob_team_scores_again"], 0.4)

    def test_falls_back_to_team_league_minute_when_state_sample_small(self):
        result = estimate_late_goals_from_history(
            self.rows, league="Serie A", team="Roma", minute=70,
            score_for=1, score_against=0, minimum_matches=8
        )
        self.assertTrue(result["available"])
        self.assertFalse(result["matched_exact_score"])
        self.assertIn("Muestra por marcador insuficiente", result["reason"])

    def test_withholds_small_samples(self):
        result = estimate_late_goals_from_history(
            self.rows[:3], league="Serie A", team="Roma", minute=70,
            score_for=2, score_against=1, minimum_matches=8
        )
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
