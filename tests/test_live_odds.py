import unittest

from models.live_odds import best_live_odds_by_market, classify_market, extract_live_odds, match_goal_tip_to_live_odds, numerology_context, score_pattern_context


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

    def test_best_live_odds_keeps_highest_price_and_bookmaker_per_market(self):
        rows = [
            {"market": "Match Winner", "value": "Draw", "odd": 2.80, "bookmaker": "Casa A"},
            {"market": "Match Winner", "value": "Draw", "odd": 3.05, "bookmaker": "Casa B"},
            {"market": "Both Teams Score", "value": "Yes", "odd": 1.72, "bookmaker": "Casa C"},
        ]
        best = best_live_odds_by_market(rows)
        by_market = {row["market_label"]: row for row in best}
        self.assertEqual(by_market["Empate final"]["odd"], 3.05)
        self.assertEqual(by_market["Empate final"]["bookmaker"], "Casa B")
        self.assertEqual(by_market["Ambos equipos marcan: Sí"]["bookmaker"], "Casa C")

    def test_matches_goal_tips_only_to_real_odds_in_allowed_bands_with_edge(self):
        rows = [
            {"market": "Over/Under", "value": "Over 1.5", "odd": 1.55, "bookmaker": "Casa A"},
            {"market": "Over/Under", "value": "Over 1.5", "handicap": "1.5", "odd": 1.58, "bookmaker": "Casa B"},
            {"market": "Match Winner", "value": "Draw", "odd": 1.65, "bookmaker": "Casa C"},
        ]
        matched = match_goal_tip_to_live_odds(
            "Total final: 2 goles o más (+2 desde ahora)", 0.70, rows
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["bookmaker"], "Casa B")
        self.assertEqual(matched["odd"], 1.58)
        self.assertIsNone(match_goal_tip_to_live_odds("Empate final", 0.70, rows))

    def test_withholds_unmapped_or_low_edge_goal_tips(self):
        rows = [{"market": "Match Winner", "value": "Draw", "odd": 1.50, "bookmaker": "Casa A"}]
        self.assertIsNone(match_goal_tip_to_live_odds("Empate final", 0.60, rows))
        self.assertIsNone(match_goal_tip_to_live_odds("Local marcará al menos 1 gol", 0.90, rows))

    def test_numerology_matches_score_to_corners_and_cards_within_one(self):
        self.assertTrue(numerology_context(1, 0, home_yellows=1, away_yellows=1))
        self.assertTrue(numerology_context(4, 2, home_corners=4, away_corners=3))
        self.assertEqual(numerology_context(1, 0, home_corners=7, away_corners=2), [])
        self.assertEqual(numerology_context(1, 0), [])

    def test_score_pattern_is_context_only(self):
        self.assertIn("Diferencia de un gol", score_pattern_context(0, 1))
        self.assertIn("no inferir empate", score_pattern_context(0, 2))


if __name__ == "__main__":
    unittest.main()
