"""Pre-match independent-Poisson baseline for goal-market research.

This is an intentionally simple benchmark, not a calibrated betting model.
It consumes feature_builder output and never fetches data or emits recommendations.
"""
from __future__ import annotations

import math
from typing import Any


MODEL_VERSION = "0.1.0"
DEFAULT_MINIMUM_SAMPLE = 5


def _valid_rate(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(rate) or rate < 0:
        return None
    return rate


def _valid_sample(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _poisson_pmf(rate: float, goals: int) -> float:
    if goals < 0:
        return 0.0
    if rate == 0:
        return 1.0 if goals == 0 else 0.0
    return math.exp(-rate + goals * math.log(rate) - math.lgamma(goals + 1))


def estimate_prematch_goals(
    features: dict[str, Any],
    *,
    minimum_sample: int = DEFAULT_MINIMUM_SAMPLE,
    max_goals: int = 12,
) -> dict[str, Any]:
    """Estimate score/goal distributions from venue-specific recent averages.

    Home expected goals = mean(home goals-for at home, away goals-against away).
    Away expected goals = mean(away goals-for away, home goals-against at home).
    """
    unavailable = {
        "available": False,
        "model_version": MODEL_VERSION,
        "model_label": "Baseline Poisson independiente; experimental y no calibrado",
        "reason": None,
    }
    if not isinstance(features, dict):
        unavailable["reason"] = "No se recibieron variables válidas."
        return unavailable
    goals = features.get("goals") or {}
    quality = features.get("data_quality") or {}
    home_sample = _valid_sample(goals.get("home_goal_sample"))
    away_sample = _valid_sample(goals.get("away_goal_sample"))
    if min(home_sample, away_sample) < max(1, int(minimum_sample)):
        unavailable["reason"] = (
            f"Muestra insuficiente: local={home_sample}, visitante={away_sample}; "
            f"mínimo requerido={max(1, int(minimum_sample))} por equipo."
        )
        unavailable["sample"] = {"home": home_sample, "away": away_sample}
        return unavailable

    home_for = _valid_rate(goals.get("home_goals_for_avg"))
    home_against = _valid_rate(goals.get("home_goals_against_avg"))
    away_for = _valid_rate(goals.get("away_goals_for_avg"))
    away_against = _valid_rate(goals.get("away_goals_against_avg"))
    if any(value is None for value in (home_for, home_against, away_for, away_against)):
        unavailable["reason"] = "Faltan promedios de goles por localía para ambos equipos."
        return unavailable

    home_lambda = (home_for + away_against) / 2.0
    away_lambda = (away_for + home_against) / 2.0
    limit = max(5, min(int(max_goals), 20))
    home_distribution = [_poisson_pmf(home_lambda, n) for n in range(limit + 1)]
    away_distribution = [_poisson_pmf(away_lambda, n) for n in range(limit + 1)]
    # Normalize the truncated grid so 1X2/BTTS probabilities sum consistently.
    home_total = sum(home_distribution)
    away_total = sum(away_distribution)
    home_distribution = [p / home_total for p in home_distribution]
    away_distribution = [p / away_total for p in away_distribution]

    home_win = draw = away_win = 0.0
    btts = 0.0
    total_distribution: dict[int, float] = {}
    for h, ph in enumerate(home_distribution):
        for a, pa in enumerate(away_distribution):
            probability = ph * pa
            if h > a:
                home_win += probability
            elif h == a:
                draw += probability
            else:
                away_win += probability
            if h > 0 and a > 0:
                btts += probability
            total_distribution[h + a] = total_distribution.get(h + a, 0.0) + probability

    totals = {}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        totals[str(line)] = {
            "over": sum(p for total, p in total_distribution.items() if total > line),
            "under": sum(p for total, p in total_distribution.items() if total < line),
        }

    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "model_label": "Baseline Poisson independiente; experimental y no calibrado",
        "reason": None,
        "expected_home_goals": home_lambda,
        "expected_away_goals": away_lambda,
        "expected_total_goals": home_lambda + away_lambda,
        "probability_1x2": {
            "home": home_win,
            "draw": draw,
            "away": away_win,
        },
        "probability_btts": btts,
        "probability_total_goals": totals,
        "sample": {"home": home_sample, "away": away_sample},
        "data_quality": {
            "history_available": bool(quality.get("history_available")),
            "minimum_sample_required": max(1, int(minimum_sample)),
            "distribution_max_goals_per_team": limit,
        },
        "warnings": [
            "No está calibrado ni validado mediante backtesting cronológico.",
            "Supone independencia entre goles de ambos equipos.",
            "No incorpora cuotas, valor esperado ni recomendaciones de apuesta.",
        ],
    }
