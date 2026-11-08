from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_engine.prediction_ledger import append_prediction_records, load_prediction_records
from ai_engine.outcome_ledger import load_verified_outcomes, record_verified_outcome


class OutcomeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "ledger.sqlite3"
        append_prediction_records(self.path, [{
            "fixture_id": "123",
            "market": "Over 2.5 goals",
            "recorded_at": "2026-11-07T12:00:00Z",
            "probability": 0.7,
            "selection": "Over 2.5",
            "model_id": "test",
        }])
        self.prediction_id = load_prediction_records(self.path)[0]["prediction_id"]

    def _record(self, outcome, **kwargs):
        defaults = {
            "source": "official result",
            "verified_by": "reviewer",
            "verified_at": "2026-11-07T13:00:00Z",
        }
        defaults.update(kwargs)
        return record_verified_outcome(self.path, self.prediction_id, outcome, **defaults)

    def test_verified_outcome_is_separate_and_does_not_mutate_forecast(self):
        result = self._record(1, source="API-Football final score", verified_by="manual_review")
        self.assertTrue(result["inserted"])
        self.assertEqual(load_verified_outcomes(self.path)[self.prediction_id]["outcome"], 1)
        forecast = load_prediction_records(self.path)[0]
        self.assertIsNone(forecast["outcome"])
        self.assertFalse(forecast["outcome_verified"])

    def test_duplicate_verification_is_idempotent(self):
        first = self._record(0)
        second = self._record(0)
        self.assertTrue(first["inserted"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(load_verified_outcomes(self.path)), 1)

    def test_conflicting_result_requires_correction_reason_and_appends_event(self):
        self._record(0)
        with self.assertRaisesRegex(ValueError, "corrección"):
            self._record(1)
        corrected = self._record(
            1,
            correction_reason="Se corrigió el acta oficial",
            source="corrected official result",
            verified_at="2026-11-07T14:00:00Z",
        )
        self.assertTrue(corrected["inserted"])
        self.assertEqual(load_verified_outcomes(self.path)[self.prediction_id]["outcome"], 1)
        with sqlite3.connect(self.path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM prediction_outcome_events WHERE prediction_id = ?",
                (self.prediction_id,),
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_only_explicit_binary_integer_outcomes_are_accepted(self):
        for bad in (True, -1, 2, "1", None):
            with self.subTest(outcome=bad):
                with self.assertRaises(ValueError):
                    self._record(bad)

    def test_unknown_prediction_is_rejected(self):
        with self.assertRaises(KeyError):
            record_verified_outcome(
                self.path, "missing", 1, source="official", verified_by="reviewer"
            )

    def test_missing_verification_source_is_rejected(self):
        with self.assertRaises(ValueError):
            self._record(1, source="")

    def test_missing_verifier_is_rejected(self):
        with self.assertRaises(ValueError):
            self._record(1, verified_by="")

    def test_naive_verification_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            self._record(1, verified_at="2026-11-07T13:00:00")


if __name__ == "__main__":
    unittest.main()
