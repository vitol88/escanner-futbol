import unittest

from models.probabilities import (
    corner_pace_per_90,
    estimate_live_goal_markets,
    find_league_baseline,
    poisson_at_least,
    poisson_pmf,
)


TEST_DATA = {
    "minimum_matches_for_estimate": 3,
    "leagues": [
        {
            "country": "England",
            "country_aliases": ["Inglaterra"],
            "league": "Premier League",
            "aliases": ["EPL"],
            "matches": 10,
            "avg_home_goals": 1.5,
            "avg_away_goals": 1.2,
            "draw_rate": 0.25,
            "btts_rate": 0.55,
            "avg_total_goals": 2.7,
        }
    ],
}


class ProbabilityModelTests(unittest.TestCase):
    def test_poisson_pmf_zero_rate(self):
        self.assertEqual(poisson_pmf(0, 0), 1.0)
        self.assertEqual(poisson_pmf(0, 1), 0.0)

    def test_poisson_tail_bounds_and_zero_target(self):
        self.assertEqual(poisson_at_least(0.4, 0), 1.0)
        self.assertGreater(poisson_at_least(1.0, 1), 0.0)
        self.assertLessEqual(poisson_at_least(1.0, 1), 1.0)

    def test_country_disambiguates_serie_a(self):
        data = {"minimum_matches_for_estimate": 1, "leagues": [
            {"country": "Italy", "country_aliases": [], "league": "Serie A", "aliases": [], "matches": 50,
             "avg_home_goals": 1.5, "avg_away_goals": 1.2, "draw_rate": .2, "btts_rate": .5, "avg_total_goals": 2.7},
            {"country": "Brazil", "country_aliases": [], "league": "Brasileirão Série A", "aliases": ["Serie A"], "matches": 50,
             "avg_home_goals": 1.5, "avg_away_goals": 1.2, "draw_rate": .2, "btts_rate": .5, "avg_total_goals": 2.7},
        ]}
        self.assertEqual(find_league_baseline("Italy", "Serie A", data)["country"], "Italy")
        self.assertEqual(find_league_baseline("Brazil", "Serie A", data)["country"], "Brazil")

    def test_missing_baseline_is_not_reported_as_probability(self):
        result = estimate_live_goal_markets(country="Sweden", league_name="Superettan",
            score_home=0, score_away=0, elapsed_minute=30, data=TEST_DATA)
        self.assertFalse(result["available"])
        self.assertIsNone(result.get("draw_final"))

    def test_low_sample_is_withheld(self):
        small = {"minimum_matches_for_estimate": 30, "leagues": [dict(TEST_DATA["leagues"][0], matches=10)]}
        result = estimate_live_goal_markets(country="England", league_name="Premier League",
            score_home=0, score_away=0, elapsed_minute=30, data=small)
        self.assertFalse(result["available"])
        self.assertIn("Muestra histórica insuficiente", result["reason"])

    def test_model_probabilities_are_bounded(self):
        result = estimate_live_goal_markets(country="England", league_name="EPL",
            score_home=1, score_away=0, elapsed_minute=45, data=TEST_DATA)
        self.assertTrue(result["available"])
        values = list(result["over_total_goals"].values()) + [result["draw_final"], result["btts_final"]]
        self.assertTrue(all(0.0 <= p <= 1.0 for p in values))
        self.assertGreater(result["btts_final"], 0.0)
        self.assertLess(result["btts_final"], 1.0)  # only the away team still needs to score

    def test_goal_targets_are_relative_to_current_total(self):
        result = estimate_live_goal_markets(
            country="England", league_name="EPL",
            score_home=2, score_away=1, elapsed_minute=35, data=TEST_DATA
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["current_total_goals"], 3)
        self.assertEqual(list(result["over_total_goals"].keys()), ["4", "5", "6"])
        self.assertEqual(result["over_total_goals"]["5"], poisson_at_least(
            result["expected_total_goals_remaining"], 2
        ))

    def test_btts_is_marked_settled_when_both_teams_have_scored(self):
        result = estimate_live_goal_markets(
            country="England", league_name="EPL",
            score_home=2, score_away=1, elapsed_minute=35, data=TEST_DATA
        )
        self.assertTrue(result["btts_already_settled"])

    def test_probability_no_more_goals_is_valid(self):
        result = estimate_live_goal_markets(
            country="England", league_name="EPL",
            score_home=2, score_away=1, elapsed_minute=35, data=TEST_DATA
        )
        self.assertTrue(0.0 <= result["probability_no_more_goals"] <= 1.0)
        self.assertAlmostEqual(
            result["probability_no_more_goals"],
            poisson_pmf(result["expected_total_goals_remaining"], 0),
        )

    def test_live_activity_adjustment_is_bounded_and_reported(self):
        baseline = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=0, score_away=0,
            elapsed_minute=60, data=TEST_DATA
        )
        active = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=0, score_away=0,
            elapsed_minute=60, data=TEST_DATA,
            live_stats={"shots_on_total": 9, "corners_total": 12, "red_cards_total": 0}
        )
        self.assertTrue(active["available"])
        self.assertTrue(active["live_stats_used"])
        self.assertGreater(active["expected_total_goals_remaining"], baseline["expected_total_goals_remaining"])
        self.assertLessEqual(active["live_activity_adjustment"], 1.25)

    def test_high_scoring_match_raises_remaining_goal_rate_modestly(self):
        quiet = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=0, score_away=0,
            elapsed_minute=60, data=TEST_DATA
        )
        high_scoring = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=2, score_away=2,
            elapsed_minute=60, data=TEST_DATA
        )
        self.assertGreater(
            high_scoring["expected_total_goals_remaining"],
            quiet["expected_total_goals_remaining"],
        )
        self.assertLessEqual(high_scoring["score_pace_adjustment"], 1.35)
        self.assertGreater(high_scoring["probability_no_more_goals"], 0.0)
        self.assertLess(high_scoring["probability_no_more_goals"], 1.0)

    def test_recent_goals_between_scans_raise_remaining_goal_rate(self):
        base = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=1, score_away=1,
            elapsed_minute=60, data=TEST_DATA
        )
        recent = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=1, score_away=1,
            elapsed_minute=60, data=TEST_DATA, recent_goals=2,
            minutes_since_previous_scan=5
        )
        self.assertGreater(
            recent["expected_total_goals_remaining"],
            base["expected_total_goals_remaining"],
        )
        self.assertEqual(recent["recent_goal_adjustment"], 1.24)

    def test_old_scan_does_not_apply_recent_goal_adjustment(self):
        base = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=1, score_away=1,
            elapsed_minute=60, data=TEST_DATA
        )
        stale = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=1, score_away=1,
            elapsed_minute=60, data=TEST_DATA, recent_goals=2,
            minutes_since_previous_scan=20
        )
        self.assertEqual(
            stale["expected_total_goals_remaining"],
            base["expected_total_goals_remaining"],
        )
        self.assertEqual(stale["recent_goal_adjustment"], 1.0)

    def test_missing_score_or_minute_withholds_estimate(self):
        cases = [
            {"score_home": None, "score_away": 0, "elapsed_minute": 30},
            {"score_home": 0, "score_away": 0, "elapsed_minute": None},
            {"score_home": -1, "score_away": 0, "elapsed_minute": 30},
        ]
        for case in cases:
            with self.subTest(case=case):
                result = estimate_live_goal_markets(
                    country="England", league_name="EPL", data=TEST_DATA, **case
                )
                self.assertFalse(result["available"])
                self.assertIsNotNone(result["reason"])
                self.assertNotIn("draw_final", result)

    def test_missing_live_stats_do_not_change_baseline_estimate(self):
        baseline = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=0, score_away=0,
            elapsed_minute=60, data=TEST_DATA
        )
        missing = estimate_live_goal_markets(
            country="England", league_name="EPL", score_home=0, score_away=0,
            elapsed_minute=60, data=TEST_DATA,
            live_stats={"shots_on_total": None, "corners_total": None, "red_cards_total": None}
        )
        self.assertEqual(
            missing["expected_total_goals_remaining"],
            baseline["expected_total_goals_remaining"],
        )
        self.assertFalse(missing["live_stats_used"])

    def test_corner_pace_is_descriptive(self):
        self.assertAlmostEqual(corner_pace_per_90(8, 40), 18.0)
        self.assertIsNone(corner_pace_per_90(None, 40))


if __name__ == "__main__":
    unittest.main()
