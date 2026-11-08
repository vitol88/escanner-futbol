import unittest

from ai_engine.prediction_schema import (
    normalize_prediction_record,
    normalize_prediction_records,
)


class PredictionSchemaTests(unittest.TestCase):
    def test_legacy_live_csv_row_is_readable_without_inventing_metadata(self):
        row = {
            "recorded_at": "2026-11-06T19:14:00",
            "fixture_id": "123",
            "league": "Liga A",
            "home": "Local",
            "away": "Visitante",
            "minute": "67",
            "score_home": "1",
            "score_away": "0",
            "market": "Over 8.5 corners",
            "estimated_probability_exploratory": "0.72",
            "outcome": "",
            "outcome_verified": "",
        }
        result = normalize_prediction_record(row)
        self.assertTrue(result["valid"])
        self.assertEqual(result["timestamp_status"], "naive_legacy")
        self.assertEqual(result["phase"], "unknown")
        self.assertEqual(result["probability"], 0.72)
        self.assertIsNone(result["line"])
        self.assertIsNone(result["model_version"])
        self.assertIsNone(result["outcome"])

    def test_aware_timestamp_is_normalized_to_utc(self):
        row = {
            "recorded_at": "2026-11-06T19:14:00-05:00",
            "fixture_id": 123,
            "market": "BTTS",
            "probability": 0.61,
        }
        result = normalize_prediction_record(row)
        self.assertTrue(result["valid"])
        self.assertEqual(result["recorded_at"], "2026-11-07T00:14:00Z")
        self.assertEqual(result["timestamp_status"], "aware_utc")

    def test_explicit_verified_binary_outcome_is_preserved_only_when_valid(self):
        base = {
            "recorded_at": "2026-11-06T19:14:00Z",
            "fixture_id": "123",
            "market": "Over 2.5 goals",
            "probability": 0.7,
        }
        verified = normalize_prediction_record({
            **base, "outcome": "1", "outcome_verified": "true"
        })
        unverified = normalize_prediction_record({
            **base, "outcome": "1", "outcome_verified": ""
        })
        malformed = normalize_prediction_record({
            **base, "outcome": "won", "outcome_verified": "true"
        })
        self.assertEqual(verified["outcome"], 1)
        self.assertTrue(verified["outcome_verified"])
        self.assertIsNone(unverified["outcome"])
        self.assertFalse(unverified["outcome_verified"])
        self.assertIsNone(malformed["outcome"])
        self.assertFalse(malformed["outcome_verified"])

    def test_invalid_required_fields_are_reported_not_repaired(self):
        result = normalize_prediction_record({
            "recorded_at": "not-a-date",
            "fixture_id": "",
            "market": "",
            "probability": 1.4,
        })
        self.assertFalse(result["valid"])
        self.assertEqual(
            set(result["validation_errors"]),
            {
                "missing_fixture_id",
                "missing_market",
                "invalid_or_missing_recorded_at",
                "invalid_or_missing_probability",
            },
        )

    def test_identity_distinguishes_lines_and_explicit_live_snapshots(self):
        base = {
            "recorded_at": "2026-11-06T19:14:00Z",
            "fixture_id": "123",
            "market": "Over corners",
            "probability": 0.7,
            "phase": "live",
            "minute": 67,
            "score_home": 1,
            "score_away": 0,
        }
        first = normalize_prediction_record({**base, "line": "8.5"})
        other_line = normalize_prediction_record({**base, "line": "9.5"})
        later_snapshot = normalize_prediction_record({
            **base, "line": "8.5", "snapshot_id": "stats-v2"
        })
        opposite_selection = normalize_prediction_record({
            **base, "line": "8.5", "selection": "Under"
        })
        self.assertNotEqual(first["prediction_id"], other_line["prediction_id"])
        self.assertNotEqual(first["prediction_id"], later_snapshot["prediction_id"])
        self.assertNotEqual(first["prediction_id"], opposite_selection["prediction_id"])

    def test_live_scanner_record_carries_common_contract_metadata(self):
        row = {
            "recorded_at": "2026-11-07T00:14:00Z",
            "fixture_id": 123,
            "league_id": 39,
            "league": "Premier League",
            "home": "Home",
            "away": "Away",
            "phase": "live",
            "minute": 67,
            "score_home": 1,
            "score_away": 0,
            "market": "Empate final",
            "market_type": "goals",
            "probability": 0.64,
            "estimated_probability_exploratory": 0.64,
            "model_id": "estimate_live_goal_markets",
            "source": "football_lab_live_scanner",
            "snapshot_id": "123:67:1:0",
            "outcome": "",
            "outcome_verified": "",
        }
        result = normalize_prediction_record(row)
        self.assertTrue(result["valid"])
        self.assertEqual(result["phase"], "live")
        self.assertEqual(result["league_id"], "39")
        self.assertEqual(result["market_type"], "goals")
        self.assertEqual(result["probability"], 0.64)
        self.assertEqual(result["model_id"], "estimate_live_goal_markets")
        self.assertEqual(result["source"], "football_lab_live_scanner")
        self.assertEqual(result["snapshot_id"], "123:67:1:0")
        self.assertIsNone(result["outcome"])

    def test_dataset_counts_duplicates_and_invalid_records(self):
        base = {
            "recorded_at": "2026-11-06T19:14:00Z",
            "fixture_id": "123",
            "market": "BTTS",
            "probability": 0.55,
        }
        result = normalize_prediction_records([base, dict(base), {"market": "bad"}])
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["invalid_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)


if __name__ == "__main__":
    unittest.main()
