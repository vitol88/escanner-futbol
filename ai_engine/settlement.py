"""Strict, deterministic settlement helpers for explicitly supplied final match data.

This module never fetches results or writes to the ledger. Unsupported or
ambiguous market labels are withheld for manual review.
"""
from __future__ import annotations

import math
import re
from typing import Any


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _line_from_selection(selection: str, direction: str) -> float | None:
    match = re.fullmatch(
        rf"\s*{direction}\s+(\d+(?:\.\d+)?)\s*",
        selection,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        value = float(match.group(1))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def resolve_binary_outcome(
    *,
    market_type: str,
    selection: str,
    final_home_score: Any = None,
    final_away_score: Any = None,
    final_total_corners: Any = None,
    final_total_yellow_cards: Any = None,
) -> dict[str, Any]:
    """Resolve only supported, unambiguous binary selections from final data.

    Canonical selection forms:
      goals: "Over 2.5", "Under 2.5", "Home", "Draw", "Away"
      draw: "Empate final" or "Draw"
      btts: "Yes" / "No" (also "Ambos equipos marcan: Sí/No")
      corners/yellow_cards: "Over 9.5" / "Under 9.5" for match totals

    Integer totals and final scores must be explicitly supplied. Pushes are
    withheld because this contract records binary outcomes only.
    """
    market = str(market_type or "").strip().casefold()
    pick = str(selection or "").strip()
    normalized = pick.casefold()

    if market in {"goals", "draw", "btts"}:
        home = _non_negative_int(final_home_score)
        away = _non_negative_int(final_away_score)
        if home is None or away is None:
            return {"resolved": False, "reason": "missing_or_invalid_final_score"}

        if market == "btts":
            if normalized in {"yes", "sí", "si", "ambos equipos marcan: sí", "ambos equipos marcan: si"}:
                result = int(home > 0 and away > 0)
            elif normalized in {"no", "ambos equipos marcan: no"}:
                result = int(not (home > 0 and away > 0))
            else:
                return {"resolved": False, "reason": "unsupported_btts_selection"}
            return {"resolved": True, "outcome": result, "reason": "final_score"}

        if market == "draw":
            if normalized not in {"draw", "empate final", "empate"}:
                return {"resolved": False, "reason": "unsupported_draw_selection"}
            return {"resolved": True, "outcome": int(home == away), "reason": "final_score"}

        if normalized in {"home", "local", "gana local"}:
            return {"resolved": True, "outcome": int(home > away), "reason": "final_score"}
        if normalized in {"draw", "empate", "empate final"}:
            return {"resolved": True, "outcome": int(home == away), "reason": "final_score"}
        if normalized in {"away", "visitante", "gana visitante"}:
            return {"resolved": True, "outcome": int(away > home), "reason": "final_score"}

        total = home + away
        for direction in ("over", "under"):
            line = _line_from_selection(pick, direction)
            if line is not None:
                # Equality is not a binary win/loss; never force a push.
                if total == line:
                    return {"resolved": False, "reason": "push_requires_non_binary_settlement"}
                won = total > line if direction == "over" else total < line
                return {"resolved": True, "outcome": int(won), "reason": "final_score"}
        return {"resolved": False, "reason": "unsupported_goal_selection"}

    if market in {"corners", "yellow_cards"}:
        raw_total = final_total_corners if market == "corners" else final_total_yellow_cards
        total = _non_negative_int(raw_total)
        if total is None:
            return {"resolved": False, "reason": "missing_or_invalid_final_total"}
        for direction in ("over", "under"):
            line = _line_from_selection(pick, direction)
            if line is not None:
                if total == line:
                    return {"resolved": False, "reason": "push_requires_non_binary_settlement"}
                won = total > line if direction == "over" else total < line
                return {"resolved": True, "outcome": int(won), "reason": "final_total"}
        return {"resolved": False, "reason": "unsupported_total_selection"}

    return {"resolved": False, "reason": "unsupported_market"}
