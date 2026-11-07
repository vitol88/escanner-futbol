import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_engine.live_corner_capture import capture_live_corner_snapshot
from ai_engine.live_corner_finalize import finalize_live_corner_fixture
from ai_engine.live_corner_store import load_live_corner_history_from_sqlite


class LiveCornerFinalizeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "football_lab.sqlite3"
        self.fixture = {
            "fixture": {"id": 501, "status": {"short": "2H", "elapsed": 67}},
            "league": {"id": 39, "name": "Premier League"},
            "teams": {
                "home": {"id": 1, "name": "Arsenal"},
                "away": {"id": 2, "name": "Chelsea"},
            },
        }
        self.live_stats = [
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 5}]},
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": 3}]},
        ]
        self.final_fixture = {
            **self.fixture,
            "fixture": {"id": 501, "status": {"short": "FT", "elapsed": 90}},
        }
        self.final_stats = [
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": 7}]},
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 9}]},
        ]

    def _capture(self, minute, home, away):
        fixture = {
            **self.fixture,
            "fixture": {
                "id": 501,
                "status": {"short": "2H", "elapsed": minute},
            },
        }
        stats = [
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": home}]},
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": away}]},
        ]
        return capture_live_corner_snapshot(self.db, fixture, stats)

    def test_finalizes_both_team_perspectives_with_remaining_counts(self):
        self._capture(40, 3, 2)
        self._capture(67, 5, 3)
        result = finalize_live_corner_fixture(
            self.db, self.final_fixture, self.final_stats
        )
        rows = load_live_corner_history_from_sqlite(self.db)

        self.assertTrue(result["finalized"])
        self.assertEqual(result["snapshots_processed"], 2)
        self.assertEqual(result["observations_inserted"], 4)
        self.assertEqual(len(rows), 4)
        home_67 = next(row for row in rows if row["team"] == "Arsenal" and row["minute"] == 67)
        away_67 = next(row for row in rows if row["team"] == "Chelsea" and row["minute"] == 67)
        self.assertEqual(
            (home_67["corners_for"], home_67["corners_against"],
             home_67["corners_for_after"], home_67["corners_against_after"]),
            (5, 3, 4, 4),
        )
        self.assertEqual(
            (away_67["corners_for"], away_67["corners_against"],
             away_67["corners_for_after"], away_67["corners_against_after"]),
            (3, 5, 4, 4),
        )

    def test_repeat_finalization_is_idempotent(self):
        self._capture(67, 5, 3)
        first = finalize_live_corner_fixture(self.db, self.final_fixture, self.final_stats)
        second = finalize_live_corner_fixture(self.db, self.final_fixture, self.final_stats)
        self.assertEqual(first["observations_inserted"], 2)
        self.assertEqual(second["observations_inserted"], 0)
        self.assertEqual(len(load_live_corner_history_from_sqlite(self.db)), 2)

    def test_rejects_not_finished_or_missing_final_stats(self):
        self._capture(67, 5, 3)
        not_finished = {
            **self.final_fixture,
            "fixture": {"id": 501, "status": {"short": "2H", "elapsed": 89}},
        }
        missing = [
            {"team": {"id": 1}, "statistics": []},
            {"team": {"id": 2}, "statistics": []},
        ]
        self.assertEqual(
            finalize_live_corner_fixture(self.db, not_finished, self.final_stats)["reason"],
            "fixture_not_finished",
        )
        self.assertEqual(
            finalize_live_corner_fixture(self.db, self.final_fixture, missing)["reason"],
            "final_corner_statistics_unavailable",
        )
        self.assertEqual(load_live_corner_history_from_sqlite(self.db), [])

    def test_rejects_final_totals_below_any_captured_snapshot(self):
        self._capture(67, 5, 3)
        lower = [
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": 3}]},
        ]
        result = finalize_live_corner_fixture(self.db, self.final_fixture, lower)
        self.assertFalse(result["finalized"])
        self.assertEqual(result["reason"], "final_count_below_live_snapshot")
        self.assertEqual(load_live_corner_history_from_sqlite(self.db), [])

    def test_rejects_team_identity_mismatch(self):
        self._capture(67, 5, 3)
        mismatch = {
            **self.final_fixture,
            "teams": {
                "home": {"id": 1, "name": "Arsenal"},
                "away": {"id": 22, "name": "Different team"},
            },
        }
        mismatch_stats = [
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 9}]},
            {"team": {"id": 22}, "statistics": [{"type": "Corner Kicks", "value": 7}]},
        ]
        result = finalize_live_corner_fixture(self.db, mismatch, mismatch_stats)
        self.assertFalse(result["finalized"])
        self.assertEqual(result["reason"], "fixture_identity_mismatch")
        self.assertEqual(load_live_corner_history_from_sqlite(self.db), [])


if __name__ == "__main__":
    unittest.main()
