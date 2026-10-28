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
    recent_goals: int = 0,
    minutes_since_previous_scan: int | None = None,
) -> dict[str, Any]:
    """Return provisional remaining-goal, draw, and BTTS probabilities.

    Estimates are withheld for missing scores/minute, unsupported competitions,
    or league samples below the configured minimum.
    """
    result: dict[str, Any] = {"available": False, "reason": None}
    baseline = find_league_baseline(country, league_name, data)
    # If a league-specific baseline is missing, use a conservative generic
    # football baseline so a live match can still be evaluated from score, minute
    # and observed activity. Mark this fallback explicitly in the result.
    baseline_fallback = baseline is None
    if baseline is None:
        baseline = {
            "league": "Referencia genérica (sin muestra específica de liga)",
            "matches": 0,
            "avg_home_goals": 1.35,
            "avg_away_goals": 1.05,
        }
    minimum = int((data or load_league_baselines()).get("minimum_matches_for_estimate", 30))
    matches = int(baseline.get("matches", 0))
    if matches < minimum and not baseline_fallback:
        result["reason"] = f"Muestra histórica insuficiente: {matches} partidos; se usará referencia genérica si hay datos en vivo."
        # Do not withhold all signals solely because the competition sample is small.
        baseline_fallback = True
        baseline = {
            "league": "Referencia genérica (muestra de liga insuficiente)",
            "matches": matches,
            "avg_home_goals": 1.35,
            "avg_away_goals": 1.05,
        }
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
    current_total = score_home + score_away
    # Use the observed score as a weak signal of match pace. If the match has
    # already produced substantially more goals than the league baseline would
    # expect by this minute, modestly raise the remaining-goal rates. This is
    # deliberately capped: goals are not a reliable standalone predictor.
    expected_goals_so_far = (
        float(baseline.get("avg_home_goals", 0.0))
        + float(baseline.get("avg_away_goals", 0.0))
    ) * min(elapsed_minute, 90) / 90.0
    score_pace_factor = 1.0
    if elapsed_minute >= 15 and expected_goals_so_far > 0:
        score_pace_factor = min(
            1.35,
            max(0.90, 1.0 + 0.12 * (current_total - expected_goals_so_far)
                / max(1.0, expected_goals_so_far)),
        )
        home_rate *= score_pace_factor
        away_rate *= score_pace_factor
    # Recent goals between scans are a short-term tempo cue. Only use the signal
    # when the previous scan is recent (<=10 match minutes); cap its influence.
    recent_goal_factor = 1.0
    if isinstance(recent_goals, int) and recent_goals > 0 and isinstance(minutes_since_previous_scan, int) and 0 < minutes_since_previous_scan <= 10:
        recent_goal_factor = min(1.35, 1.0 + 0.12 * recent_goals)
        home_rate *= recent_goal_factor
        away_rate *= recent_goal_factor
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
    # Team-specific red-card adjustment. Conservative until historical data is fitted.
    red_home = valid_nonnegative("red_cards_home")
    red_away = valid_nonnegative("red_cards_away")
    if red_home is not None and red_home > 0:
        home_rate *= 0.88
        away_rate *= 1.12
    if red_away is not None and red_away > 0:
        away_rate *= 0.88
        home_rate *= 1.12
    if red_home is None and red_away is None and reds is not None and reds > 0:
        home_rate *= 1.05
        away_rate *= 1.05
    # Team-specific pressure: corners, shots on target and possession help distinguish
    # an 8-2 corner split from a match with the same total but no territorial imbalance.
    # These are deliberately small, capped exploratory multipliers (not calibrated).
    def team_value(key: str) -> float | None:
        return valid_nonnegative(key)

    corners_home = team_value("corners_home")
    corners_away = team_value("corners_away")
    shots_home = team_value("shots_on_home")
    shots_away = team_value("shots_on_away")
    possession_home = team_value("possession_home")
    possession_away = team_value("possession_away")

    home_pressure = 0.0
    away_pressure = 0.0
    pressure_evidence = 0
    if elapsed_minute >= 15:
        if corners_home is not None and corners_away is not None:
            # Normalize by minutes so 8 corners at 70' differs from 8 at 20'.
            expected_each = max(0.6, elapsed_minute * 0.045)
            home_pressure += max(-1.0, min(2.0, (corners_home - expected_each) / max(2.0, expected_each))) * 0.045
            away_pressure += max(-1.0, min(2.0, (corners_away - expected_each) / max(2.0, expected_each))) * 0.045
            pressure_evidence += 1
        if shots_home is not None and shots_away is not None:
            expected_sot_each = max(0.35, elapsed_minute * 0.032)
            home_pressure += max(-1.0, min(2.0, (shots_home - expected_sot_each) / max(1.0, expected_sot_each))) * 0.075
            away_pressure += max(-1.0, min(2.0, (shots_away - expected_sot_each) / max(1.0, expected_sot_each))) * 0.075
            pressure_evidence += 1
        if possession_home is not None and possession_away is not None:
            home_pressure += max(-0.20, min(0.20, (possession_home - possession_away) / 100.0)) * 0.30
            away_pressure += max(-0.20, min(0.20, (possession_away - possession_home) / 100.0)) * 0.30
            pressure_evidence += 1
    # A team trailing on the scoreboard may attack more; only use this when
    # pressure evidence is present, and do not turn pressure into a certainty.
    if pressure_evidence:
        if score_home < score_away:
            home_pressure += 0.035
        elif score_away < score_home:
            away_pressure += 0.035
        home_pressure = max(-0.12, min(0.18, home_pressure))
        away_pressure = max(-0.12, min(0.18, away_pressure))
        home_rate *= 1.0 + home_pressure
        away_rate *= 1.0 + away_pressure
    total_rate = home_rate + away_rate

    # Evaluate only future total-goal targets, relative to the current score.
    # This prevents already-won markets from being shown as new live opportunities.
    over = {}
    for additional_goals in (1, 2, 3):
        final_total_target = current_total + additional_goals
        over[str(final_total_target)] = poisson_at_least(total_rate, additional_goals)
    under = {}
    for line in (1.5, 2.5, 3.5, 4.5):
        max_future_goals = math.floor(line) - current_total
        probability = sum(poisson_pmf(total_rate, n) for n in range(max_future_goals + 1)) if max_future_goals >= 0 else 0.0
        under[str(line)] = min(1.0, max(0.0, probability))

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
        "baseline_fallback": baseline_fallback,
        "minute_used": minute,
        "expected_home_goals_remaining": home_rate,
        "expected_away_goals_remaining": away_rate,
        "expected_total_goals_remaining": total_rate,
        "live_activity_adjustment": round(activity_factor, 3),
        "score_pace_adjustment": round(score_pace_factor, 3),
        "recent_goal_adjustment": round(recent_goal_factor, 3),
        "recent_goals_observed": recent_goals if isinstance(recent_goals, int) else 0,
        "live_stats_used": bool(activity_components or (reds is not None and reds > 0)),
        "live_stats_status": "ajuste moderado por actividad en vivo" if activity_components or (reds is not None and reds > 0) else "sin ajuste: estadísticas insuficientes",
        "probability_no_more_goals": poisson_pmf(total_rate, 0),
        "current_total_goals": current_total,
        "over_total_goals": over,
        "under_total_goals": under,
        "home_final_goals_at_least": home_goal_thresholds,
        "away_final_goals_at_least": away_goal_thresholds,
        "draw_final": draw_probability,
        "btts_final": btts_probability,
        "btts_already_settled": score_home > 0 and score_away > 0,
        "model_label": "Exploratorio por promedio de liga/genérico y ritmo observado; no calibrado ni validado para apuestas",
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
