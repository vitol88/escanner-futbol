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

    def test_safe_stat_finds_value(self):
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]}
        ]
        self.assertEqual(safe_stat(stats, "Corner Kicks"), 4)

    def test_missing_core_stats_is_not_enough(self):
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 4}]},
            {"statistics": [{"type": "Total Shots", "value": 7}]},
        ]
        enough, missing = has_core_stats(stats)
        self.assertFalse(enough)
        self.assertIn("córners", missing)
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


if _name_ == "_main_":
    unittest.main()
