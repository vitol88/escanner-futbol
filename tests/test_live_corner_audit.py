import tempfile
import unittest
from pathlib import Path

from ai_engine.live_corner_capture import capture_live_corner_snapshot
from ai_engine.live_corner_finalize import finalize_live_corner_fixture
from ai_engine.live_corner_audit import audit_live_corner_database


class LiveCornerAuditTests(unittest.TestCase):
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
            {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 9}]},
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": 7}]},
        ]

    def test_missing_database_is_reported_without_creating_it(self):
        result = audit_live_corner_database(self.db)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "database_not_found")
        self.assertFalse(self.db.exists())

    def test_audits_pending_capture_and_verified_pairs(self):
        capture_live_corner_snapshot(self.db, self.fixture, self.live_stats)
        pending = audit_live_corner_database(self.db)
        self.assertEqual(pending["captures"]["snapshots"], 1)
        self.assertEqual(pending["captures"]["pending_fixtures"], 1)
        self.assertEqual(pending["verified_history"]["observations"], 0)

        finalize_live_corner_fixture(self.db, self.final_fixture, self.final_stats)
        result = audit_live_corner_database(self.db)
        self.assertEqual(result["captures"]["snapshots"], 1)
        self.assertEqual(result["captures"]["pending_fixtures"], 0)
        self.assertEqual(result["verified_history"]["observations"], 2)
        self.assertEqual(result["verified_history"]["complete_pairs"], 1)
        self.assertEqual(result["quality"]["incomplete_pairs"], 0)
        self.assertEqual(result["quality"]["mismatched_pairs"], 0)
        self.assertEqual(result["by_league"][0]["league"], "Premier League")
        self.assertEqual(result["by_league"][0]["capture_snapshots"], 1)
        self.assertEqual(result["by_league"][0]["verified_observations"], 2)
        self.assertEqual(result["by_minute_bucket"][0]["minute_bucket"], "61-75")

    def test_audit_detects_missing_snapshot_pair_even_when_fixture_has_other_verified_minutes(self):
        capture_live_corner_snapshot(self.db, self.fixture, self.live_stats)
        later_fixture = {
            **self.fixture,
            "fixture": {"id": 501, "status": {"short": "2H", "elapsed": 75}},
        }
        capture_live_corner_snapshot(self.db, later_fixture, self.live_stats)
        finalize_live_corner_fixture(self.db, self.final_fixture, self.final_stats)

        connection = __import__("sqlite3").connect(self.db)
        connection.execute(
            "DELETE FROM live_corner_observations WHERE fixture_id = ? AND minute = ?",
            ("501", 75),
        )
        connection.commit()
        connection.close()

        result = audit_live_corner_database(self.db)
        self.assertEqual(result["captures"]["pending_fixtures"], 0)
        self.assertEqual(result["quality"]["pending_snapshots"], 1)
        self.assertEqual(result["quality"]["orphan_observation_minutes"], 0)
        self.assertTrue(any("snapshots" in warning for warning in result["warnings"]))

    def test_audit_detects_impossible_remaining_corner_timeline(self):
        capture_live_corner_snapshot(self.db, self.fixture, self.live_stats)
        later_fixture = {
            **self.fixture,
            "fixture": {"id": 501, "status": {"short": "2H", "elapsed": 75}},
        }
        capture_live_corner_snapshot(self.db, later_fixture, self.live_stats)
        finalize_live_corner_fixture(self.db, self.final_fixture, self.final_stats)

        connection = __import__("sqlite3").connect(self.db)
        connection.execute(
            """
            UPDATE live_corner_observations
            SET corners_for_after = 5
            WHERE fixture_id = ? AND venue = 'home' AND minute = 75
            """,
            ("501",),
        )
        connection.commit()
        connection.close()

        result = audit_live_corner_database(self.db)
        self.assertEqual(result["quality"]["inconsistent_remaining_progression"], 1)
        self.assertEqual(result["quality"]["inconsistent_final_totals"], 1)
        self.assertTrue(any("restantes aumentan" in warning for warning in result["warnings"]))
        self.assertTrue(any("total final implícito" in warning for warning in result["warnings"]))

    def test_timeline_groups_team_aliases_by_normalized_team_key(self):
        capture_live_corner_snapshot(self.db, self.fixture, self.live_stats)
        later_fixture = {
            **self.fixture,
            "fixture": {"id": 501, "status": {"short": "2H", "elapsed": 75}},
        }
        capture_live_corner_snapshot(self.db, later_fixture, self.live_stats)
        finalize_live_corner_fixture(self.db, self.final_fixture, self.final_stats)

        connection = __import__("sqlite3").connect(self.db)
        connection.execute(
            """
            UPDATE live_corner_observations
            SET team = 'Arsenal FC', corners_for_after = 5
            WHERE fixture_id = ? AND venue = 'home' AND minute = 75
            """,
            ("501",),
        )
        connection.commit()
        connection.close()

        result = audit_live_corner_database(self.db)
        self.assertEqual(result["quality"]["inconsistent_remaining_progression"], 1)
        self.assertEqual(result["quality"]["inconsistent_final_totals"], 1)

    def test_audit_is_read_only(self):
        capture_live_corner_snapshot(self.db, self.fixture, self.live_stats)
        before = self.db.stat().st_mtime_ns
        audit_live_corner_database(self.db)
        after = self.db.stat().st_mtime_ns
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
