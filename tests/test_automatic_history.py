from models.automatic_history import build_automatic_history


def _fixture(fid, home_id, away_id, hg, ag, status="FT", timestamp=None):
    return {
        "fixture": {"id": fid, "timestamp": timestamp if timestamp is not None else fid * 10, "status": {"short": status}},
        "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
        "league": {"id": 10, "season": 2026},
        "goals": {"home": hg, "away": ag},
    }


def test_automatic_history_calculates_home_away_goals_and_corners():
    current = {
        "fixture": {"timestamp": 2000},
        "teams": {"home": {"id": 1, "name": "Home FC"}, "away": {"id": 2, "name": "Away FC"}},
        "league": {"id": 10, "season": 2026},
    }
    past_home = _fixture(101, 1, 3, 2, 0)
    past_away = _fixture(102, 4, 2, 1, 1)

    def fake_api(endpoint, params):
        if endpoint == "fixtures" and params["team"] == 1:
            return {"response": [past_home]}
        if endpoint == "fixtures" and params["team"] == 2:
            return {"response": [past_away]}
        if endpoint == "fixtures/statistics" and params["fixture"] == 101:
            return {"response": [
                {"statistics": [{"type": "Corner Kicks", "value": 6}, {"type": "Yellow Cards", "value": 3}]},
                {"statistics": [{"type": "Corner Kicks", "value": 2}, {"type": "Yellow Cards", "value": 1}]},
            ]}
        if endpoint == "fixtures/statistics" and params["fixture"] == 102:
            return {"response": [
                {"statistics": [{"type": "Corner Kicks", "value": 4}, {"type": "Yellow Cards", "value": 2}]},
                {"statistics": [{"type": "Corner Kicks", "value": 5}, {"type": "Yellow Cards", "value": 4}]},
            ]}
        return {"response": []}

    result = build_automatic_history(current, api_get=fake_api, cache={}, stats_budget=2)
    assert result["available"] is True
    assert result["home_goals_for"] == 2.0
    assert result["away_goals_for"] == 1.0
    assert result["home_corners_for"] == 6.0
    assert result["away_corners_for"] == 5.0
    assert len(result["card_history_rows"]) == 2
    assert result["card_history_rows"][0]["home_yellow_cards"] == 3.0
    assert result["card_history_rows"][1]["away_yellow_cards"] == 4.0


def test_automatic_history_counts_shared_stats_budget_for_full_and_half_requests():
    current = {
        "fixture": {"timestamp": 3000},
        "teams": {"home": {"id": 1, "name": "Home FC"}, "away": {"id": 2, "name": "Away FC"}},
        "league": {"id": 10, "season": 2026},
    }
    past = _fixture(201, 1, 3, 1, 0)
    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "fixtures" and params["team"] == 1:
            return {"response": [past]}
        if endpoint == "fixtures" and params["team"] == 2:
            return {"response": []}
        if endpoint == "fixtures/statistics" and params.get("fixture") == 201:
            return {"response": [
                {"statistics": [{"type": "Corner Kicks", "value": 5}, {"type": "Yellow Cards", "value": 2}]},
                {"statistics": [{"type": "Corner Kicks", "value": 3}, {"type": "Yellow Cards", "value": 1}]},
            ]}
        return {"response": []}

    shared_cache = {"_automatic_history_stats_calls": 4}
    result = build_automatic_history(current, api_get=fake_api, cache=shared_cache, stats_budget=4)

    assert result["diagnostics"]["historical_stats"]["requested"] == 2
    assert shared_cache["_automatic_history_stats_calls"] == 6
    assert len([call for call in calls if call[0] == "fixtures/statistics"]) == 2


def test_automatic_history_does_not_count_cached_statistics_as_new_requests():
    current = {
        "fixture": {"timestamp": 3000},
        "teams": {"home": {"id": 1, "name": "Home FC"}, "away": {"id": 2, "name": "Away FC"}},
        "league": {"id": 10, "season": 2026},
    }
    past = _fixture(202, 1, 3, 1, 0)
    shared_cache = {
        "team-fixtures-v5:1:10:2026": [past],
        "team-fixtures-v5:2:10:2026": [],
        "historical-stats-full-v1:202": [
            {"statistics": [{"type": "Corner Kicks", "value": 5}, {"type": "Yellow Cards", "value": 2}]},
            {"statistics": [{"type": "Corner Kicks", "value": 3}, {"type": "Yellow Cards", "value": 1}]},
        ],
        "historical-stats-halves-v5:202": [
            {"statistics": [{"type": "Corner Kicks", "value": 2}]},
            {"statistics": [{"type": "Corner Kicks", "value": 1}]},
        ],
        "_automatic_history_stats_calls": 7,
    }
    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params))
        return {"response": []}

    build_automatic_history(current, api_get=fake_api, cache=shared_cache, stats_budget=2)

    assert shared_cache["_automatic_history_stats_calls"] == 7
    assert not [call for call in calls if call[0] == "fixtures/statistics"]

def test_automatic_history_keeps_goal_samples_but_guards_card_rows_by_timestamp():
    current = {
        "fixture": {"timestamp": 2000},
        "teams": {"home": {"id": 1, "name": "Home FC"}, "away": {"id": 2, "name": "Away FC"}},
        "league": {"id": 10, "season": 2026},
    }
    earlier = _fixture(301, 1, 3, 1, 0, timestamp=1900)
    same_time = _fixture(302, 1, 4, 1, 0, timestamp=2000)
    later = _fixture(303, 1, 5, 1, 0, timestamp=2100)
    missing_time = _fixture(304, 1, 6, 1, 0, timestamp=None)
    missing_time["fixture"].pop("timestamp")
    rows = [earlier, same_time, later, missing_time]

    def fake_api(endpoint, params):
        if endpoint == "fixtures" and params["team"] == 1:
            return {"response": rows}
        if endpoint == "fixtures" and params["team"] == 2:
            return {"response": []}
        if endpoint == "fixtures/statistics":
            return {"response": [
                {"statistics": [{"type": "Yellow Cards", "value": 2}]},
                {"statistics": [{"type": "Yellow Cards", "value": 1}]},
            ]}
        return {"response": []}

    result = build_automatic_history(current, api_get=fake_api, cache={}, stats_budget=8)
    # Goals/corners history must not disappear when optional timestamps are
    # absent or out of order; card-model rows keep their strict timestamp guard.
    assert result["home_matches"] == 4
    assert result["home_goal_sample"] == 4
    assert [row["fixture_id"] for row in result["card_history_rows"]] == [301]


def test_failed_historical_statistics_request_still_consumes_budget():
    current = {
        "fixture": {"timestamp": 5000},
        "teams": {"home": {"id": 1, "name": "Home FC"}, "away": {"id": 2, "name": "Away FC"}},
        "league": {"id": 10, "season": 2026},
    }
    past = _fixture(401, 1, 3, 1, 0)
    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "fixtures" and params["team"] == 1:
            return {"response": [past]}
        if endpoint == "fixtures" and params["team"] == 2:
            return {"response": []}
        if endpoint == "fixtures/statistics":
            raise RuntimeError("temporary API failure")
        return {"response": []}

    cache = {}
    result = build_automatic_history(current, api_get=fake_api, cache=cache, stats_budget=1)
    stat_calls = [call for call in calls if call[0] == "fixtures/statistics"]
    assert len(stat_calls) == 1
    assert cache["_automatic_history_stats_calls"] == 1
    assert result["diagnostics"]["historical_stats"]["requested"] == 1
    assert result["diagnostics"]["stats_budget_remaining"] == 0



def test_automatic_history_reuses_cached_completed_stats_for_corner_finalization():
    current = {
        "fixture": {"timestamp": 5000},
        "teams": {
            "home": {"id": 1, "name": "Home FC"},
            "away": {"id": 2, "name": "Away FC"},
        },
        "league": {"id": 10, "season": 2026},
    }
    past = _fixture(601, 1, 3, 2, 0)
    cached_stats = [
        {"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 8}]},
        {"team": {"id": 3}, "statistics": [{"type": "Corner Kicks", "value": 4}]},
    ]
    cache = {
        "team-fixtures-v5:1:10:2026": [past],
        "team-fixtures-v5:2:10:2026": [],
        "historical-stats-full-v1:601": cached_stats,
        "historical-stats-halves-v5:601": [],
    }
    finalized = []

    def finalizer(completed_fixture, final_statistics):
        finalized.append((completed_fixture, final_statistics))
        return {"finalized": True, "observations_inserted": 2}

    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params))
        return {"response": []}

    result = build_automatic_history(
        current,
        api_get=fake_api,
        cache=cache,
        stats_budget=0,
        live_corner_finalizer=finalizer,
    )

    assert len(finalized) == 1
    assert finalized[0][0]["fixture"]["id"] == 601
    assert finalized[0][1] == cached_stats
    assert calls == []
    assert result["diagnostics"]["live_corner_finalization"]["finalized"] == 1
    assert result["diagnostics"]["live_corner_finalization"]["observations_inserted"] == 2
