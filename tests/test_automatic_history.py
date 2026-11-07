from models.automatic_history import build_automatic_history


def _fixture(fid, home_id, away_id, hg, ag, status="FT"):
    return {
        "fixture": {"id": fid, "status": {"short": status}},
        "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
        "league": {"id": 10, "season": 2026},
        "goals": {"home": hg, "away": ag},
    }


def test_automatic_history_calculates_home_away_goals_and_corners():
    current = {
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
    result = build_automatic_history(current, api_get=fake_api, cache=shared_cache, stats_budget=2)

    assert result["diagnostics"]["historical_stats"]["requested"] == 2
    assert shared_cache["_automatic_history_stats_calls"] == 6
    assert len([call for call in calls if call[0] == "fixtures/statistics"]) == 2


def test_automatic_history_does_not_count_cached_statistics_as_new_requests():
    current = {
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
        "_automatic_history_stats_calls": 7,
    }
    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params))
        return {"response": []}

    build_automatic_history(current, api_get=fake_api, cache=shared_cache, stats_budget=2)

    assert shared_cache["_automatic_history_stats_calls"] == 7
    assert not [call for call in calls if call[0] == "fixtures/statistics"]
