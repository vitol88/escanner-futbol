"""Helpers to normalize API-Football in-play odds without inventing prices."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.casefold()).strip()


def extract_live_odds(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return live odds indexed by fixture id, preserving bookmaker/market/value."""
    indexed: dict[str, list[dict[str, Any]]] = {}
    for item in payload.get("response") or []:
        fixture_id = (item.get("fixture") or {}).get("id")
        if fixture_id is None:
            continue
        rows = indexed.setdefault(str(fixture_id), [])
        for bookmaker in item.get("bookmakers") or []:
            bookmaker_name = bookmaker.get("name") or "Casa no identificada"
            for bet in bookmaker.get("bets") or []:
                market_name = bet.get("name") or "Mercado"
                for value in bet.get("values") or []:
                    try:
                        odd = float(str(value.get("odd", "")).replace(",", "."))
                    except (TypeError, ValueError):
                        continue
                    if odd <= 1.0 or value.get("suspended") is True:
                        continue
                    rows.append({
                        "bookmaker": bookmaker_name,
                        "market": market_name,
                        "value": str(value.get("value") or ""),
                        "odd": odd,
                        "handicap": value.get("handicap"),
                        "main": value.get("main"),
                    })
    return indexed


def classify_market(row: dict[str, Any]) -> str | None:
    """Conservative market classifier; unknown labels are deliberately omitted."""
    market = _norm(row.get("market"))
    value = _norm(row.get("value"))
    if "both teams score" in market or "ambos equipos marcan" in market or market == "btts":
        if value in {"yes", "si"}:
            return "Ambos equipos marcan: Sí"
        if value == "no":
            return "Ambos equipos marcan: No"
    if "match winner" in market or market in {"1x2", "fulltime result", "full time result"} or "resultado final" in market:
        if value in {"draw", "empate", "x"}:
            return "Empate final"
        if value in {"home", "1", "local"}:
            return "Gana local"
        if value in {"away", "2", "visitante"}:
            return "Gana visitante"
    if "corner" in market or "corners" in market or "córner" in market or "corners" in value or "córners" in value:
        if any(token in value for token in ("over", "under", "mas de", "menos de")):
            handicap = row.get("handicap")
            side = "Más de" if any(token in value for token in ("over", "mas de")) else "Menos de"
            line = str(handicap).strip() if handicap not in (None, "") else value
            return f"{side} {line} córners"
    if "over/under" in market or "total goals" in market or "total de goles" in market:
        if any(token in value for token in ("over", "under", "mas de", "menos de")):
            handicap = row.get("handicap")
            side = "Más de" if any(token in value for token in ("over", "mas de")) else "Menos de"
            line = str(handicap).strip() if handicap not in (None, "") else value
            return f"{side} {line} goles"
    return None


def score_pattern_context(score_home: int | None, score_away: int | None) -> str:
    """Descriptive score-pattern context, never a standalone probability."""
    if not isinstance(score_home, int) or not isinstance(score_away, int):
        return "Patrón de marcador no disponible"
    if score_home == score_away:
        return "Marcador empatado: evaluar si el empate se sostiene"
    if abs(score_home - score_away) == 1:
        return "Diferencia de un gol: revisar empate y ambos marcan según el contexto"
    return "Diferencia amplia: no inferir empate solo por el patrón numérico"


def numerology_context(
    score_home: int | None,
    score_away: int | None,
    home_corners: int | float | None = None,
    away_corners: int | float | None = None,
    home_yellows: int | float | None = None,
    away_yellows: int | float | None = None,
) -> list[str]:
    """Compare score digits with team corner/card counts as risk-only context.

    A match is reported when both team counts are close to the corresponding
    score (within one), e.g. score 4-2 and corners 4-3. This is descriptive
    pattern matching, not a predictive model and must never create a tip alone.
    """
    if not isinstance(score_home, int) or not isinstance(score_away, int):
        return []
    patterns: list[str] = []
    for label, home_count, away_count in (
        ("córners", home_corners, away_corners),
        ("tarjetas amarillas", home_yellows, away_yellows),
    ):
        if not isinstance(home_count, (int, float)) or not isinstance(away_count, (int, float)):
            continue
        if abs(float(home_count) - score_home) <= 1 and abs(float(away_count) - score_away) <= 1:
            patterns.append(
                f"patrón numérico en {label}: marcador {score_home}–{score_away}, "
                f"registro {home_count:g}–{away_count:g}"
            )
    return patterns


def best_live_odds_by_market(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the highest currently listed price per recognized market."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = classify_market(row)
        odd = row.get("odd")
        if not label or not isinstance(odd, (int, float)) or odd <= 1:
            continue
        current = best.get(label)
        if current is None or float(odd) > float(current.get("odd", 0)):
            best[label] = {**row, "market_label": label}
    return list(best.values())


def match_goal_tip_to_live_odds(
    tip_label: str,
    probability: float,
    rows: list[dict[str, Any]],
    *,
    minimum_edge: float = 0.02,
) -> dict[str, Any] | None:
    """Match supported goal-model tips to a real quote and enforce alert rules.

    Only exact supported markets are matched. Unknown/team-specific propositions
    are deliberately withheld rather than paired with a merely similar price.
    """
    tip = _norm(tip_label)
    expected_market: str | None = None
    if tip == "empate final":
        expected_market = "Empate final"
    elif tip.startswith("ambos equipos marcan"):
        expected_market = "Ambos equipos marcan: Sí"
    else:
        over_match = re.search(r"total final:\\s*(\\d+)\\s*goles o mas", tip)
        under_match = re.search(r"menos de\\s*(\\d+(?:[.,]\\d+)?)\\s*goles totales", tip)
        if over_match:
            # N goals or more corresponds to the Asian half-goal line N-0.5.
            expected_market = f"Más de {int(over_match.group(1)) - 0.5:g} goles"
        elif under_match:
            expected_market = f"Menos de {float(under_match.group(1).replace(',', '.')):g} goles"
    if not expected_market or not isinstance(probability, (int, float)):
        return None

    best = None
    for row in best_live_odds_by_market(rows):
        if row.get("market_label") != expected_market:
            continue
        odd = row.get("odd")
        if not isinstance(odd, (int, float)) or not (1.35 <= float(odd) <= 1.60 or float(odd) >= 1.70):
            continue
        implied = 1.0 / float(odd)
        edge = float(probability) - implied
        if edge < minimum_edge:
            continue
        candidate = {
            **row,
            "model_probability": float(probability),
            "implied_probability": implied,
            "estimated_edge": edge,
        }
        if best is None or float(candidate["odd"]) > float(best["odd"]):
            best = candidate
    return best
