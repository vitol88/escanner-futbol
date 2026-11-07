"""Data-coverage diagnostics for Football Lab's experimental model families.

Pure reporting only: no network calls, persistence, Streamlit state, or picks.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _count(value: Any) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _same(value: Any, target: Any) -> bool:
    if value is None or target is None:
        return False
    normalize = lambda item: " ".join(str(item).strip().casefold().split())
    return normalize(value) == normalize(target)


def _market_status(sample: int, minimum: int) -> dict[str, Any]:
    return {
        "sample": sample,
        "minimum_required": minimum,
        "available": sample > 0,
        "sufficient": sample >= minimum,
        "status": "sufficient" if sample >= minimum else ("partial" if sample > 0 else "missing"),
    }


def build_data_coverage_report(
    features: dict[str, Any],
    history: dict[str, Any] | None = None,
    *,
    live_corner_history_rows: list[dict[str, Any]] | None = None,
    minimum_team_sample: int = 5,
    minimum_referee_sample: int = 8,
    minimum_live_corner_sample: int = 8,
) -> dict[str, Any]:
    """Report data coverage separately from statistical validity or calibration.

    Goal/corner sample counts are the valid venue-specific samples already produced
    by automatic_history. Card samples are counted from the same pre-kickoff,
    league-matched card rows consumed by card_model. Live-corner history is a
    separate optional source and is never inferred from the automatic team history.
    """
    features = features if isinstance(features, dict) else {}
    history = history if isinstance(history, dict) else {}
    quality = features.get("data_quality") or {}
    goals = features.get("goals") or {}
    corners = features.get("corners") or {}
    cards = features.get("cards") or {}

    team_min = max(1, _count(minimum_team_sample))
    referee_min = max(1, _count(minimum_referee_sample))
    live_min = max(1, _count(minimum_live_corner_sample))

    goal_home = _count(goals.get("home_goal_sample"))
    goal_away = _count(goals.get("away_goal_sample"))
    corner_home = _count(corners.get("home_corner_sample"))
    corner_away = _count(corners.get("away_corner_sample"))

    league_id = features.get("league_id")
    home_id = features.get("home_team_id")
    away_id = features.get("away_team_id")
    referee = features.get("referee")
    card_rows = []
    for row in history.get("card_history_rows", []) if isinstance(history.get("card_history_rows"), list) else []:
        if not isinstance(row, dict) or not _same(row.get("league_id"), league_id):
            continue
        if _number(row.get("home_yellow_cards")) is None or _number(row.get("away_yellow_cards")) is None:
            continue
        card_rows.append(row)

    home_card_sample = sum(1 for row in card_rows if _same(row.get("home_team_id"), home_id))
    away_card_sample = sum(1 for row in card_rows if _same(row.get("away_team_id"), away_id))
    referee_card_sample = sum(
        1 for row in card_rows
        if referee and _same(row.get("referee"), referee)
    )

    # The current automatic history only contains matches involving the two
    # selected teams. It cannot provide a representative league-wide referee prior.
    league_referee_prior = {
        "available": False,
        "sample": 0,
        "minimum_required": None,
        "reason": "No existe todavía una muestra independiente y representativa de toda la liga.",
    }

    live_rows = live_corner_history_rows if isinstance(live_corner_history_rows, list) else []
    live_samples: dict[str, dict[str, Any]] = {}
    league_label = features.get("league_name") or league_id
    live_minute = _number((features.get("live") or {}).get("minute"))
    for side, team_name, venue in (
        ("home", (features.get("teams") or {}).get("home"), "home"),
        ("away", (features.get("teams") or {}).get("away"), "away"),
    ):
        matched = []
        for row in live_rows:
            if not isinstance(row, dict):
                continue
            if not _same(row.get("league"), league_label):
                continue
            if not _same(row.get("team"), team_name) or not _same(row.get("venue"), venue):
                continue
            required = ("minute", "corners_for", "corners_against", "corners_for_after", "corners_against_after")
            values = {key: _number(row.get(key)) for key in required}
            if any(value is None for value in values.values()):
                continue
            # The existing estimator uses the exact minute bucket; do not inflate
            # coverage by counting rows from other match minutes.
            if live_minute is None or int(values["minute"]) != int(live_minute):
                continue
            matched.append(row)
        live_samples[side] = _market_status(len(matched), live_min)

    markets = {
        "prematch_goals": {
            "home": _market_status(goal_home, team_min),
            "away": _market_status(goal_away, team_min),
        },
        "prematch_corners": {
            "home": _market_status(corner_home, team_min),
            "away": _market_status(corner_away, team_min),
        },
        "prematch_yellow_cards": {
            "home_team_at_home": _market_status(home_card_sample, team_min),
            "away_team_away": _market_status(away_card_sample, team_min),
            "referee": _market_status(referee_card_sample, referee_min),
            "league_referee_prior": league_referee_prior,
        },
        "live_remaining_corners": live_samples,
    }
    return {
        "schema_version": "1.0",
        "fixture_id": features.get("fixture_id"),
        "league_id": league_id,
        "markets": markets,
        "ready": {
            "prematch_goals": markets["prematch_goals"]["home"]["sufficient"] and markets["prematch_goals"]["away"]["sufficient"],
            "prematch_corners": markets["prematch_corners"]["home"]["sufficient"] and markets["prematch_corners"]["away"]["sufficient"],
            "prematch_yellow_cards": markets["prematch_yellow_cards"]["home_team_at_home"]["sufficient"] and markets["prematch_yellow_cards"]["away_team_away"]["sufficient"],
            "referee_adjustment": markets["prematch_yellow_cards"]["referee"]["sufficient"] and league_referee_prior["available"],
            "live_remaining_corners": markets["live_remaining_corners"]["home"]["sufficient"] or markets["live_remaining_corners"]["away"]["sufficient"],
        },
        "warnings": [
            "Cobertura disponible no equivale a calibración, precisión ni rentabilidad.",
            "Los mínimos indican únicamente si el baseline experimental puede ejecutarse.",
            "El histórico automático de córners prepartido y el histórico minuto-a-minuto de córners en vivo son fuentes distintas.",
            "No se estima un promedio arbitral de liga a partir del historial de solo dos equipos.",
        ],
    }
