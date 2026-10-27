from models.corner_history import estimate_remaining_corners


def _rows(count=10, venue="home", corners_for=4, corners_against=3):
    rows = []
    for i in range(count):
        rows.append({
            "league": "Serie A",
            "team": "Roma",
            "venue": venue,
            "minute": 70,
            "corners_for": corners_for,
            "corners_against": corners_against,
            "corners_for_after": 1 if i < 4 else 0,
            "corners_against_after": 1 if i < 2 else 0,
        })
    return rows


def test_exact_corner_state_empirical_rates():
    result = estimate_remaining_corners(
        _rows(), league="Serie A", team="Roma", venue="home",
        minute=70, corners_for=4, corners_against=3,
    )
    assert result["available"] is True
    assert result["sample_size"] == 10
    assert result["matched_exact_state"] is True
    assert result["prob_at_least_1_corner"] == 0.4
    assert result["prob_at_least_2_corners"] == 0.2
    assert result["prob_team_gets_corner"] == 0.4


def test_corner_history_requires_minimum_sample():
    result = estimate_remaining_corners(
        _rows(3), league="Serie A", team="Roma", venue="home",
        minute=70, corners_for=4, corners_against=3,
    )
    assert result["available"] is False
    assert result["sample_size"] == 3
