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


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class OutcomeSyncIntegrationTests(unittest.TestCase):
    def test_sync_reads_prediction_ledger_and_snapshots_without_duplicate_fixtures(self):
        from ai_engine.supabase_outcome_sync import sync_finished_fixture_outcomes

        get_calls = []
        post_calls = []
        table_rows = {
            "prediction_ledger": [{"fixture_id": "123"}, {"fixture_id": "456"}],
            "analysis_snapshots": [{"fixture_id": "123"}, {"fixture_id": "789"}],
            "latest_match_outcomes": [],
        }

        def fake_get(url, params, headers, timeout):
            table = url.rsplit("/", 1)[-1]
            get_calls.append((table, params))
            return _FakeResponse(table_rows.get(table, []))

        def fake_post(url, **kwargs):
            post_calls.append((url, kwargs["json"]))
            return _FakeResponse([kwargs["json"]])

        api_calls = []

        def fake_api_get(endpoint, params):
            fixture_id = str(params.get("id") or params.get("fixture"))
            api_calls.append((endpoint, fixture_id))
            if endpoint == "fixtures":
                return {"response": [{
                    "fixture": {"id": int(fixture_id), "status": {"short": "FT"}},
                    "goals": {"home": 1, "away": 0},
                }]}
            if endpoint == "fixtures/statistics":
                return {"response": [
                    {"statistics": [{"type": "Corner Kicks", "value": 4},
                                    {"type": "Yellow Cards", "value": 1}]},
                    {"statistics": [{"type": "Corner Kicks", "value": 3},
                                    {"type": "Yellow Cards", "value": 2}]},
                ]}
            raise AssertionError(endpoint)

        result = sync_finished_fixture_outcomes(
            "https://example.supabase.co", "service-key", fake_api_get,
            max_fixtures=10, get=fake_get, post=fake_post,
        )

        self.assertEqual(result["fixtures_found"], 3)
        self.assertEqual(result["checked"], 3)
        self.assertEqual(result["finished"], 3)
        self.assertEqual(result["inserted"], 3)
        self.assertEqual(len(post_calls), 3)
        self.assertEqual(
            [fixture_id for endpoint, fixture_id in api_calls if endpoint == "fixtures"],
            ["123", "456", "789"],
        )
        self.assertEqual(
            {table for table, _ in get_calls},
            {"prediction_ledger", "analysis_snapshots", "latest_match_outcomes"},
        )

    def test_sync_bounds_fixture_checks(self):
        from ai_engine.supabase_outcome_sync import sync_finished_fixture_outcomes

        def fake_get(url, params, headers, timeout):
            table = url.rsplit("/", 1)[-1]
            rows = ([{"fixture_id": str(value)} for value in range(1, 6)]
                    if table == "prediction_ledger" else [])
            return _FakeResponse(rows)

        checked_ids = []

        def fake_api_get(endpoint, params):
            fixture_id = str(params.get("id") or params.get("fixture"))
            if endpoint == "fixtures":
                checked_ids.append(fixture_id)
                return {"response": []}
            return {"response": []}

        result = sync_finished_fixture_outcomes(
            "https://example.supabase.co", "service-key", fake_api_get,
            max_fixtures=2, get=fake_get, post=lambda *args, **kwargs: _FakeResponse([]),
        )
        self.assertEqual(result["fixtures_found"], 2)
        self.assertEqual(checked_ids, ["1", "2"])


class LatestOutcomeReaderTests(unittest.TestCase):
    def test_load_latest_outcomes_indexes_fixture_and_uses_verified_fields(self):
        from ai_engine.supabase_outcome_sync import load_latest_match_outcomes

        calls = []
        def fake_get(url, params, headers, timeout):
            calls.append((url, params))
            return _FakeResponse([{
                "fixture_id": 321,
                "final_home_score": 2,
                "final_away_score": 1,
                "final_total_corners": 10,
                "final_total_yellow_cards": 4,
                "source": "api-football",
                "verified_at": "2026-11-11T12:00:00+00:00",
            }])

        outcomes = load_latest_match_outcomes(
            "https://example.supabase.co", "service-key", get=fake_get
        )
        self.assertEqual(outcomes["321"]["final_home_score"], 2)
        self.assertEqual(outcomes["321"]["final_total_corners"], 10)
        self.assertIn("/latest_match_outcomes", calls[0][0])
        self.assertIn("verified_at", calls[0][1]["select"])
