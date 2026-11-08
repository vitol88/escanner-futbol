import unittest

from ai_engine.opportunity_engine import evaluate_opportunity, evaluate_candidates, classify_goal_tip_market


class OpportunityEngineTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "market": "corners",
            "selection": "Over 8.5",
            "probability": 0.62,
            "odds": 1.75,
            "odds_verified": True,
            "fixture_id": 12345,
            "fixture": "Home vs Away",
            "minute": 63,
            "score": "1-0",
            "bookmaker": "TestBook",
        }

    def test_goal_tip_market_classification(self):
        self.assertEqual(classify_goal_tip_market("Empate final"), "draw")
        self.assertEqual(classify_goal_tip_market("Ambos equipos marcan (falta que marque Local)"), "btts")
        self.assertEqual(classify_goal_tip_market("Total final: 2 goles o más"), "goals")

    def test_positive_value_candidate_is_eligible(self):
        result = evaluate_opportunity(self.base)
        self.assertTrue(result["eligible"])
        self.assertGreater(result["expected_value"], 0.02)

    def test_unverified_price_is_rejected(self):
        candidate = {**self.base, "odds_verified": False}
        result = evaluate_opportunity(candidate)
        self.assertFalse(result["eligible"])
        self.assertIn("odds_not_verified", result["reasons"])

    def test_bad_probability_is_rejected(self):
        candidate = {**self.base, "probability": 1.2}
        result = evaluate_opportunity(candidate)
        self.assertFalse(result["eligible"])
        self.assertIn("invalid_probability", result["reasons"])

    def test_wrong_market_selection_is_rejected(self):
        candidate = {**self.base, "market": "cards"}
        result = evaluate_opportunity(candidate)
        self.assertFalse(result["eligible"])
        self.assertIn("unsupported_market", result["reasons"])

    def test_negative_value_is_not_returned(self):
        candidate = {**self.base, "probability": 0.40}
        self.assertEqual(evaluate_candidates([candidate]), [])


if __name__ == "__main__":
    unittest.main()
