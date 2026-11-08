import unittest
from datetime import datetime, timezone
from ai_engine.supabase_analysis_snapshots import (
    build_analysis_snapshot, append_supabase_analysis_snapshots,
)

class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload

class AnalysisSnapshotTests(unittest.TestCase):
    def test_snapshot_is_idempotent_for_same_five_minute_state(self):
        moment = datetime(2026, 11, 8, 18, 1, tzinfo=timezone.utc)
        args = dict(fixture_id=123, analysis_type="goals",
                    match={"minute": 67, "home_score": 1, "away_score": 0},
                    inputs={"shots": {"home": 5}}, outputs={"expected_goals_remaining": 0.8})
        a = build_analysis_snapshot(**args, recorded_at=moment)
        b = build_analysis_snapshot(**args, recorded_at=moment)
        self.assertEqual(a["snapshot_id"], b["snapshot_id"])
        self.assertEqual(a["outputs"]["expected_goals_remaining"], 0.8)

    def test_different_analysis_types_have_distinct_ids(self):
        base = dict(fixture_id=123, match={"minute": 20}, inputs={}, outputs={})
        a = build_analysis_snapshot(analysis_type="goals", **base)
        b = build_analysis_snapshot(analysis_type="h2h", **base)
        self.assertNotEqual(a["snapshot_id"], b["snapshot_id"])

    def test_append_ignores_duplicates(self):
        captured = {}
        def post(url, **kwargs):
            captured.update(kwargs)
            return FakeResponse([{"snapshot_id": "one"}])
        row = {"snapshot_id":"one","fixture_id":"123","recorded_at":"2026-11-08T18:00:00Z",
               "analysis_type":"goals","match":{},"inputs":{},"outputs":{}}
        result = append_supabase_analysis_snapshots([row,row],"https://example.supabase.co","secret",post=post)
        self.assertEqual(result, {"received":2,"inserted":1,"duplicates":1})
        self.assertEqual(captured["params"]["on_conflict"], "snapshot_id")

if __name__ == "__main__": unittest.main()
