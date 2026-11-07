import unittest

from ai_engine.forecast_records import build_corner_prediction_records


class CornerForecastRecordTests(unittest.TestCase):
    def _fixture(self):
        return {
            "fixture_id": 987,
            "league_id": 39,
            "league": "Premier League",
            "home": "Home FC",
            "away": "Away FC",
        }

    def test_prematch_maps_total_and_team_markets_to_canonical_records(self):
        model = {
            "available": True,
            "model_version": "0.1.0",
            "probability_total_corners": {
                "8.5": {"over": 0.63, "under": 0.37},
            },
            "probability_team_corners": {
                "home": {"4.5": {"over": 0.55, "under": 0.45}},
                "away": {"3.5": {"over": 0.51, "under": 0.49}},
            },
        }
        records = build_corner_prediction_records(
            model, self._fixture(), phase="pre_match",
            recorded_at="2026-11-07T12:00:00Z",
        )
        self.assertEqual(len(records), 6)
        total_over = next(row for row in records if row["market"] == "total_corners" and row["selection"] == "over")
        self.assertEqual(total_over["line"], "8.5")
        self.assertEqual(total_over["probability"], 0.63)
        self.assertEqual(total_over["model_id"], "prematch_corner_poisson")
        self.assertEqual(total_over["fixture_id"], "987")
        self.assertTrue(all(row["valid"] and row["phase"] == "pre_match" for row in records))

    def test_live_maps_only_available_remaining_corner_probabilities(self):
        model = {
            "available": True,
            "model_version": "0.1.0",
            "probability_remaining_at_least_1": 0.72,
            "probability_remaining_at_least_2": None,
        }
        records = build_corner_prediction_records(
            model, self._fixture(), phase="live", minute=67,
            score_home=1, score_away=0, snapshot_id="fx987-m67-1-0",
            recorded_at="2026-11-07T12:00:00Z",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["market"], "remaining_corners")
        self.assertEqual(records[0]["line"], "0.5")
        self.assertEqual(records[0]["minute"], 67)
        self.assertEqual(records[0]["score_home"], 1)

    def test_unavailable_or_invalid_model_output_produces_no_records(self):
        self.assertEqual(build_corner_prediction_records(
            {"available": False}, self._fixture(), phase="pre_match"
        ), [])
        model = {"available": True, "probability_total_corners": {"8.5": {"over": 1.2}}}
        self.assertEqual(build_corner_prediction_records(
            model, self._fixture(), phase="pre_match"
        ), [])

    def test_unknown_phase_or_missing_fixture_is_rejected(self):
        self.assertEqual(build_corner_prediction_records(
            {"available": True}, self._fixture(), phase="unknown"
        ), [])
        self.assertEqual(build_corner_prediction_records(
            {"available": True}, {}, phase="live"
        ), [])


if __name__ == "__main__":
    unittest.main()
