import unittest

from models.live_context import summarize_live_context


def team_stats(values):
    return {"statistics": [{"type": key, "value": value} for key, value in values.items()]}


class LiveContextTests(unittest.TestCase):
    def test_summarizes_complete_stats_without_inventing_missing_values(self):
        stats = [
            team_stats({"Corner Kicks": 4, "Total Shots": 8, "Shots on Goal": 3, "Ball Possession": "55%", "Yellow Cards": 1, "Red Cards": 0}),
            team_stats({"Corner Kicks": 2, "Total Shots": 5, "Shots on Goal": 1, "Ball Possession": "45%", "Yellow Cards": 2, "Red Cards": 0}),
        ]
        result = summarize_live_context(stats, 62)
        self.assertTrue(result["core_complete"])
        self.assertEqual(result["corners_total"], 6)
        self.assertEqual(result["shots_total"], 13)
        self.assertEqual(result["shots_on_total"], 4)
        self.assertEqual(result["red_cards_total"], 0)
        self.assertEqual(result["elapsed"], 62)

    def test_missing_team_stats_stay_missing(self):
        stats = [team_stats({"Corner Kicks": 3, "Total Shots": 7})]
        result = summarize_live_context(stats, 25)
        self.assertFalse(result["core_complete"])
        self.assertIsNone(result["corners_total"])
        self.assertIsNone(result["shots_total"])
        self.assertIsNone(result["shots_on_total"])

    def test_zero_values_are_not_treated_as_missing(self):
        stats = [
            team_stats({"Corner Kicks": 0, "Total Shots": 0}),
            team_stats({"Corner Kicks": 0, "Total Shots": 0}),
        ]
        result = summarize_live_context(stats, 5)
        self.assertTrue(result["core_complete"])
        self.assertEqual(result["corners_total"], 0)
        self.assertEqual(result["shots_total"], 0)


if __name__ == "__main__":
    unittest.main()
