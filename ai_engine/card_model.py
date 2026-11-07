"""Experimental pre-match yellow-card baseline with venue and referee context."""
from __future__ import annotations
import math
from typing import Any

def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None

def _same(a: Any, b: Any) -> bool:
    return a is not None and b is not None and str(a).strip().casefold() == str(b).strip().casefold()

def _poisson_over(lam: float, line: float) -> float:
    threshold = math.floor(line) + 1
    probability_below = 0.0
    term = math.exp(-lam)
    for k in range(threshold):
        if k:
            term *= lam / k
        probability_below += term
    return min(1.0, max(0.0, 1.0 - probability_below))

def estimate_prematch_yellow_cards(features: dict[str, Any], history_rows: list[dict[str, Any]], *,
        minimum_team_matches: int = 5, minimum_referee_matches: int = 8,
        referee_prior_strength: float = 8.0, max_referee_factor: float = 1.25) -> dict[str, Any]:
    """Estimate cards from venue-specific team rates and a shrunken referee factor.

    Historical rows must be completed matches before kickoff and contain league_id,
    home_team_id, away_team_id, home_yellow_cards and away_yellow_cards.
    """
    features = features if isinstance(features, dict) else {}
    rows = history_rows if isinstance(history_rows, list) else []
    league_id = features.get("league_id")
    teams = features.get("teams") or {}
    home_id, away_id = features.get("home_team_id"), features.get("away_team_id")
    home_name, away_name = teams.get("home"), teams.get("away")
    referee = features.get("referee")
    if league_id is None or not (home_id is not None or home_name) or not (away_id is not None or away_name):
        return {"available": False, "reason": "Faltan liga o identificación de los equipos."}
    if isinstance(minimum_team_matches, bool) or minimum_team_matches < 1:
        return {"available": False, "reason": "minimum_team_matches debe ser mayor que cero."}

    league_rows = []
    for row in rows:
        if not isinstance(row, dict) or not _same(row.get("league_id"), league_id):
            continue
        hc, ac = _number(row.get("home_yellow_cards")), _number(row.get("away_yellow_cards"))
        if hc is not None and ac is not None:
            league_rows.append((row, hc, ac))

    home_for, home_against, away_for, away_against, referee_totals = [], [], [], [], []
    for row, hc, ac in league_rows:
        row_home_id, row_away_id = row.get("home_team_id"), row.get("away_team_id")
        row_home_name, row_away_name = row.get("home_team"), row.get("away_team")
        if ((home_id is not None and _same(row_home_id, home_id)) or
                (home_id is None and _same(row_home_name, home_name))):
            home_for.append(hc); home_against.append(ac)
        if ((away_id is not None and _same(row_away_id, away_id)) or
                (away_id is None and _same(row_away_name, away_name))):
            away_for.append(ac); away_against.append(hc)
        if referee and _same(row.get("referee"), referee):
            referee_totals.append(hc + ac)

    if len(home_for) < minimum_team_matches or len(away_for) < minimum_team_matches:
        return {"available": False,
                "reason": "Muestra insuficiente de tarjetas por localía para uno o ambos equipos.",
                "sample": {"home_team": len(home_for), "away_team": len(away_for)},
                "minimum_team_matches": minimum_team_matches}

    home_base = (sum(home_for) / len(home_for) + sum(away_against) / len(away_against)) / 2
    away_base = (sum(away_for) / len(away_for) + sum(home_against) / len(home_against)) / 2
    league_totals = [hc + ac for _, hc, ac in league_rows]
    league_average = _number(features.get("league_average_total_cards"))
    referee_average = sum(referee_totals) / len(referee_totals) if referee_totals else None
    factor, referee_used = 1.0, False
    if league_average and referee_average is not None and len(referee_totals) >= minimum_referee_matches:
        shrinkage = len(referee_totals) / (len(referee_totals) + max(0.0, referee_prior_strength))
        upper = max(1.0, float(max_referee_factor))
        raw_factor = referee_average / league_average
        factor = min(upper, max(1.0 / upper, 1.0 + (raw_factor - 1.0) * shrinkage))
        referee_used = True

    expected_home, expected_away = home_base * factor, away_base * factor
    expected_total = expected_home + expected_away
    if not math.isfinite(expected_total):
        return {"available": False, "reason": "No fue posible calcular una proyección válida."}
    lines = {line: round(_poisson_over(expected_total, line), 6) for line in (2.5, 3.5, 4.5, 5.5, 6.5)}
    warnings = [
        "Modelo experimental Poisson, no calibrado; las tarjetas pueden presentar sobredispersión.",
        "El ajuste arbitral se reduce hacia el promedio de liga y exige una muestra mínima y un promedio de liga representativo.",
        "No incorpora cuotas, valor esperado ni recomendaciones de apuesta.",
    ]
    if not referee_used:
        warnings.append("Sin muestra suficiente del árbitro o promedio de liga representativo: se conserva el factor neutral.")
    return {
        "available": True, "model": "experimental_poisson_yellow_cards", "calibrated": False,
        "expected_yellow_cards": {"home": round(expected_home, 3), "away": round(expected_away, 3), "total": round(expected_total, 3)},
        "probability_over": lines,
        "referee": {"name": referee, "matches": len(referee_totals),
                    "average_total_cards": round(referee_average, 3) if referee_average is not None else None,
                    "league_average_total_cards": round(league_average, 3) if league_average is not None else None,
                    "factor": round(factor, 4), "used": referee_used},
        "sample": {"home_team_venue": len(home_for), "away_team_venue": len(away_for), "league_matches": len(league_rows)},
        "warnings": warnings,
    }
