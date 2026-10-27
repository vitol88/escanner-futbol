import unittest

from app import fixture_label, has_core_stats, safe_stat


class ScannerUnitTests(unittest.TestCase):
    def test_fixture_label_handles_missing_scores(self):
        fixture = {
            "teams": {
                "home": {"name": "A"},
                "away": {"name": "B"},
            },
            "goals": {"home": None, "away": 1},
            "fixture": {"status": {"elapsed": 33}},
            "league": {"name": "Liga X"},
        }
        label = fixture_label(fixture)
        self.assertIn("A", label)
        self.assertIn("B", label)
        self.assertIn("-–1", label)

    def test_safe_stat_finds_value_for_requested_team(self):
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"statistics": [{"type": "Corner Kicks", "value": 7}]},
        ]
        self.assertEqual(safe_stat(stats, "Corner Kicks", team_index=0), 4)
        self.assertEqual(safe_stat(stats, "Corner Kicks", team_index=1), 7)

    def test_safe_stat_does_not_fall_back_to_other_team(self):
        stats = [
            {"statistics": [{"type": "Total Shots", "value": None}]},
            {"statistics": [{"type": "Total Shots", "value": 7}]},
        ]
        self.assertIsNone(safe_stat(stats, "Total Shots", team_index=0))
        self.assertEqual(safe_stat(stats, "Total Shots", team_index=1), 7)

    def test_missing_core_stats_is_not_enough(self):
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"statistics": [{"type": "Total Shots", "value": 7}]},
        ]
        enough, missing = has_core_stats(stats)
        self.assertFalse(enough)
        self.assertIn("córners", missing)
        self.assertIn("tiros", missing)
        self.assertIn("tiros", missing)

    def test_complete_core_stats_passes_gate(self):
        stats = [
            {"statistics": [
                {"type": "Corner Kicks", "value": 4},
                {"type": "Total Shots", "value": 7},
            ]},
            {"statistics": [
                {"type": "Corner Kicks", "value": 3},
                {"type": "Total Shots", "value": 5},
            ]},
        ]
        enough, missing = has_core_stats(stats)
        self.assertTrue(enough)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
