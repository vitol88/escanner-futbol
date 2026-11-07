import unittest

from ai_engine.forecast_records import (
    build_corner_prediction_records,
    build_goal_prediction_records,
    build_yellow_card_prediction_records,
)


class ForecastRecordTests(unittest.TestCase):
    def _fixture(self):
        return {"fixture_id": 987, "league_id": 39, "league": "Premier League",
                "home": "Home FC", "away": "Away FC"}

    def test_prematch_corners_maps_total_and_team_markets(self):
        model = {"available": True, "model_version": "0.1.0",
                 "probability_total_corners": {"8.5": {"over": 0.63, "under": 0.37}},
                 "probability_team_corners": {
                     "home": {"4.5": {"over": 0.55, "under": 0.45}},
                     "away": {"3.5": {"over": 0.51, "under": 0.49}}}}
        records = build_corner_prediction_records(model, self._fixture(), phase="pre_match",
                                                   recorded_at="2026-11-07T12:00:00Z")
        self.assertEqual(len(records), 6)
        row = next(r for r in records if r["market"] == "total_corners" and r["selection"] == "over")
        self.assertEqual((row["line"], row["probability"], row["model_id"]), ("8.5", 0.63, "prematch_corner_poisson"))
        self.assertTrue(all(r["valid"] and r["phase"] == "pre_match" for r in records))

    def test_live_corners_maps_only_explicit_remaining_probabilities(self):
        model = {"available": True, "model_version": "0.1.0",
                 "probability_remaining_at_least_1": 0.72, "probability_remaining_at_least_2": None}
        records = build_corner_prediction_records(model, self._fixture(), phase="live", minute=67,
            score_home=1, score_away=0, snapshot_id="fx987-m67-1-0",
            recorded_at="2026-11-07T12:00:00Z")
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["market"], records[0]["line"], records[0]["minute"]),
                         ("remaining_corners", "0.5", 67))

    def test_goals_maps_total_result_and_btts_probabilities(self):
        model = {"available": True, "model_version": "0.1.0",
                 "probability_total_goals": {"2.5": {"over": 0.6, "under": 0.4}},
                 "probability_1x2": {"home": 0.5, "draw": 0.25, "away": 0.25},
                 "probability_btts": 0.58,
                 "expected_total_goals": 2.7}
        records = build_goal_prediction_records(model, self._fixture(),
                                                 recorded_at="2026-11-07T12:00:00Z")
        self.assertEqual(len(records), 6)
        self.assertNotIn("expected_total_goals", records[0])
        self.assertEqual({r["market"] for r in records},
                         {"total_goals", "match_result", "both_teams_to_score"})
        btts = next(r for r in records if r["market"] == "both_teams_to_score")
        self.assertEqual((btts["selection"], btts["probability"]), ("yes", 0.58))

    def test_cards_maps_only_explicit_over_probabilities(self):
        model = {"available": True, "model": "experimental_poisson_yellow_cards",
                 "probability_over": {2.5: 0.7, 3.5: 0.55},
                 "expected_yellow_cards": {"total": 4.1}}
        records = build_yellow_card_prediction_records(model, self._fixture(),
                                                        recorded_at="2026-11-07T12:00:00Z")
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["market"] == "total_yellow_cards" and r["selection"] == "over"
                            for r in records))
        self.assertEqual(records[0]["model_id"], "prematch_yellow_card_poisson")

    def test_unavailable_invalid_probabilities_and_missing_fixture_are_rejected(self):
        self.assertEqual(build_goal_prediction_records({"available": False}, self._fixture()), [])
        self.assertEqual(build_yellow_card_prediction_records(
            {"available": True, "probability_over": {"2.5": 1.2}}, self._fixture()), [])
        self.assertEqual(build_corner_prediction_records(
            {"available": True}, {}, phase="live"), [])
        self.assertEqual(build_corner_prediction_records(
            {"available": True}, self._fixture(), phase="unknown"), [])


if __name__ == "__main__":
    unittest.main()
