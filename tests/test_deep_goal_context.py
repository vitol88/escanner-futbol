from models.deep_goal_context import build_deep_goal_context


def _match(fid, home_id, away_id, home_goals, away_goals, status="FT", minute=90):
    return {
        "fixture": {"id": fid, "status": {"short": status, "elapsed": minute}},
        "teams": {"home": {"id": home_id, "name": f"Team {home_id}"}, "away": {"id": away_id, "name": f"Team {away_id}"}},
        "goals": {"home": home_goals, "away": away_goals},
        "league": {"id": 10, "season": 2026},
    }


def test_deep_context_summarizes_form_h2h_and_caches_calls():
    current = _match(999, 1, 2, 1, 0, status="LIVE", minute=58)
    current["teams"]["home"]["name"] = "Chico"
    current["teams"]["away"]["name"] = "Junior"
    home_old = _match(101, 1, 3, 1, 1)
    away_old = _match(102, 4, 2, 2, 1)
    h2h_old = _match(103, 1, 2, 2, 1)
    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params.copy()))
        if endpoint == "fixtures" and params.get("team") == 1:
            return {"response": [home_old]}
        if endpoint == "fixtures" and params.get("team") == 2:
            return {"response": [away_old]}
        if endpoint == "fixtures/headtohead":
            return {"response": [h2h_old]}
        if endpoint == "fixtures/events" and params.get("fixture") == 999:
            return {"response": [
                {"type": "Goal", "detail": "Normal Goal", "time": {"elapsed": 58, "extra": None}, "team": {"id": 1, "name": "Chico"}}
            ]}
        if endpoint == "fixtures/events" and params.get("fixture") == 101:
            return {"response": [
                {"type": "Goal", "detail": "Normal Goal", "time": {"elapsed": 30}, "team": {"id": 3}},
                {"type": "Goal", "detail": "Normal Goal", "time": {"elapsed": 70}, "team": {"id": 1}},
            ]}
        return {"response": []}

    cache = {}
    result = build_deep_goal_context(current, api_get=fake_api, cache=cache, event_fixture_budget=1)
    assert result["available"] is True
    assert result["home_form"]["matches"] == 1
    assert result["home_form"]["record"] == "0V 1E 0D"
    assert result["away_form"]["goals_for_avg"] == 1.0
    assert result["h2h"]["matches"] == 1
    assert result["current_goal_minute"] == 58
    assert result["current_goal_team"] == "Chico"
    assert build_deep_goal_context(current, api_get=fake_api, cache=cache, event_fixture_budget=1) is result
    assert len(calls) == len(set((endpoint, str(params)) for endpoint, params in calls))
