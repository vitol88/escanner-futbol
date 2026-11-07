"""Convert experimental model outputs into canonical forecast records.

Pure adapters only: no CSV writes, API calls, or betting signals. Only explicit
probabilities emitted by each model are mapped; expected counts are not converted.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ai_engine.prediction_schema import normalize_prediction_record


def _probability(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and 0 <= result <= 1 else None


def _metadata(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": fixture.get("fixture_id"),
        "league_id": fixture.get("league_id"),
        "league": fixture.get("league"),
        "home": fixture.get("home"),
        "away": fixture.get("away"),
    }


def _build_records(
    candidates: list[tuple[str, str, str | None, Any]],
    model_result: dict[str, Any],
    fixture: dict[str, Any],
    *,
    phase: str,
    model_id: str,
    recorded_at: str | None,
    minute: int | None,
    score_home: int | None,
    score_away: int | None,
    snapshot_id: str | None,
    source: str,
) -> list[dict[str, Any]]:
    if not isinstance(model_result, dict) or not model_result.get("available"):
        return []
    if not isinstance(fixture, dict) or not fixture.get("fixture_id"):
        return []
    if phase not in {"pre_match", "live"}:
        return []
    if recorded_at is None:
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    base = {
        **_metadata(fixture),
        "recorded_at": recorded_at,
        "phase": phase,
        "minute": minute if phase == "live" else None,
        "score_home": score_home if phase == "live" else None,
        "score_away": score_away if phase == "live" else None,
        "model_version": model_result.get("model_version"),
        "source": source,
        "snapshot_id": snapshot_id,
    }
    records = []
    for market, selection, line, raw_probability in candidates:
        probability = _probability(raw_probability)
        if probability is None:
            continue
        normalized = normalize_prediction_record({
            **base,
            "market": market,
            "market_type": market,
            "selection": selection,
            "line": line,
            "probability": probability,
            "model_id": model_id,
        })
        if normalized["valid"]:
            records.append(normalized)
    return records


def build_corner_prediction_records(
    model_result: dict[str, Any],
    fixture: dict[str, Any],
    *,
    phase: str,
    recorded_at: str | None = None,
    minute: int | None = None,
    score_home: int | None = None,
    score_away: int | None = None,
    snapshot_id: str | None = None,
    source: str = "football_lab_corner_model",
) -> list[dict[str, Any]]:
    """Map pre-match total/team corners or live remaining-corner probabilities."""
    candidates: list[tuple[str, str, str | None, Any]] = []
    if phase == "pre_match":
        total = model_result.get("probability_total_corners") or {} if isinstance(model_result, dict) else {}
        for line, selections in total.items():
            if isinstance(selections, dict):
                for selection in ("over", "under"):
                    candidates.append(("total_corners", selection, str(line), selections.get(selection)))
        teams = model_result.get("probability_team_corners") or {} if isinstance(model_result, dict) else {}
        for side, market in (("home", "home_team_corners"), ("away", "away_team_corners")):
            for line, selections in (teams.get(side) or {}).items():
                if isinstance(selections, dict):
                    for selection in ("over", "under"):
                        candidates.append((market, selection, str(line), selections.get(selection)))
        model_id = "prematch_corner_poisson"
    elif phase == "live":
        candidates.extend([
            ("remaining_corners", "over", "0.5", model_result.get("probability_remaining_at_least_1") if isinstance(model_result, dict) else None),
            ("remaining_corners", "over", "1.5", model_result.get("probability_remaining_at_least_2") if isinstance(model_result, dict) else None),
        ])
        model_id = "live_remaining_corners_empirical"
    else:
        return []
    return _build_records(candidates, model_result, fixture, phase=phase, model_id=model_id,
        recorded_at=recorded_at, minute=minute, score_home=score_home, score_away=score_away,
        snapshot_id=snapshot_id, source=source)


def build_goal_prediction_records(
    model_result: dict[str, Any],
    fixture: dict[str, Any],
    *,
    recorded_at: str | None = None,
    source: str = "football_lab_goal_model",
) -> list[dict[str, Any]]:
    """Map explicit pre-match total-goal, 1X2, and BTTS probabilities."""
    if not isinstance(model_result, dict):
        return []
    candidates: list[tuple[str, str, str | None, Any]] = []
    for line, selections in (model_result.get("probability_total_goals") or {}).items():
        if isinstance(selections, dict):
            for selection in ("over", "under"):
                candidates.append(("total_goals", selection, str(line), selections.get(selection)))
    for selection, probability in (model_result.get("probability_1x2") or {}).items():
        if selection in {"home", "draw", "away"}:
            candidates.append(("match_result", selection, None, probability))
    candidates.append(("both_teams_to_score", "yes", None, model_result.get("probability_btts")))
    return _build_records(candidates, model_result, fixture, phase="pre_match",
        model_id="prematch_goal_poisson", recorded_at=recorded_at, minute=None,
        score_home=None, score_away=None, snapshot_id=None, source=source)


def build_yellow_card_prediction_records(
    model_result: dict[str, Any],
    fixture: dict[str, Any],
    *,
    recorded_at: str | None = None,
    source: str = "football_lab_yellow_card_model",
) -> list[dict[str, Any]]:
    """Map only explicit total-yellow-card over probabilities from the card model."""
    if not isinstance(model_result, dict):
        return []
    candidates = [
        ("total_yellow_cards", "over", str(line), probability)
        for line, probability in (model_result.get("probability_over") or {}).items()
    ]
    return _build_records(candidates, model_result, fixture, phase="pre_match",
        model_id="prematch_yellow_card_poisson", recorded_at=recorded_at, minute=None,
        score_home=None, score_away=None, snapshot_id=None, source=source)
