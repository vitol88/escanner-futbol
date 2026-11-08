import unittest

from ai_engine.supabase_prediction_ledger import (
    append_supabase_prediction_records,
    load_supabase_prediction_records,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class SupabasePredictionLedgerTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "recorded_at": "2026-11-08T18:00:00Z",
            "fixture_id": "fixture-123",
            "phase": "live",
            "market": "total_goals",
            "selection": "over",
            "probability": 0.72,
            "model_id": "live_goal_model",
            "snapshot_id": "fixture-123:67:1:0",
        }
        row.update(overrides)
        return row

    def test_append_counts_inserted_and_duplicate_rows(self):
        captured = {}
        def fake_post(url, **kwargs):
            captured.update(kwargs)
            return FakeResponse([{"prediction_id": "inserted-id"}])
        result = append_supabase_prediction_records(
            [self._row(), self._row(probability=1.5)],
            "https://example.supabase.co", "secret", post=fake_post,
        )
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(captured["params"]["on_conflict"], "prediction_id")
        self.assertIn("resolution=ignore-duplicates", captured["headers"]["Prefer"])

    def test_load_reads_paginated_json_records(self):
        calls = []
        def fake_get(url, **kwargs):
            calls.append(kwargs["headers"]["Range"])
            page = [{"record_json": self._row()}] if len(calls) == 1 else []
            return FakeResponse(page)
        loaded = load_supabase_prediction_records(
            "https://example.supabase.co", "secret", get=fake_get,
        )
        self.assertEqual(len(loaded), 1)
        self.assertEqual(calls, ["0-499"])

    def test_missing_credentials_fail_closed(self):
        with self.assertRaises(ValueError):
            load_supabase_prediction_records("", "")


if __name__ == "__main__":
    unittest.main()
