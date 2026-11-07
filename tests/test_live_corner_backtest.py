import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_engine.live_corner_backtest import run_live_corner_baseline_backtest


class LiveCornerBacktestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "history.sqlite3"
        connection = sqlite3.connect(self.db)
        connection.execute(
            """
            CREATE TABLE live_corner_observations (
                fixture_id TEXT NOT NULL, league TEXT NOT NULL, team TEXT NOT NULL,
                venue TEXT NOT NULL, minute INTEGER NOT NULL,
                corners_for_after INTEGER NOT NULL, corners_against_after INTEGER NOT NULL
            )
            """
        )
        test_ids, train_ids = [], []
        for number in range(1000):
            fixture_id = str(number)
            digest = hashlib.sha256(fixture_id.encode()).hexdigest()
            is_test = int(digest[:8], 16) / 0xFFFFFFFF < 0.25
            (test_ids if is_test else train_ids).append(fixture_id)
            if len(test_ids) >= 4 and len(train_ids) >= 8:
                break
        self.assertGreaterEqual(len(test_ids), 4)
        self.assertGreaterEqual(len(train_ids), 8)
        for fixture_id in test_ids + train_ids:
            target = 4 if fixture_id in train_ids else 8
            # Both team perspectives and two minute snapshots belong to the
            # same fixture and therefore must always stay in the same split.
            for minute in (30, 65):
                connection.execute(
                    "INSERT INTO live_corner_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (fixture_id, "League", "Home", "home", minute, target, 3),
                )
                connection.execute(
                    "INSERT INTO live_corner_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (fixture_id, "League", "Away", "away", minute, 3, target),
                )
        connection.commit()
        connection.close()

    def test_fixture_holdout_has_no_leakage_and_reports_metrics(self):
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5, min_test_fixtures=2
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["split"]["fixture_overlap"], 0)
        self.assertGreater(result["split"]["train_fixtures"], 0)
        self.assertGreater(result["split"]["test_fixtures"], 0)
        self.assertIsNotNone(result["metrics"]["mae_remaining_corners"])
        self.assertEqual(
            {row["minute_bucket"] for row in result["by_minute_bucket"]},
            {"16-30", "61-75"},
        )

    def test_missing_database_is_reported(self):
        missing = self.db.parent / "missing.sqlite3"
        result = run_live_corner_baseline_backtest(missing)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "database_not_found")

    def test_insufficient_history_is_not_scored(self):
        connection = sqlite3.connect(self.db)
        connection.execute("DELETE FROM live_corner_observations")
        connection.execute(
            "INSERT INTO live_corner_observations VALUES ('one', 'L', 'T', 'home', 20, 1, 0)"
        )
        connection.commit()
        connection.close()
        result = run_live_corner_baseline_backtest(
            self.db, min_train_fixtures=5, min_test_fixtures=2
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "insufficient_fixture_count_for_holdout")

    def test_invalid_test_fraction_is_rejected(self):
        with self.assertRaises(ValueError):
            run_live_corner_baseline_backtest(self.db, test_fraction=0.8)


if __name__ == "__main__":
    unittest.main()
