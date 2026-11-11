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

    def test_real_spanish_goal_market_labels(self):
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Más de 2.5 goles",
            final_home_score=2, final_away_score=1,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Menos de 2,5 goles",
            final_home_score=1, final_away_score=0,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Gana local",
            final_home_score=2, final_away_score=0,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="goals", selection="Gana visitante",
            final_home_score=0, final_away_score=1,
        )["outcome"], 1)

    def test_real_spanish_corner_and_card_labels(self):
        self.assertEqual(resolve_binary_outcome(
            market_type="corners", selection="Más de 8.5 córners",
            final_total_corners=9,
        )["outcome"], 1)
        self.assertEqual(resolve_binary_outcome(
            market_type="yellow_cards", selection="Menos de 4.5 tarjetas amarillas",
            final_total_yellow_cards=3,
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


    def test_absolute_total_goals_threshold_labels(self):
        won = resolve_binary_outcome(
            market_type="goals",
            selection="Total final: 3 goles o más (+2 desde ahora)",
            final_home_score=2, final_away_score=1,
        )
        lost = resolve_binary_outcome(
            market_type="goals",
            selection="Total final: 4 goles o más (+3 desde ahora)",
            final_home_score=2, final_away_score=1,
        )
        self.assertEqual(won["outcome"], 1)
        self.assertEqual(lost["outcome"], 0)

    def test_dynamic_btts_labels(self):
        for label in (
            "Ambos equipos marcan (deben marcar ambos equipos)",
            "Ambos equipos marcan (falta que marque América)",
        ):
            result = resolve_binary_outcome(
                market_type="btts", selection=label,
                final_home_score=1, final_away_score=1,
            )
            self.assertEqual(result["outcome"], 1)

    def test_named_team_goal_threshold_uses_verified_team_side(self):
        result = resolve_binary_outcome(
            market_type="goals",
            selection="América: terminará con 2 goles o más",
            final_home_score=2, final_away_score=1,
            home_team_name="América", away_team_name="Cali",
        )
        self.assertEqual(result["outcome"], 1)
        unresolved = resolve_binary_outcome(
            market_type="goals",
            selection="América: terminará con 2 goles o más",
            final_home_score=2, final_away_score=1,
        )
        self.assertFalse(unresolved["resolved"])


    def test_prediction_rows_join_verified_outcomes_without_mutating_source(self):
        from ai_engine.settlement import settle_prediction_rows

        predictions = [
            {"prediction_id": "p1", "fixture_id": "101", "market_type": "goals",
             "selection": "Over 2.5", "probability": 0.8},
            {"prediction_id": "p2", "fixture_id": "101", "market_type": "btts",
             "selection": "Yes", "probability": 0.7},
            {"prediction_id": "p3", "fixture_id": "202", "market_type": "corners",
             "selection": "Over 8.5", "probability": 0.6},
        ]
        outcomes = {
            "101": {"final_home_score": 2, "final_away_score": 1,
                    "source": "api-football", "verified_at": "2026-11-11T12:00:00Z"},
            "202": {"final_home_score": 0, "final_away_score": 0,
                    "final_total_corners": None},
        }

        result = settle_prediction_rows(predictions, outcomes)

        self.assertEqual(result["settled_count"], 2)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["hit_count"], 2)
        self.assertEqual(result["miss_count"], 0)
        self.assertEqual({row["prediction_id"] for row in result["settled"]}, {"p1", "p2"})
        self.assertEqual(result["pending"][0]["settlement_status"], "pending_review")
        self.assertNotIn("outcome", predictions[0])
        self.assertNotIn("outcome_verified", predictions[0])

    def test_prediction_without_verified_fixture_result_stays_pending(self):
        from ai_engine.settlement import settle_prediction_rows

        result = settle_prediction_rows(
            [{"fixture_id": "missing", "market_type": "draw",
              "selection": "Empate final"}],
            {},
        )
        self.assertEqual(result["settled_count"], 0)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["pending"][0]["settlement_status"], "pending_final_result")

    def test_unsupported_prediction_market_is_not_guessed(self):
        from ai_engine.settlement import settle_prediction_rows

        result = settle_prediction_rows(
            [{"fixture_id": "1", "market_type": "first_goal",
              "selection": "Home scores first"}],
            {"1": {"final_home_score": 2, "final_away_score": 1}},
        )
        self.assertEqual(result["settled_count"], 0)
        self.assertEqual(result["pending"][0]["settlement_status"], "pending_review")


if __name__ == "__main__":
    unittest.main()
