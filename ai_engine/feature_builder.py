"""Build model-ready features from shared snapshots and existing history outputs."""
from __future__ import annotations
from typing import Any

FEATURE_SCHEMA_VERSION = "1.0"

def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace("%", "").strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None

def _history_number(history: dict[str, Any], key: str) -> float | None:
    return _number(history.get(key))

def _count(value: Any) -> int:
    number = _number(value)
    return max(0, int(number)) if number is not None else 0

def build_model_features(snapshot: dict[str, Any], history: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return stable goal/corner/card feature groups; does not fetch or estimate."""
    history = history if isinstance(history, dict) else {}
    match = snapshot.get("match") if isinstance(snapshot, dict) else {}
    match = match if isinstance(match, dict) else {}
    teams = match.get("teams") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    statistics = snapshot.get("statistics") if isinstance(snapshot, dict) else {}
    statistics = statistics if isinstance(statistics, dict) else {}
    home_stats = (statistics.get("home") or {}).get("values") or {}
    away_stats = (statistics.get("away") or {}).get("values") or {}
    status, goals = match.get("status") or {}, match.get("goals") or {}

    def stat(side: dict[str, Any], key: str) -> float | None:
        entry = side.get(key)
        return _number(entry.get("value")) if isinstance(entry, dict) else _number(entry)

    home_yellow, away_yellow = stat(home_stats, "yellow_cards"), stat(away_stats, "yellow_cards")

    raw_card_rows = history.get("card_history_rows")
    card_rows = []
    if isinstance(raw_card_rows, list):
        for row in raw_card_rows:
            if not isinstance(row, dict):
                continue
            row_league = row.get("league_id")
            current_league = (match.get("league") or {}).get("id")
            if str(row_league) != str(current_league):
                continue
            if _number(row.get("home_yellow_cards")) is None or _number(row.get("away_yellow_cards")) is None:
                continue
            card_rows.append(row)
    referee_name = (match.get("league") or {}).get("referee")
    referee_card_sample = sum(
        1 for row in card_rows
        if referee_name and str(row.get("referee") or "").strip().casefold() == str(referee_name).strip().casefold()
    )
    goal_features = {
        "home_goals_for_avg": _history_number(history, "home_goals_for"),
        "home_goals_against_avg": _history_number(history, "home_goals_against"),
        "away_goals_for_avg": _history_number(history, "away_goals_for"),
        "away_goals_against_avg": _history_number(history, "away_goals_against"),
        "home_goal_sample": history.get("home_goal_sample"), "away_goal_sample": history.get("away_goal_sample"),
        "current_home_goals": _number(goals.get("home")), "current_away_goals": _number(goals.get("away")),
    }
    corner_features = {
        "home_corners_for_avg": _history_number(history, "home_corners_for"),
        "home_corners_against_avg": _history_number(history, "home_corners_against"),
        "away_corners_for_avg": _history_number(history, "away_corners_for"),
        "away_corners_against_avg": _history_number(history, "away_corners_against"),
        "home_corner_sample": history.get("home_corner_sample"), "away_corner_sample": history.get("away_corner_sample"),
        "live_home_corners": stat(home_stats, "corners"), "live_away_corners": stat(away_stats, "corners"),
    }
    live_features = {
        "minute": _number(status.get("elapsed")),
        "home_shots_total": stat(home_stats, "shots_total"), "away_shots_total": stat(away_stats, "shots_total"),
        "home_shots_on_target": stat(home_stats, "shots_on_target"), "away_shots_on_target": stat(away_stats, "shots_on_target"),
        "home_possession": stat(home_stats, "possession"), "away_possession": stat(away_stats, "possession"),
        "home_yellow_cards": home_yellow, "away_yellow_cards": away_yellow,
    }
    return {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "fixture_id": match.get("fixture_id"), "league_id": (match.get("league") or {}).get("id"),
        "league_name": (match.get("league") or {}).get("name"),
        "season": (match.get("league") or {}).get("season"),
        "home_team_id": home.get("id"), "away_team_id": away.get("id"),
        "teams": {"home": home.get("name"), "away": away.get("name")},
        "referee": (match.get("league") or {}).get("referee"),
        "goals": goal_features, "corners": corner_features,
        "cards": {"current_home_yellow_cards": home_yellow, "current_away_yellow_cards": away_yellow,
                  "current_total_yellow_cards": home_yellow + away_yellow if home_yellow is not None and away_yellow is not None else None,
                  "historical_sample": len(card_rows), "referee_historical_sample": referee_card_sample},
        "live": live_features,
        "data_quality": {
            "history_available": bool(history.get("available")),
            "goal_history_missing": [k for k, v in goal_features.items() if k.endswith("_avg") and v is None],
            "corner_history_missing": [k for k, v in corner_features.items() if k.endswith("_avg") and v is None],
            "statistics_available": bool(statistics.get("available")),
            "statistics_missing_teams": list(statistics.get("missing_teams") or []),
            "goal_sample": min(_count(goal_features["home_goal_sample"]), _count(goal_features["away_goal_sample"])),
            "corner_sample": min(_count(corner_features["home_corner_sample"]), _count(corner_features["away_corner_sample"])),
            "card_history_available": bool(card_rows),
            "card_history_sample": len(card_rows),
            "referee_card_history_sample": referee_card_sample,
        },
    }
