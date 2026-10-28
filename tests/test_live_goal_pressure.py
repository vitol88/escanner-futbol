from models.probabilities import estimate_live_goal_markets


def _estimate(corners_home, corners_away, shots_on_home=2, shots_on_away=1, possession_home=55, possession_away=45):
    data = {
        "minimum_matches_for_estimate": 30,
        "leagues": [{
            "country": "Testland",
            "league": "Test League",
            "avg_home_goals": 1.4,
            "avg_away_goals": 1.1,
            "matches": 100,
        }],
    }
    # The model accepts its production baseline schema (avg_home_goals/avg_away_goals).
    return estimate_live_goal_markets(
        country="Testland",
        league_name="Test League",
        score_home=0,
        score_away=0,
        elapsed_minute=65,
        data=data,
        live_stats={
            "corners_home": corners_home,
            "corners_away": corners_away,
            "corners_total": corners_home + corners_away,
            "shots_on_home": shots_on_home,
            "shots_on_away": shots_on_away,
            "shots_on_total": shots_on_home + shots_on_away,
            "possession_home": possession_home,
            "possession_away": possession_away,
            "red_cards_home": 0,
            "red_cards_away": 0,
            "red_cards_total": 0,
        },
    )


def test_corner_imbalance_contributes_to_next_goal_probability():
    balanced = _estimate(2, 2)
    home_pressure = _estimate(8, 2)

    assert balanced["available"] is True
    assert home_pressure["available"] is True
    assert home_pressure["probability_next_goal"] > balanced["probability_next_goal"]
    assert home_pressure["team_pressure_home_adjustment"] > balanced["team_pressure_home_adjustment"]


def test_probability_is_available_for_live_0_0_and_is_bounded():
    result = _estimate(8, 2, shots_on_home=4, shots_on_away=1)
    assert result["available"] is True
    assert 0 <= result["probability_next_goal"] <= 1
