import csv
import tempfile
import unittest
from pathlib import Path

from ai_engine.live_corner_history import load_live_corner_history_csv


class LiveCornerHistoryLoaderTests(unittest.TestCase):
    def write_csv(self, path, rows, columns=None):
        columns = columns or [
            "fixture_id", "league", "team", "venue", "minute",
            "corners_for", "corners_against",
            "corners_for_after", "corners_against_after",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, **overrides):
        result = {
            "fixture_id": "1001", "league": "Premier League",
            "team": "Arsenal", "venue": "home", "minute": "67",
            "corners_for": "5", "corners_against": "2",
            "corners_for_after": "1", "corners_against_after": "0",
        }
        result.update(overrides)
        return result

    def test_loads_valid_rows_and_normalizes_venue(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.csv"
            self.write_csv(path, [self.row(venue="local")])
            result = load_live_corner_history_csv(path)
        self.assertTrue(result["available"])
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["rows"][0]["venue"], "home")
        self.assertEqual(result["rows"][0]["minute"], 67)

    def test_rejects_invalid_rows_and_deduplicates_fixture_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.csv"
            self.write_csv(path, [
                self.row(),
                self.row(corners_for="not-a-number"),
                self.row(minute="0"),
                self.row(),
            ])
            result = load_live_corner_history_csv(path)
        self.assertEqual(result["received"], 4)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["invalid"], 2)
        self.assertEqual(result["duplicates"], 1)

    def test_requires_fixture_identity_and_all_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.csv"
            self.write_csv(path, [self.row(fixture_id="")])
            result = load_live_corner_history_csv(path)
        self.assertFalse(result["available"])
        self.assertEqual(result["invalid"], 1)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.csv"
            self.write_csv(path, [], columns=["fixture_id", "league"])
            result = load_live_corner_history_csv(path)
        self.assertIn("Faltan columnas", result["reason"])

    def test_missing_file_abstains_without_error(self):
        with tempfile.TemporaryDirectory() as folder:
            result = load_live_corner_history_csv(Path(folder) / "missing.csv")
        self.assertFalse(result["available"])
        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
