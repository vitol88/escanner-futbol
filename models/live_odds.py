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
