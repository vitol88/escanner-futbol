import unittest

from ai_engine.settlement import resolve_binary_outcome


class SettlementTests(unittest.TestCase):
    def test_over_under_goals(self):
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Over 2.5",
            final_home_score=2, final_away_score=1,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Under 2.5",
            final_home_score=2, final_away_score=1,
        )["outcome"], 0)

    def test_result_and_draw(self):
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Home",
            final_home_score=2, final_away_score=0,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="draw", selection="Empate final",
            final_home_score=1, final_away_score=1,
        )["outcome"], 1)

    def test_actual_live_team_goal_labels_use_the_correct_side(self):
        local_pick = "América marcará al menos 1 gol (más de 0.5 goles del local)"
        away_pick = "Cali marcará al menos 1 gol (más de 0.5 goles del visitante)"
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection=local_pick,
            final_home_score=1, final_away_score=0,
        ), {"resolved": True, "outcome": 1, "reason": "final_team_score"})
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection=away_pick,
            final_home_score=2, final_away_score=0,
        )["outcome"], 0)
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection=away_pick,
            final_home_score=0, final_away_score=1,
        )["outcome"], 1)

    def test_btts(self):
        self.assertEqual(resolve_binary_outcome(
            market_type="btts", selection="Yes",
            final_home_score=1, final_away_score=1,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="btts", selection="No",
            final_home_score=2, final_away_score=0,
        )["outcome"], 1)

    def test_corner_and_card_totals(self):
        self.assertEqual(resolve_binary_outcome(
            market_type="corners", selection="Over 8.5",
            final_total_corners=9,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="yellow_cards", selection="Under 4.5",
            final_total_yellow_cards=3,
        )["outcome"], 1)

    def test_push_is_not_forced_into_binary_result(self):
        result = resolve_binary_outcome(
            market_type="goals", selection="Over 2.0",
            final_home_score=1, final_away_score=1,
        )
        self.assertFalse(result["resolved"])
        self.assertEqual(result["reason"], "push_requires_non_binary_settlement")

    def test_missing_or_invalid_data_is_withheld(self):
        for result in (
            resolve_binary_outcome(market_type="goals", selection="Over 2.5", final_home_score=1),
            resolve_binary_outcome(market_type="corners", selection="Over 8.5"),
            resolve_binary_outcome(market_type="goals", selection="Over 2.5", final_home_score=True, final_away_score=0),
            resolve_binary_outcome(market_type="yellow_cards", selection="Over 3.5", final_total_yellow_cards=-1),
        ):
            self.assertFalse(result["resolved"])

    def test_unsupported_selections_and_markets_are_withheld(self):
        self.assertFalse(resolve_binary_outcome(
            market_type="goals", selection="Home team scores first",
            final_home_score=2, final_away_score=1,
        )["resolved"])
        self.assertFalse(resolve_binary_outcome(
            market_type="corners", selection="Home Over 4.5",
            final_total_corners=10,
        )["resolved"])
        self.assertFalse(resolve_binary_outcome(
            market_type="cards", selection="Over 3.5",
            final_total_yellow_cards=5,
        )["resolved"])


if __name__ == "__main__":
    unittest.main()
