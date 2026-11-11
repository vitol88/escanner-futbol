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


def _line_from_selection(
    selection: str,
    direction: str,
    allowed_suffixes: tuple[str, ...] = ("",),
) -> float | None:
    suffix_pattern = "|".join(re.escape(suffix) for suffix in allowed_suffixes)
    match = re.fullmatch(
        rf"\s*(?:{direction}|{'Más de' if direction == 'over' else 'Menos de'})"
        rf"\s+(\d+(?:[.,]\d+)?)\s*(?:{suffix_pattern})\s*",
        selection,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
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
    home_team_name: str | None = None,
    away_team_name: str | None = None,
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
            if normalized in {"no", "ambos equipos marcan: no"}:
                result = int(not (home > 0 and away > 0))
            elif normalized.startswith("ambos equipos marcan (") or normalized in {"yes", "sí", "si", "ambos equipos marcan: sí", "ambos equipos marcan: si"}:
                result = int(home > 0 and away > 0)
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

        # Formato de selección por umbral absoluto: "Total final: 3 goles o más".
        total_threshold = re.match(r"^total final:\s*(\d+)\s+goles?\s+o\s+más", pick, flags=re.IGNORECASE)
        if total_threshold:
            return {
                "resolved": True,
                "outcome": int(total >= int(total_threshold.group(1))),
                "reason": "final_score",
            }

        # Formato real del escáner: "<equipo> marcará al menos 1 gol
        # (más de 0.5 goles del local/visitante)". Se liquida con el marcador
        # del lado indicado, nunca con el total de goles del partido.
        team_goal_match = re.search(
            r"marcará\s+al\s+menos\s+1\s+gol\s*"
            r"\(\s*más\s+de\s+0\.5\s+goles\s+del\s+(local|visitante)\s*\)\s*$",
            pick,
            flags=re.IGNORECASE,
        )
        if team_goal_match:
            side_score = home if team_goal_match.group(1).casefold() == "local" else away
            return {
                "resolved": True,
                "outcome": int(side_score >= 1),
                "reason": "final_team_score",
            }

        named_team_match = re.match(r"^(.+?):\s*terminará\s+con\s+(\d+)\s+goles?\s+o\s+más$", pick, flags=re.IGNORECASE)
        if named_team_match:
            team_name = named_team_match.group(1).strip().casefold()
            if home_team_name and team_name == str(home_team_name).strip().casefold():
                side_score = home
            elif away_team_name and team_name == str(away_team_name).strip().casefold():
                side_score = away
            else:
                return {"resolved": False, "reason": "team_side_not_verified"}
            return {
                "resolved": True,
                "outcome": int(side_score >= int(named_team_match.group(2))),
                "reason": "final_team_score",
            }

        for direction in ("over", "under"):
            line = _line_from_selection(pick, direction, ("", " goles"))
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
            suffixes = ("", " córners") if market == "corners" else ("", " tarjetas amarillas", " tarjetas")
            line = _line_from_selection(pick, direction, suffixes)
            if line is not None:
                if total == line:
                    return {"resolved": False, "reason": "push_requires_non_binary_settlement"}
                won = total > line if direction == "over" else total < line
                return {"resolved": True, "outcome": int(won), "reason": "final_total"}
        return {"resolved": False, "reason": "unsupported_total_selection"}

    return {"resolved": False, "reason": "unsupported_market"}


def settle_prediction_rows(
    prediction_rows: list[dict[str, Any]],
    final_outcomes_by_fixture: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Join immutable predictions to verified fixture outcomes without mutating either.

    Unsupported selections, missing final stats, and Asian-line pushes remain
    pending. Each output row is an evaluation projection, not a ledger update.
    """
    settled: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for row in prediction_rows if isinstance(prediction_rows, list) else []:
        if not isinstance(row, dict):
            continue
        fixture_id = str(row.get("fixture_id") or "").strip()
        final = final_outcomes_by_fixture.get(fixture_id) if fixture_id else None
        if not isinstance(final, dict):
            pending.append({**row, "settlement_status": "pending_final_result"})
            continue
        market_type = str(row.get("market_type") or "").strip()
        if not market_type:
            market_type = str(row.get("market") or "").strip().casefold()
        selection = str(row.get("selection") or "").strip()
        result = resolve_binary_outcome(
            market_type=market_type,
            selection=selection,
            final_home_score=final.get("final_home_score"),
            final_away_score=final.get("final_away_score"),
            final_total_corners=final.get("final_total_corners"),
            final_total_yellow_cards=final.get("final_total_yellow_cards"),
            home_team_name=row.get("home"),
            away_team_name=row.get("away"),
        )
        enriched = {
            **row,
            "settlement_status": "settled" if result.get("resolved") else "pending_review",
            "settlement_reason": result.get("reason"),
            "outcome": result.get("outcome") if result.get("resolved") else None,
            "outcome_verified": bool(result.get("resolved")),
            "outcome_source": final.get("source") or "verified_fixture_result",
            "outcome_verified_at": final.get("verified_at"),
        }
        (settled if result.get("resolved") else pending).append(enriched)
    return {
        "settled": settled,
        "pending": pending,
        "settled_count": len(settled),
        "pending_count": len(pending),
        "hit_count": sum(row["outcome"] == 1 for row in settled),
        "miss_count": sum(row["outcome"] == 0 for row in settled),
    }
