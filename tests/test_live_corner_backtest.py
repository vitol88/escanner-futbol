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
        connection.execute("""
            CREATE TABLE live_corner_observations (
                fixture_id TEXT NOT NULL, league TEXT NOT NULL, team TEXT NOT NULL,
                venue TEXT NOT NULL, minute INTEGER NOT NULL,
                corners_for_after INTEGER NOT NULL, corners_against_after INTEGER NOT NULL,
                fixture_timestamp INTEGER
            )
        """)
        # Ten fixtures in chronological order, two mirrored perspectives and
        # two snapshots per fixture. The latest three fixtures form the test set.
        for number in range(10):
            for minute in (30, 65):
                for venue, team in (("home", "Home"), ("away", "Away")):
                    target = 4 if number < 7 else 8
                    league = "Premier League" if number % 2 == 0 else "La Liga"
                    connection.execute(
                        "INSERT INTO live_corner_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (f"fixture-{number}", league, team, venue, minute,
                         target, 3, 1_800_000_000 + number * 86400),
                    )
        connection.commit()
        connection.close()

    def test_chronological_split_has_no_fixture_leakage_and_reports_leagues(self):
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5,
            min_test_fixtures=2, min_league_test_fixtures=1,
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["split"]["fixture_overlap"], 0)
        self.assertEqual(result["split"]["method"], "chronological_fixture_timestamp_grouped")
        self.assertLess(
            result["split"]["train_latest_timestamp"],
            result["split"]["test_earliest_timestamp"],
        )
        self.assertEqual(result["split"]["train_fixtures"], 7)
        self.assertEqual(result["split"]["test_fixtures"], 3)
        self.assertIsNotNone(result["metrics"]["mae_remaining_corners"])
        self.assertEqual(result["benchmark"]["name"], "global_training_mean")
        self.assertEqual(result["benchmark"]["observations"], result["metrics"]["observations"])
        self.assertIsNotNone(result["benchmark"]["mae_remaining_corners"])
        self.assertIsNotNone(result["mae_improvement_vs_global_mean"])
        self.assertTrue(result["by_league_minute_bucket"])
        self.assertTrue(all("test_fixtures" in item for item in result["by_league_minute_bucket"]))
        self.assertEqual(
            {item["league"] for item in result["by_league"]},
            {"Premier League", "La Liga"},
        )


    def test_segmented_and_global_benchmark_use_training_data_only(self):
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5,
            min_test_fixtures=2, min_league_test_fixtures=1,
        )
        self.assertTrue(result["available"])
        # Seven earlier fixtures all have target=4; the three held-out
        # fixtures have target=8. Neither predictor may learn from test rows.
        self.assertAlmostEqual(result["benchmark"]["mae_remaining_corners"], 4.0)
        self.assertAlmostEqual(result["metrics"]["mae_remaining_corners"], 4.0)
        self.assertAlmostEqual(result["mae_improvement_vs_global_mean"], 0.0)

    def test_zero_error_global_reference_has_no_percentage_improvement(self):
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE live_corner_observations SET corners_for_after = 4")
        connection.commit()
        connection.close()
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5,
            min_test_fixtures=2, min_league_test_fixtures=1,
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["benchmark"]["mae_remaining_corners"], 0.0)
        self.assertIsNone(result["mae_improvement_vs_global_mean"])

    def test_fixtures_with_same_kickoff_timestamp_are_not_split(self):
        connection = sqlite3.connect(self.db)
        connection.execute(
            "UPDATE live_corner_observations SET fixture_timestamp = ? WHERE fixture_id IN (?, ?, ?, ?)",
            (1_800_000_000 + 9 * 86400, "fixture-6", "fixture-7", "fixture-8", "fixture-9"),
        )
        connection.commit()
        connection.close()
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5,
            min_test_fixtures=2, min_league_test_fixtures=1,
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["split"]["test_fixtures"], 4)
        self.assertEqual(result["split"]["train_fixtures"], 6)
        self.assertLess(
            result["split"]["train_latest_timestamp"],
            result["split"]["test_earliest_timestamp"],
        )
        self.assertEqual(result["split"]["fixture_overlap"], 0)


    def test_rolling_origin_uses_expanding_chronological_folds_without_leakage(self):
        connection = sqlite3.connect(self.db)
        for number in range(10, 30):
            for minute in (30, 65):
                for venue, team in (("home", "Home"), ("away", "Away")):
                    connection.execute(
                        "INSERT INTO live_corner_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (f"fixture-{number}", "Premier League", team, venue, minute,
                         5, 3, 1_800_000_000 + number * 86400),
                    )
        connection.commit()
        connection.close()
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5,
            min_test_fixtures=2, min_league_test_fixtures=1,
        )
        rolling = result["rolling_origin"]
        self.assertTrue(rolling["available"])
        self.assertEqual(rolling["fold_count"], 3)
        previous_test_start = 0
        for fold in rolling["folds"]:
            self.assertEqual(fold["fixture_overlap"], 0)
            self.assertLess(fold["train_latest_timestamp"], fold["test_earliest_timestamp"])
            self.assertGreater(fold["test_earliest_timestamp"], previous_test_start)
            previous_test_start = fold["test_earliest_timestamp"]
        self.assertIsNotNone(rolling["weighted_mae_remaining_corners"])
        self.assertEqual(
            rolling["method"], "expanding_window_chronological_folds"
        )

    def test_rolling_origin_reports_insufficient_history(self):
        result = run_live_corner_baseline_backtest(
            self.db, test_fraction=0.25, min_train_fixtures=5,
            min_test_fixtures=2, min_league_test_fixtures=1,
        )
        self.assertFalse(result["rolling_origin"]["available"])
        self.assertEqual(
            result["rolling_origin"]["reason"],
            "insufficient_fixtures_in_rolling_fold",
        )

    def test_missing_database_is_reported(self):
        result = run_live_corner_baseline_backtest(self.db.parent / "missing.sqlite3")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "database_not_found")

    def test_missing_or_incomplete_timestamps_are_not_scored(self):
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE live_corner_observations SET fixture_timestamp = NULL WHERE fixture_id = 'fixture-0'")
        connection.commit()
        connection.close()
        result = run_live_corner_baseline_backtest(self.db)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "incomplete_fixture_timestamps")

    def test_insufficient_history_is_not_scored(self):
        connection = sqlite3.connect(self.db)
        connection.execute("DELETE FROM live_corner_observations")
        connection.execute(
            "INSERT INTO live_corner_observations VALUES ('one', 'League', 'Team', 'home', 20, 1, 0, 1800000000)"
        )
        connection.commit()
        connection.close()
        result = run_live_corner_baseline_backtest(
            self.db, min_train_fixtures=5, min_test_fixtures=2
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "insufficient_fixture_count_for_chronological_split")

    def test_invalid_test_fraction_is_rejected(self):
        with self.assertRaises(ValueError):
            run_live_corner_baseline_backtest(self.db, test_fraction=0.8)


if __name__ == "__main__":
    unittest.main()
