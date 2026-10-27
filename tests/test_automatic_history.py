from models.automatic_history import build_automatic_history


def _fixture(fid, home_id, away_id, hg, ag, status="FT"):
    return {
        "fixture": {"id": fid, "status": {"short": status}},
        "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
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
                {"statistics": [{"type": "Corner Kicks", "value": 6}]},
                {"statistics": [{"type": "Corner Kicks", "value": 2}]},
            ]}
        if endpoint == "fixtures/statistics" and params["fixture"] == 102:
            return {"response": [
                {"statistics": [{"type": "Corner Kicks", "value": 4}]},
                {"statistics": [{"type": "Corner Kicks", "value": 5}]},
            ]}
        return {"response": []}

    result = build_automatic_history(current, api_get=fake_api, cache={}, stats_budget=2)
    assert result["available"] is True
    assert result["home_goals_for"] == 2.0
    assert result["away_goals_for"] == 1.0
    assert result["home_corners_for"] == 6.0
    assert result["away_corners_for"] == 5.0
