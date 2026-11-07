import unittest

from ai_engine.data_engine import (
    FootballDataEngine,
    build_match_snapshot,
    cache_key,
    normalize_fixture,
    normalize_statistics,
)


FIXTURE = {
    "fixture": {
        "id": 12345,
        "date": "2026-11-06T20:00:00+00:00",
        "timestamp": 1793995200,
        "status": {"short": "2H", "long": "Second Half", "elapsed": 63},
    },
    "league": {"id": 239, "name": "Liga BetPlay", "country": "Colombia", "season": 2026},
    "teams": {
        "home": {"id": 10, "name": "América"},
        "away": {"id": 20, "name": "Deportivo Cali"},
    },
    "goals": {"home": 1, "away": 0},
    "score": {"halftime": {"home": 1, "away": 0}},
}


class DataEngineTests(unittest.TestCase):
    def test_normalize_fixture_preserves_match_identity_and_nullable_fields(self):
        normalized = normalize_fixture(FIXTURE)
        self.assertEqual(normalized["fixture_id"], 12345)
        self.assertEqual(normalized["teams"]["home"]["name"], "América")
        self.assertEqual(normalized["goals"], {"home": 1, "away": 0})
        self.assertIsNone(normalized["halftime_score"]["away"])

    def test_statistics_are_matched_by_team_id_not_provider_order(self):
        response = [
            {
                "team": {"id": 20, "name": "Deportivo Cali"},
                "statistics": [{"type": "Corner Kicks", "value": 7}],
            },
            {
                "team": {"id": 10, "name": "América"},
                "statistics": [{"type": "Corner Kicks", "value": 4}],
            },
        ]
        stats = normalize_statistics(response, FIXTURE)
        self.assertEqual(stats["home"]["values"]["corners"]["value"], 4)
        self.assertEqual(stats["away"]["values"]["corners"]["value"], 7)
        self.assertEqual(stats["missing_teams"], [])

    def test_missing_statistics_remain_missing_not_zero(self):
        stats = normalize_statistics([], FIXTURE)
        self.assertFalse(stats["available"])
        self.assertIsNone(stats["home"]["values"].get("corners"))
        self.assertEqual(stats["missing_teams"], ["home", "away"])

    def test_percentages_and_unknown_statistics_are_preserved(self):
        response = [
            {
                "team": {"id": 10, "name": "América"},
                "statistics": [
                    {"type": "Ball Possession", "value": "57%"},
                    {"type": "Custom Metric", "value": "3.5"},
                ],
            }
        ]
        stats = normalize_statistics(response, FIXTURE)
        self.assertEqual(stats["home"]["values"]["possession"]["value"], 57)
        self.assertEqual(stats["home"]["values"]["possession"]["unit"], "percent")
        self.assertEqual(stats["home"]["values"]["custom_metric"]["value"], 3.5)

    def test_cache_key_is_stable_and_namespaced(self):
        self.assertEqual(
            cache_key("fixture statistics", fixture=123, season=2026),
            cache_key("fixture statistics", season=2026, fixture=123),
        )
        self.assertTrue(cache_key("fixture statistics", fixture=123).startswith("fixture_statistics:"))

    def test_data_engine_reuses_cached_statistics(self):
        calls = []

        def fake_api_get(endpoint, params):
            calls.append((endpoint, params))
            return {"response": [{"team": {"id": 10}, "statistics": []}]}

        cache = {}
        engine = FootballDataEngine(fake_api_get, cache)
        first = engine.get_fixture_statistics(12345)
        second = engine.get_fixture_statistics(12345)
        self.assertIs(first, second)
        self.assertEqual(len(calls), 1)

    def test_data_engine_reuses_existing_streamlit_stats_cache(self):
        existing = [{"team": {"id": 10}, "statistics": []}]
        cache = {"12345": existing}
        calls = []
        engine = FootballDataEngine(
            lambda endpoint, params: calls.append((endpoint, params)) or {"response": []},
            cache,
        )
        self.assertIs(engine.get_fixture_statistics(12345), existing)
        self.assertEqual(calls, [])

    def test_data_engine_rejects_empty_fixture_id(self):
        engine = FootballDataEngine(lambda endpoint, params: {"response": []})
        with self.assertRaises(ValueError):
            engine.get_fixture_statistics("")

    def test_snapshot_reports_data_quality_without_fabricating_stats(self):
        snapshot = build_match_snapshot(
            FIXTURE,
            [],
            fetched_at="2026-11-06T20:00:00+00:00",
        )
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertFalse(snapshot["data_quality"]["statistics_available"])
        self.assertEqual(snapshot["data_quality"]["statistics_missing_teams"], ["home", "away"])


if __name__ == "__main__":
    unittest.main()
