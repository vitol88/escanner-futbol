import unittest
from ai_engine.card_model import estimate_prematch_yellow_cards

class PrematchYellowCardModelTests(unittest.TestCase):
    def setUp(self):
        self.features = {"league_id": 140, "home_team_id": 1, "away_team_id": 2,
                          "teams": {"home": "Home FC", "away": "Away FC"}, "referee": "Referee A"}
        self.rows = []
        for i in range(5):
            self.rows.append({"league_id": 140, "home_team_id": 1, "away_team_id": 10+i,
                              "home_yellow_cards": 2, "away_yellow_cards": 1,
                              "referee": "Referee A" if i < 4 else "Referee B"})
            self.rows.append({"league_id": 140, "home_team_id": 20+i, "away_team_id": 2,
                              "home_yellow_cards": 1, "away_yellow_cards": 3,
                              "referee": "Referee A" if i < 4 else "Referee B"})

    def test_venue_rates_and_lines(self):
        result = estimate_prematch_yellow_cards(self.features, self.rows)
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["expected_yellow_cards"]["home"], 1.5)
        self.assertAlmostEqual(result["expected_yellow_cards"]["away"], 2.0)
        self.assertAlmostEqual(result["expected_yellow_cards"]["total"], 3.5)
        self.assertIn(4.5, result["probability_over"])
        self.assertFalse(result["calibrated"])

    def test_referee_needs_minimum_sample(self):
        result = estimate_prematch_yellow_cards(self.features, self.rows, minimum_referee_matches=9)
        self.assertFalse(result["referee"]["used"])
        self.assertEqual(result["referee"]["factor"], 1.0)

    def test_referee_adjustment_is_shrunken_and_capped(self):
        rows = self.rows + [{"league_id": 140, "home_team_id": 100+i, "away_team_id": 200+i,
                             "home_yellow_cards": 4, "away_yellow_cards": 4, "referee": "Referee A"}
                            for i in range(10)]
        result = estimate_prematch_yellow_cards(self.features, rows)
        self.assertTrue(result["referee"]["used"])
        self.assertGreater(result["referee"]["factor"], 1.0)
        self.assertLessEqual(result["referee"]["factor"], 1.25)

    def test_ignores_other_leagues_and_missing_values(self):
        rows = self.rows + [
            {"league_id": 999, "home_team_id": 1, "away_team_id": 50, "home_yellow_cards": 9, "away_yellow_cards": 9},
            {"league_id": 140, "home_team_id": 1, "away_team_id": 51, "home_yellow_cards": None, "away_yellow_cards": 8},
        ]
        result = estimate_prematch_yellow_cards(self.features, rows)
        self.assertTrue(result["available"])
        self.assertEqual(result["sample"]["home_team_venue"], 5)

    def test_abstains_on_insufficient_samples_or_missing_identity(self):
        result = estimate_prematch_yellow_cards(self.features, self.rows[:4])
        self.assertFalse(result["available"])
        self.assertIn("Muestra insuficiente", result["reason"])
        self.assertFalse(estimate_prematch_yellow_cards({"league_id": 140}, self.rows)["available"])

if __name__ == "__main__":
    unittest.main()
