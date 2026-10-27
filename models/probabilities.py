"""Exploratory live goal-market probabilities.

League-average inputs are intentionally labelled as preliminary. These functions do
not model team strength, red cards, game state, extra time, or bookmaker margin.
They are research outputs, not validated betting signals.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_league_baselines() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "data" / "league_baselines.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def find_league_baseline(
    country: str | None,
    league_name: str | None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Match a league by both country and known aliases to avoid Serie A ambiguity."""
    data = data or load_league_baselines()
    country_key = normalize_name(country)
    league_key = normalize_name(league_name)
    for league in data.get("leagues", []):
        country_names = [league.get("country", ""), *league.get("country_aliases", [])]
        country_matches = country_key in {normalize_name(name) for name in country_names}
        league_names = [league.get("league", ""), *league.get("aliases", [])]
        league_matches = league_key in {normalize_name(name) for name in league_names}
        if country_matches and league_matches:
            return league
    return None


def poisson_pmf(rate: float, count: int) -> float:
    if rate < 0 or count < 0:
        return 0.0
    if rate == 0:
        return 1.0 if count == 0 else 0.0
    return math.exp(-rate + count * math.log(rate) - math.lgamma(count + 1))


def poisson_at_least(rate: float, count: int) -> float:
    """P(Poisson(rate) >= count), with safe handling of zero/negative targets."""
    if count <= 0:
        return 1.0
    cdf = sum(poisson_pmf(rate, k) for k in range(count))
    return min(1.0, max(0.0, 1.0 - cdf))


def estimate_live_goal_markets(
    *,
    country: str | None,
    league_name: str | None,
    score_home: int | None,
    score_away: int | None,
    elapsed_minute: int | None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return provisional remaining-goal, draw, and BTTS probabilities.

    Estimates are withheld for missing scores/minute, unsupported competitions,
    or league samples below the configured minimum.
    """
    result: dict[str, Any] = {"available": False, "reason": None}
    baseline = find_league_baseline(country, league_name, data)
    if baseline is None:
        result["reason"] = "No hay una referencia histórica compatible para esta liga."
        return result
    minimum = int((data or load_league_baselines()).get("minimum_matches_for_estimate", 30))
    matches = int(baseline.get("matches", 0))
    if matches < minimum:
        result["reason"] = f"Muestra histórica insuficiente: {matches} partidos; se requieren al menos {minimum}."
        result["baseline_matches"] = matches
        return result
    if not isinstance(score_home, int) or not isinstance(score_away, int) or score_home < 0 or score_away < 0:
        result["reason"] = "El marcador no está disponible."
        return result
    if not isinstance(elapsed_minute, int) or elapsed_minute < 1:
        result["reason"] = "El minuto de juego no está disponible."
        return result

    minute = min(elapsed_minute, 90)
    remaining_fraction = max(0.0, (90 - minute) / 90.0)
    home_rate = max(0.0, float(baseline["avg_home_goals"]) * remaining_fraction)
    away_rate = max(0.0, float(baseline["avg_away_goals"]) * remaining_fraction)
    total_rate = home_rate + away_rate
    current_total = score_home + score_away

    # Evaluate only future total-goal targets, relative to the current score.
    # This prevents already-won markets from being shown as new live opportunities.
    over = {}
    for additional_goals in (1, 2, 3):
        final_total_target = current_total + additional_goals
        over[str(final_total_target)] = poisson_at_least(total_rate, additional_goals)

    draw_probability = 0.0
    # Independent Poisson approximation for future goals; truncate where tail mass is negligible.
    for home_future in range(16):
        away_future = score_home + home_future - score_away
        if 0 <= away_future < 16:
            draw_probability += poisson_pmf(home_rate, home_future) * poisson_pmf(away_rate, away_future)
    draw_probability = min(1.0, max(0.0, draw_probability))

    if score_home > 0 and score_away > 0:
        btts_probability = 1.0
    elif score_home == 0 and score_away == 0:
        btts_probability = (1.0 - math.exp(-home_rate)) * (1.0 - math.exp(-away_rate))
    elif score_home == 0:
        btts_probability = 1.0 - math.exp(-home_rate)
    else:
        btts_probability = 1.0 - math.exp(-away_rate)

    result.update({
        "available": True,
        "reason": None,
        "baseline_league": baseline["league"],
        "baseline_matches": matches,
        "minute_used": minute,
        "expected_home_goals_remaining": home_rate,
        "expected_away_goals_remaining": away_rate,
        "expected_total_goals_remaining": total_rate,
        "current_total_goals": current_total,
        "over_total_goals": over,
        "draw_final": draw_probability,
        "btts_final": btts_probability,
        "btts_already_settled": score_home > 0 and score_away > 0,
        "model_label": "Exploratorio por promedio de liga; no calibrado ni validado para apuestas",
    })
    return result


def corner_pace_per_90(total_corners: int | float | None, elapsed_minute: int | None) -> float | None:
    """Descriptive live pace only; deliberately not a probability or betting signal."""
    if total_corners is None or elapsed_minute is None or elapsed_minute <= 0:
        return None
    if not isinstance(total_corners, (int, float)) or total_corners < 0:
        return None
    if not isinstance(elapsed_minute, int):
        return None
    return float(total_corners) * 90.0 / min(elapsed_minute, 90)
