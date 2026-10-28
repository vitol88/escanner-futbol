import unittest

from models.live_odds import classify_market, extract_live_odds, score_pattern_context


class LiveOddsTests(unittest.TestCase):
    def test_extracts_live_odds_by_fixture_and_ignores_suspended_or_invalid(self):
        payload = {"response": [{
            "fixture": {"id": 123},
            "bookmakers": [{
                "name": "ExampleBook",
                "bets": [{"name": "Match Winner", "values": [
                    {"value": "Draw", "odd": "3.20"},
                    {"value": "Home", "odd": "1.32", "suspended": True},
                    {"value": "Away", "odd": "N/A"},
                ]}],
            }],
        }]}
        result = extract_live_odds(payload)
        self.assertEqual(len(result["123"]), 1)
        self.assertEqual(result["123"][0]["odd"], 3.2)
        self.assertEqual(result["123"][0]["bookmaker"], "ExampleBook")

    def test_classifies_draw_and_btts(self):
        self.assertEqual(
            classify_market({"market": "Match Winner", "value": "Draw", "odd": 3.2}),
            "Empate final",
        )
        self.assertEqual(
            classify_market({"market": "Both Teams Score", "value": "Yes", "odd": 1.8}),
            "Ambos equipos marcan: Sí",
        )

    def test_score_pattern_is_context_only(self):
        self.assertIn("Diferencia de un gol", score_pattern_context(0, 1))
        self.assertIn("no inferir empate", score_pattern_context(0, 2))


if __name__ == "__main__":
    unittest.main()
