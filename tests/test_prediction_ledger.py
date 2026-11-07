import tempfile
import unittest
from pathlib import Path

from ai_engine.prediction_ledger import append_prediction_records, load_prediction_records


class PredictionLedgerTests(unittest.TestCase):
    def _record(self, **overrides):
        row = {
            "recorded_at": "2026-11-07T18:00:00Z",
            "fixture_id": "fixture-123",
            "phase": "live",
            "minute": 67,
            "score_home": 1,
            "score_away": 0,
            "market": "total_goals",
            "selection": "over",
            "line": "2.5",
            "probability": 0.72,
            "model_id": "live_goal_model",
            "model_version": "0.1.0",
            "snapshot_id": "fixture-123:67:1:0",
            "source": "unit_test",
        }
        row.update(overrides)
        return row

    def test_append_is_idempotent_by_prediction_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            row = self._record()
            first = append_prediction_records(path, [row])
            second = append_prediction_records(path, [row])
            saved = load_prediction_records(path)
            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["duplicates"], 1)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["probability"], 0.72)

    def test_distinct_live_snapshots_are_both_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            first = self._record()
            second = self._record(minute=68, snapshot_id="fixture-123:68:1:0",
                                  recorded_at="2026-11-07T18:01:00Z")
            result = append_prediction_records(path, [first, second])
            self.assertEqual(result["inserted"], 2)
            self.assertEqual(len(load_prediction_records(path)), 2)

    def test_invalid_rows_are_skipped_without_corrupting_valid_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            result = append_prediction_records(path, [
                self._record(),
                self._record(probability=1.5),
                {"fixture_id": "missing-required-fields"},
            ])
            self.assertEqual(result["valid"], 1)
            self.assertEqual(result["invalid"], 2)
            self.assertEqual(result["inserted"], 1)
            self.assertEqual(len(load_prediction_records(path)), 1)

    def test_verified_outcome_is_only_stored_when_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            row = self._record(outcome="1", outcome_verified="false")
            append_prediction_records(path, [row])
            saved = load_prediction_records(path)[0]
            self.assertIsNone(saved["outcome"])
            self.assertFalse(saved["outcome_verified"])


if __name__ == "__main__":
    unittest.main()
