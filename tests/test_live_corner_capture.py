import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ai_engine.live_corner_capture import (
    capture_live_corner_snapshot,
    count_live_corner_snapshots,
)


class LiveCornerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "capture.sqlite3"
        self.fixture = {
            "fixture": {
                "id": 501,
                "date": "2026-11-07T19:00:00+00:00",
                "status": {"short": "2H", "elapsed": 67},
            },
            "league": {"id": 39, "name": "Premier League"},
            "teams": {
                "home": {"id": 1, "name": "Arsenal"},
                "away": {"id": 2, "name": "Chelsea"},
            },
        }
        self.stats = [
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": "5"}]},
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": 3}]},
        ]
        self.stamp = datetime(2026, 11, 7, 19, 20, tzinfo=timezone.utc)

    def test_persists_snapshot_without_extra_api_data(self):
        result = capture_live_corner_snapshot(
            self.db, self.fixture, self.stats, captured_at=self.stamp
        )
        self.assertTrue(result["stored"])
        self.assertEqual(result["minute"], 67)
        self.assertEqual(result["home_corners"], 5)
        self.assertEqual(count_live_corner_snapshots(self.db), 1)

    def test_same_minute_is_upserted_monotonically(self):
        capture_live_corner_snapshot(self.db, self.fixture, self.stats, captured_at=self.stamp)
        updated_stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 6}]},
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
        ]
        capture_live_corner_snapshot(
            self.db, self.fixture, updated_stats, captured_at=self.stamp
        )
        lower_stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"statistics": [{"type": "Corner Kicks", "value": 2}]},
        ]
        capture_live_corner_snapshot(
            self.db, self.fixture, lower_stats, captured_at=self.stamp
        )
        import sqlite3
        with sqlite3.connect(self.db) as connection:
            row = connection.execute(
                "SELECT home_corners, away_corners FROM live_corner_capture_snapshots"
            ).fetchone()
        self.assertEqual(row, (6, 4))
        self.assertEqual(count_live_corner_snapshots(self.db), 1)

    def test_rejects_invalid_or_non_live_fixtures(self):
        bad_minute = {
            **self.fixture,
            "fixture": {**self.fixture["fixture"], "status": {"short": "2H", "elapsed": 0}},
        }
        finished = {
            **self.fixture,
            "fixture": {**self.fixture["fixture"], "status": {"short": "FT", "elapsed": 90}},
        }
        self.assertFalse(
            capture_live_corner_snapshot(self.db, bad_minute, self.stats)["stored"]
        )
        self.assertFalse(
            capture_live_corner_snapshot(self.db, finished, self.stats)["stored"]
        )
        self.assertEqual(count_live_corner_snapshots(self.db), 0)

    def test_rejects_missing_corner_counts(self):
        missing = [{"statistics": []}, {"statistics": []}]
        result = capture_live_corner_snapshot(self.db, self.fixture, missing)
        self.assertFalse(result["stored"])
        self.assertEqual(result["reason"], "corner_statistics_unavailable")


if __name__ == "__main__":
    unittest.main()
