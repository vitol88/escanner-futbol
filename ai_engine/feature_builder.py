"""Build model-ready features from shared snapshots and existing history outputs.

This layer deliberately does not estimate probabilities. It only assembles
validated inputs for goal/corner models and preserves missing values.
"""
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


def build_model_features(
    snapshot: dict[str, Any],
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return stable goal/corner feature groups for one match.

    `history` is the existing output of build_automatic_history; this function
    does not fetch data or recalculate historical averages.
    """
    history = history if isinstance(history, dict) else {}
    match = snapshot.get("match") if isinstance(snapshot, dict) else {}
    match = match if isinstance(match, dict) else {}
    teams = match.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    statistics = snapshot.get("statistics") if isinstance(snapshot, dict) else {}
    statistics = statistics if isinstance(statistics, dict) else {}
    home_stats = (statistics.get("home") or {}).get("values") or {}
    away_stats = (statistics.get("away") or {}).get("values") or {}
    status = match.get("status") or {}
    goals = match.get("goals") or {}

    def stat(side: dict[str, Any], key: str) -> float | None:
        entry = side.get(key)
        if isinstance(entry, dict):
            return _number(entry.get("value"))
        return _number(entry)

    goal_features = {
        "home_goals_for_avg": _history_number(history, "home_goals_for"),
        "home_goals_against_avg": _history_number(history, "home_goals_against"),
        "away_goals_for_avg": _history_number(history, "away_goals_for"),
        "away_goals_against_avg": _history_number(history, "away_goals_against"),
        "home_goal_sample": history.get("home_goal_sample"),
        "away_goal_sample": history.get("away_goal_sample"),
        "current_home_goals": _number(goals.get("home")),
        "current_away_goals": _number(goals.get("away")),
    }
    corner_features = {
        "home_corners_for_avg": _history_number(history, "home_corners_for"),
        "home_corners_against_avg": _history_number(history, "home_corners_against"),
        "away_corners_for_avg": _history_number(history, "away_corners_for"),
        "away_corners_against_avg": _history_number(history, "away_corners_against"),
        "home_corner_sample": history.get("home_corner_sample"),
        "away_corner_sample": history.get("away_corner_sample"),
        "live_home_corners": stat(home_stats, "corners"),
        "live_away_corners": stat(away_stats, "corners"),
    }
    live_features = {
        "minute": _number(status.get("elapsed")),
        "home_shots_total": stat(home_stats, "shots_total"),
        "away_shots_total": stat(away_stats, "shots_total"),
        "home_shots_on_target": stat(home_stats, "shots_on_target"),
        "away_shots_on_target": stat(away_stats, "shots_on_target"),
        "home_possession": stat(home_stats, "possession"),
        "away_possession": stat(away_stats, "possession"),
        "home_yellow_cards": stat(home_stats, "yellow_cards"),
        "away_yellow_cards": stat(away_stats, "yellow_cards"),
    }

    missing_goal = [key for key, value in goal_features.items()
                    if key.endswith("_avg") and value is None]
    missing_corner = [key for key, value in corner_features.items()
                      if key.endswith("_avg") and value is None]
    return {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "fixture_id": match.get("fixture_id"),
        "league_id": (match.get("league") or {}).get("id"),
        "season": (match.get("league") or {}).get("season"),
        "teams": {"home": home.get("name"), "away": away.get("name")},
        "goals": goal_features,
        "corners": corner_features,
        "live": live_features,
        "data_quality": {
            "history_available": bool(history.get("available")),
            "goal_history_missing": missing_goal,
            "corner_history_missing": missing_corner,
            "statistics_available": bool(statistics.get("available")),
            "statistics_missing_teams": list(statistics.get("missing_teams") or []),
            "goal_sample": min(
                _count(goal_features["home_goal_sample"]),
                _count(goal_features["away_goal_sample"]),
            ),
            "corner_sample": min(
                _count(corner_features["home_corner_sample"]),
                _count(corner_features["away_corner_sample"]),
            ),
        },
    }
