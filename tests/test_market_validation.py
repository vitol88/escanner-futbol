import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_engine.market_validation import (
    card_calibration_readiness,
    corner_calibration_readiness,
)


class MarketValidationTests(unittest.TestCase):
    def test_missing_corner_database_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = corner_calibration_readiness(Path(tmp) / "missing.db")
        self.assertFalse(result["available"])
        self.assertFalse(result["ready_for_calibration"])
        self.assertEqual(result["reason"], "database_not_found")

    def test_corner_readiness_counts_unique_fixtures_and_valid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "corners.db"
            with sqlite3.connect(db) as con:
                con.execute("""
                    CREATE TABLE live_corner_observations (
                        fixture_id TEXT, minute INTEGER, corners_for INTEGER,
                        corners_against INTEGER, corners_for_after INTEGER,
                        corners_against_after INTEGER
                    )
                """)
                for fixture in range(30):
                    for venue in range(4):
                        con.execute(
                            "INSERT INTO live_corner_observations VALUES (?, ?, ?, ?, ?, ?)",
                            (str(fixture), 30 + venue, 2, 1, 3, 2),
                        )
            result = corner_calibration_readiness(db)
        self.assertTrue(result["ready_for_calibration"])
        self.assertEqual(result["fixtures"], 30)
        self.assertEqual(result["observations"], 120)

    def test_duplicate_card_fixture_counts_once(self):
        rows = [
            {"fixture_id": "a", "fixture_timestamp": 100, "home_yellow_cards": 2, "away_yellow_cards": 3},
            {"fixture_id": "a", "fixture_timestamp": 100, "home_yellow_cards": 2, "away_yellow_cards": 3},
            {"fixture_id": "", "fixture_timestamp": 100, "home_yellow_cards": 2, "away_yellow_cards": 3},
        ]
        result = card_calibration_readiness(rows, min_fixtures=2)
        self.assertEqual(result["fixtures"], 1)
        self.assertFalse(result["ready_for_calibration"])

    def test_invalid_card_counts_are_excluded(self):
        rows = [
            {"fixture_id": "a", "fixture_timestamp": 100, "home_yellow_cards": None, "away_yellow_cards": 3},
            {"fixture_id": "b", "fixture_timestamp": 100, "home_yellow_cards": 2, "away_yellow_cards": -1},
            {"fixture_id": "c", "fixture_timestamp": True, "home_yellow_cards": 2, "away_yellow_cards": 1},
        ]
        result = card_calibration_readiness(rows)
        self.assertEqual(result["fixtures"], 0)
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
