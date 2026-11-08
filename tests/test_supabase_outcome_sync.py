import unittest
from ai_engine.supabase_outcome_sync import build_outcome_event


class OutcomeSyncTests(unittest.TestCase):
    def test_only_completed_fixture_is_accepted(self):
        fixture = {"fixture": {"id": 123, "status": {"short": "FT"}},
                   "goals": {"home": 2, "away": 1}}
        stats = [
            {"statistics": [{"type": "Corner Kicks", "value": 5},
                            {"type": "Yellow Cards", "value": 2}]},
            {"statistics": [{"type": "Corner Kicks", "value": 4},
                            {"type": "Yellow Cards", "value": 3}]},
        ]
        result = build_outcome_event(fixture, stats)
        self.assertEqual(result["fixture_id"], "123")
        self.assertEqual(result["final_home_score"], 2)
        self.assertEqual(result["final_total_corners"], 9)
        self.assertEqual(result["final_total_yellow_cards"], 5)

    def test_live_fixture_is_not_accepted(self):
        fixture = {"fixture": {"id": 123, "status": {"short": "2H"}},
                   "goals": {"home": 2, "away": 1}}
        self.assertIsNone(build_outcome_event(fixture, []))

    def test_missing_stats_remain_null_not_guessed(self):
        fixture = {"fixture": {"id": 123, "status": {"short": "FT"}},
                   "goals": {"home": 0, "away": 0}}
        result = build_outcome_event(fixture, [])
        self.assertIsNone(result["final_total_corners"])
        self.assertIsNone(result["final_total_yellow_cards"])


if __name__ == "__main__":
    unittest.main()
