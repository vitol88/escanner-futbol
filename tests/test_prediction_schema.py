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
        self.assertEqual(result["schema_version"], "1.1")
        self.assertEqual(result["phase"], "live")
        self.assertEqual(result["league_id"], "39")
        self.assertEqual(result["market_type"], "goals")
        self.assertEqual(result["probability"], 0.64)
        self.assertEqual(result["model_id"], "estimate_live_goal_markets")
        self.assertIsNone(result["model_version"])
        self.assertEqual(result["source"], "football_lab_live_scanner")
        self.assertEqual(result["snapshot_id"], "123:67:1:0")
        self.assertIsNone(result["outcome"])

    def test_model_version_is_preserved_and_legacy_version_stays_unknown(self):
        base = {
            "recorded_at": "2026-11-07T00:14:00Z",
            "fixture_id": "model-version-fixture",
            "market": "Más de 8.5 córners",
            "market_type": "corners",
            "selection": "Más de 8.5 córners",
            "probability": 0.67,
            "phase": "live",
        }
        versioned = normalize_prediction_record({
            **base,
            "model_id": "live_corner_poisson_exploratory",
            "model_version": "live-corner-poisson-exploratory-v1",
        })
        legacy = normalize_prediction_record(base)
        self.assertEqual(versioned["model_id"], "live_corner_poisson_exploratory")
        self.assertEqual(versioned["model_version"], "live-corner-poisson-exploratory-v1")
        self.assertIsNone(legacy["model_id"])
        self.assertIsNone(legacy["model_version"])

    def test_verified_odds_metadata_is_preserved_for_auditing(self):
        result = normalize_prediction_record({
            "recorded_at": "2026-11-07T18:00:00Z",
            "fixture_id": "456",
            "market": "Empate final",
            "market_type": "draw",
            "selection": "Empate final",
            "probability": 0.64,
            "odds_decimal": 2.1,
            "odds_verified": True,
            "odds_bookmaker": "Casa de prueba",
            "odds_market": "Empate",
            "implied_probability": 0.4762,
            "estimated_edge": 0.1638,
            "expected_value": 0.344,
        })
        self.assertTrue(result["valid"])
        self.assertTrue(result["odds_verified"])
        self.assertEqual(result["odds_decimal"], 2.1)
        self.assertEqual(result["odds_bookmaker"], "Casa de prueba")
        self.assertEqual(result["odds_market"], "Empate")
        self.assertEqual(result["implied_probability"], 0.4762)
        self.assertEqual(result["estimated_edge"], 0.1638)
        self.assertEqual(result["expected_value"], 0.344)

    def test_csv_odds_metadata_is_parsed_as_finite_numbers(self):
        result = normalize_prediction_record({
            "recorded_at": "2026-11-07T18:00:00Z",
            "fixture_id": "789",
            "market": "Over 2.5 goles",
            "probability": "0.72",
            "odds_decimal": "2.10",
            "odds_verified": "true",
            "implied_probability": "0.47619",
            "estimated_edge": "0.24381",
            "expected_value": "0.512",
        })
        self.assertTrue(result["odds_verified"])
        self.assertEqual(result["odds_decimal"], 2.1)
        self.assertAlmostEqual(result["implied_probability"], 0.47619)
        self.assertAlmostEqual(result["estimated_edge"], 0.24381)
        self.assertEqual(result["expected_value"], 0.512)

    def test_invalid_odds_metadata_is_not_marked_verified(self):
        result = normalize_prediction_record({
            "recorded_at": "2026-11-07T18:00:00Z",
            "fixture_id": "790",
            "market": "Over 2.5 goles",
            "probability": 0.72,
            "odds_decimal": "NaN",
            "odds_verified": "true",
            "implied_probability": "Infinity",
            "estimated_edge": "not-a-number",
            "expected_value": "",
        })
        self.assertFalse(result["odds_verified"])
        self.assertIsNone(result["odds_decimal"])
        self.assertIsNone(result["implied_probability"])
        self.assertIsNone(result["estimated_edge"])
        self.assertIsNone(result["expected_value"])

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


    def test_selection_is_preserved_as_distinct_event_identity(self):
        base = {
            "recorded_at": "2026-11-08T18:00:00Z",
            "fixture_id": "fixture-selection",
            "market": "Total final: 3 goles o más",
            "market_type": "goals",
            "probability": 0.64,
            "model_id": "estimate_live_goal_markets",
            "snapshot_id": "fixture-selection:70:1:1",
        }
        over = normalize_prediction_record({**base, "selection": "Total final: 3 goles o más"})
        under = normalize_prediction_record({**base, "selection": "Total final: menos de 3 goles"})
        self.assertEqual(over["selection"], "Total final: 3 goles o más")
        self.assertNotEqual(over["prediction_id"], under["prediction_id"])


if __name__ == "__main__":
    unittest.main()
