"""Conservative, pure evaluation layer for Football Lab betting opportunities.

This module does not fetch data or invent probabilities. Callers must provide a
model probability and a verified price for the exact same market/selection.
"""
from __future__ import annotations

from typing import Any, Iterable

SUPPORTED_MARKETS = {
    "corners", "goals", "yellow_cards", "btts", "draw"
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and 0.0 <= result <= 1000000 else None


def evaluate_opportunity(
    candidate: dict[str, Any],
    *,
    min_probability: float = 0.0,
    min_ev: float = 0.02,
    min_odds: float = 1.35,
    max_odds: float = 10.0,
) -> dict[str, Any]:
    """Evaluate one exact market selection; return eligible=False on bad inputs.

    candidate keys: market, selection, probability (0..1), odds, odds_verified,
    fixture_id, fixture, minute, score, bookmaker, source.
    EV is decimal expected return per unit stake: p * odds - 1.
    """
    market = str(candidate.get("market") or "").strip().lower()
    selection = str(candidate.get("selection") or "").strip()
    probability = _number(candidate.get("probability"))
    odds = _number(candidate.get("odds"))
    reasons: list[str] = []

    if market not in SUPPORTED_MARKETS:
        reasons.append("unsupported_market")
    if not selection:
        reasons.append("missing_selection")
    if probability is None or not 0.0 <= probability <= 1.0:
        reasons.append("invalid_probability")
    if odds is None or odds <= 1.0:
        reasons.append("invalid_odds")
    if candidate.get("odds_verified") is not True:
        reasons.append("odds_not_verified")
    if not candidate.get("fixture_id"):
        reasons.append("missing_fixture_id")
    if not candidate.get("bookmaker"):
        reasons.append("missing_bookmaker")

    if reasons:
        return {"eligible": False, "reasons": reasons}

    assert probability is not None and odds is not None
    implied_probability = 1.0 / odds
    edge = probability - implied_probability
    expected_value = probability * odds - 1.0

    if probability < min_probability:
        reasons.append("probability_below_minimum")
    if not min_odds <= odds <= max_odds:
        reasons.append("odds_outside_range")
    if expected_value < min_ev:
        reasons.append("expected_value_below_minimum")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "market": market,
        "selection": selection,
        "probability": round(probability, 4),
        "odds": round(odds, 3),
        "implied_probability": round(implied_probability, 4),
        "edge": round(edge, 4),
        "expected_value": round(expected_value, 4),
        "fixture_id": str(candidate["fixture_id"]),
        "fixture": str(candidate.get("fixture") or ""),
        "minute": candidate.get("minute"),
        "score": candidate.get("score"),
        "bookmaker": str(candidate["bookmaker"]),
        "source": str(candidate.get("source") or "model"),
    }


def evaluate_candidates(
    candidates: Iterable[dict[str, Any]],
    **thresholds: Any,
) -> list[dict[str, Any]]:
    """Evaluate candidates and return eligible opportunities only."""
    evaluated = [evaluate_opportunity(item, **thresholds) for item in candidates]
    return [item for item in evaluated if item.get("eligible")]
