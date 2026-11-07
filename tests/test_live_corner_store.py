import csv
import tempfile
import unittest
from pathlib import Path

from ai_engine.live_corner_store import (
    analyze_with_persisted_live_corner_history,
    load_live_corner_history_from_sqlite,
    sync_live_corner_history_to_sqlite,
)


class LiveCornerStoreTests(unittest.TestCase):
    def _write_csv(self, path, rows):
        columns = [
            "fixture_id", "league", "team", "venue", "minute",
            "corners_for", "corners_against",
            "corners_for_after", "corners_against_after",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def _row(self, fixture_id="1001", **overrides):
        row = {
            "fixture_id": fixture_id,
            "league": "Premier League",
            "team": "Arsenal",
            "venue": "home",
            "minute": "67",
            "corners_for": "5",
            "corners_against": "3",
            "corners_for_after": "1",
            "corners_against_after": "0",
        }
        row.update(overrides)
        return row

    def test_sync_persists_only_valid_rows_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "history.csv"
            db_path = Path(folder) / "ledger.sqlite3"
            self._write_csv(csv_path, [
                self._row(),
                self._row(fixture_id="1002"),
                self._row(fixture_id="1003", minute="0"),
                self._row(),
            ])

            first = sync_live_corner_history_to_sqlite(db_path, csv_path)
            second = sync_live_corner_history_to_sqlite(db_path, csv_path)
            stored = load_live_corner_history_from_sqlite(db_path)

        self.assertEqual(first["valid"], 2)
        self.assertEqual(first["invalid"], 1)
        self.assertEqual(first["duplicates"], 1)
        self.assertEqual(first["persisted"], 2)
        self.assertEqual(second["persisted"], 0)
        self.assertEqual(second["already_stored"], 2)
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["venue"], "home")

    def test_missing_csv_keeps_previously_persisted_history(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "history.csv"
            db_path = Path(folder) / "ledger.sqlite3"
            self._write_csv(csv_path, [self._row()])
            sync_live_corner_history_to_sqlite(db_path, csv_path)

            report = sync_live_corner_history_to_sqlite(
                db_path, Path(folder) / "missing.csv"
            )
            stored = load_live_corner_history_from_sqlite(db_path)

        self.assertFalse(report["available"])
        self.assertEqual(len(stored), 1)

    def test_bridge_passes_sqlite_rows_to_pipeline_without_enabling_signals(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "history.csv"
            db_path = Path(folder) / "ledger.sqlite3"
            rows = [self._row(fixture_id=str(2000 + index)) for index in range(8)]
            self._write_csv(csv_path, rows)
            features = {
                "fixture_id": 101,
                "league_id": 39,
                "league_name": "Premier League",
                "home_team_id": 1,
                "away_team_id": 2,
                "teams": {"home": "Arsenal", "away": "Chelsea"},
                "goals": {},
                "corners": {"live_home_corners": 5, "live_away_corners": 3},
                "live": {"minute": 67},
            }
            result = analyze_with_persisted_live_corner_history(
                db_path, csv_path, features, minimum_live_corner_sample=8
            )

        self.assertEqual(result["history_observations"], 8)
        self.assertEqual(result["history_sync"]["persisted"], 8)
        self.assertIn("live_remaining_corners", result["analysis"]["models"])
        self.assertFalse(result["analysis"]["policy"]["betting_signals_enabled"])
        self.assertFalse(result["analysis"]["policy"]["recommendations_enabled"])


if __name__ == "__main__":
    unittest.main()
