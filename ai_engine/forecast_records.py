"""Convert corner-model outputs into canonical forecast records.

This is a pure adapter: it does not write CSVs, call APIs, or emit betting signals.
Only probabilities explicitly produced by the corner models are mapped.
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
    """Map available pre-match/live corner probabilities into schema records.

    Pre-match outputs contain total and team over/under lines. Live outputs
    contain empirical probabilities for at least one or two remaining corners,
    represented as over 0.5 and over 1.5 on the remaining-corners market.
    """
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
    model_id = "prematch_corner_poisson" if phase == "pre_match" else "live_remaining_corners_empirical"
    candidates: list[tuple[str, str, str, Any]] = []

    if phase == "pre_match":
        total = model_result.get("probability_total_corners") or {}
        for line, selections in total.items():
            if not isinstance(selections, dict):
                continue
            for selection in ("over", "under"):
                candidates.append(("total_corners", selection, str(line), selections.get(selection)))
        teams = model_result.get("probability_team_corners") or {}
        for side, market in (("home", "home_team_corners"), ("away", "away_team_corners")):
            side_lines = teams.get(side) or {}
            for line, selections in side_lines.items():
                if not isinstance(selections, dict):
                    continue
                for selection in ("over", "under"):
                    candidates.append((market, selection, str(line), selections.get(selection)))
    else:
        candidates.extend([
            ("remaining_corners", "over", "0.5", model_result.get("probability_remaining_at_least_1")),
            ("remaining_corners", "over", "1.5", model_result.get("probability_remaining_at_least_2")),
        ])

    records = []
    for market, selection, line, raw_probability in candidates:
        probability = _probability(raw_probability)
        if probability is None:
            continue
        row = {
            **base,
            "market": market,
            "market_type": "corners",
            "selection": selection,
            "line": line,
            "probability": probability,
            "model_id": model_id,
        }
        normalized = normalize_prediction_record(row)
        if normalized["valid"]:
            records.append(normalized)
    return records
