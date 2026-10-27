"""Exploratory live goal-market probabilities.

League-average inputs are intentionally labelled as preliminary. These functions do
not model team strength, detailed game state, extra time, or bookmaker margin. Live
shots/corners apply only a small bounded adjustment, and red cards apply a small
symmetric adjustment; neither effect has been calibrated. These are research outputs,
not validated betting signals.
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
    live_stats: dict[str, Any] | None = None,
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
    # Conservative live-activity adjustment. It only applies when observed stats are
    # available; missing stats never become zero and cannot create a false signal.
    live_stats = live_stats or {}
    def valid_nonnegative(key: str) -> float | None:
        value = live_stats.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number >= 0 else None

    shots_on = valid_nonnegative("shots_on_total")
    corners = valid_nonnegative("corners_total")
    reds = valid_nonnegative("red_cards_total")
    activity_factor = 1.0
    activity_components = []
    if isinstance(elapsed_minute, int) and elapsed_minute >= 15:
        # Compare observed activity with modest time-based expectations. Clamp the
        # multiplier so small samples cannot dominate the league baseline.
        if shots_on is not None:
            expected_sot = max(0.5, elapsed_minute * 0.065)
            activity_components.append(min(1.25, max(0.78, 1 + 0.10 * (shots_on - expected_sot) / max(1.0, expected_sot))) )
        if corners is not None:
            expected_corners = max(0.5, elapsed_minute * 0.09)
            activity_components.append(min(1.18, max(0.85, 1 + 0.06 * (corners - expected_corners) / max(1.0, expected_corners))) )
    if activity_components:
        activity_factor = sum(activity_components) / len(activity_components)
        home_rate *= activity_factor
        away_rate *= activity_factor
    # A red card can open the match, but its impact is uncertain; use a small
    # symmetric increase rather than guessing which side will score.
    if reds is not None and reds > 0:
        home_rate *= 1.08
        away_rate *= 1.08
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

    # Team-specific final goal thresholds. These are conditional probabilities
    # for each side to finish with at least 1, 2, or 3 goals, using league-average
    # remaining-goal rates. Thresholds already reached are marked as settled.
    home_goal_thresholds = {}
    away_goal_thresholds = {}
    for target in (1, 2, 3):
        home_needed = max(0, target - score_home)
        away_needed = max(0, target - score_away)
        home_goal_thresholds[str(target)] = {
            "probability": poisson_at_least(home_rate, home_needed),
            "already_settled": score_home >= target,
        }
        away_goal_thresholds[str(target)] = {
            "probability": poisson_at_least(away_rate, away_needed),
            "already_settled": score_away >= target,
        }

    result.update({
        "available": True,
        "reason": None,
        "baseline_league": baseline["league"],
        "baseline_matches": matches,
        "minute_used": minute,
        "expected_home_goals_remaining": home_rate,
        "expected_away_goals_remaining": away_rate,
        "expected_total_goals_remaining": total_rate,
        "live_activity_adjustment": round(activity_factor, 3),
        "live_stats_used": bool(activity_components or (reds is not None and reds > 0)),
        "live_stats_status": "ajuste moderado por actividad en vivo" if activity_components or (reds is not None and reds > 0) else "sin ajuste: estadísticas insuficientes",
        "probability_no_more_goals": poisson_pmf(total_rate, 0),
        "current_total_goals": current_total,
        "over_total_goals": over,
        "home_final_goals_at_least": home_goal_thresholds,
        "away_final_goals_at_least": away_goal_thresholds,
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
