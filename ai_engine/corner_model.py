"""Pre-match independent-Poisson baseline for corner markets.

Research baseline only. It consumes feature_builder output and does not fetch data,
read Streamlit state, or emit betting recommendations.
"""
from __future__ import annotations

import math
from typing import Any


MODEL_VERSION = "0.1.0"
DEFAULT_MINIMUM_SAMPLE = 5
TOTAL_LINES = (6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5)


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
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _poisson_pmf(rate: float, count: int) -> float:
    if count < 0:
        return 0.0
    if rate == 0:
        return 1.0 if count == 0 else 0.0
    return math.exp(-rate + count * math.log(rate) - math.lgamma(count + 1))


def _distribution(rate: float, max_count: int = 35) -> list[float]:
    values = [_poisson_pmf(rate, count) for count in range(max_count + 1)]
    mass = sum(values)
    return [value / mass for value in values] if mass else [1.0] + [0.0] * max_count


def estimate_prematch_corners(
    features: dict[str, Any],
    *,
    minimum_sample: int = DEFAULT_MINIMUM_SAMPLE,
    max_corners_per_team: int = 35,
) -> dict[str, Any]:
    """Estimate expected corners and market probabilities from venue averages.

    Home lambda = mean(home corners-for at home, away corners-against away).
    Away lambda = mean(away corners-for away, home corners-against at home).
    """
    try:
        minimum = max(1, int(minimum_sample))
    except (TypeError, ValueError, OverflowError):
        minimum = DEFAULT_MINIMUM_SAMPLE
    unavailable = {
        "available": False,
        "model_version": MODEL_VERSION,
        "model_label": "Baseline Poisson independiente de córners; experimental y no calibrado",
        "reason": None,
    }
    if not isinstance(features, dict):
        unavailable["reason"] = "No se recibieron variables válidas."
        return unavailable

    corners = features.get("corners") or {}
    quality = features.get("data_quality") or {}
    home_sample = _valid_sample(corners.get("home_corner_sample"))
    away_sample = _valid_sample(corners.get("away_corner_sample"))
    if min(home_sample, away_sample) < minimum:
        unavailable["reason"] = (
            f"Muestra insuficiente: local={home_sample}, visitante={away_sample}; "
            f"mínimo requerido={minimum} por equipo."
        )
        unavailable["sample"] = {"home": home_sample, "away": away_sample}
        return unavailable

    home_for = _valid_rate(corners.get("home_corners_for_avg"))
    home_against = _valid_rate(corners.get("home_corners_against_avg"))
    away_for = _valid_rate(corners.get("away_corners_for_avg"))
    away_against = _valid_rate(corners.get("away_corners_against_avg"))
    if any(value is None for value in (home_for, home_against, away_for, away_against)):
        unavailable["reason"] = "Faltan promedios de córners por localía para ambos equipos."
        return unavailable

    home_lambda = (home_for + away_against) / 2.0
    away_lambda = (away_for + home_against) / 2.0
    total_lambda = home_lambda + away_lambda
    limit = max(10, min(_valid_sample(max_corners_per_team), 50))
    home_dist = _distribution(home_lambda, limit)
    away_dist = _distribution(away_lambda, limit)

    total_dist: dict[int, float] = {}
    for home_count, home_probability in enumerate(home_dist):
        for away_count, away_probability in enumerate(away_dist):
            total = home_count + away_count
            total_dist[total] = total_dist.get(total, 0.0) + home_probability * away_probability

    total_markets = {}
    for line in TOTAL_LINES:
        total_markets[str(line)] = {
            "over": sum(prob for total, prob in total_dist.items() if total > line),
            "under": sum(prob for total, prob in total_dist.items() if total < line),
        }

    team_markets = {}
    for side, distribution in (("home", home_dist), ("away", away_dist)):
        team_markets[side] = {
            str(line): {
                "over": sum(prob for count, prob in enumerate(distribution) if count > line),
                "under": sum(prob for count, prob in enumerate(distribution) if count < line),
            }
            for line in (2.5, 3.5, 4.5, 5.5, 6.5)
        }

    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "model_label": "Baseline Poisson independiente de córners; experimental y no calibrado",
        "reason": None,
        "expected_home_corners": home_lambda,
        "expected_away_corners": away_lambda,
        "expected_total_corners": total_lambda,
        "probability_total_corners": total_markets,
        "probability_team_corners": team_markets,
        "sample": {"home": home_sample, "away": away_sample},
        "data_quality": {
            "history_available": bool(quality.get("history_available")),
            "minimum_sample_required": minimum,
            "distribution_max_corners_per_team": limit,
        },
        "warnings": [
            "No está calibrado ni validado mediante backtesting cronológico.",
            "Supone independencia entre los córners de ambos equipos.",
            "Usa Poisson como baseline; debe compararse con binomial negativa si la dispersión histórica supera la media.",
            "No incorpora cuotas, valor esperado ni recomendaciones de apuesta.",
        ],
    }
