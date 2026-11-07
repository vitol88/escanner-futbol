"""Live remaining-corner estimates using the existing empirical history model.

This adapter reuses models.corner_history and does not invent a pressure multiplier.
"""
from __future__ import annotations

from typing import Any, Callable


MODEL_VERSION = "0.1.0"


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _weighted(values: list[tuple[float, int]]) -> float | None:
    usable = [(value, weight) for value, weight in values if weight > 0]
    denominator = sum(weight for _, weight in usable)
    if not denominator:
        return None
    return sum(value * weight for value, weight in usable) / denominator


def estimate_live_remaining_corners(
    features: dict[str, Any],
    history_rows: list[dict[str, Any]],
    *,
    minimum_matches: int = 8,
    estimator: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Estimate additional corners using minute-matched historical rows."""
    if estimator is None:
        from models.corner_history import estimate_remaining_corners as estimator

    unavailable = {
        "available": False,
        "model_version": MODEL_VERSION,
        "model_label": "Estimador empírico live de córners restantes",
        "reason": None,
    }
    if not isinstance(features, dict):
        unavailable["reason"] = "No se recibieron variables válidas."
        return unavailable

    live = features.get("live") or {}
    match_minute = _nonnegative_int(live.get("minute"))
    league_id = features.get("league_id")
    teams = features.get("teams") or {}
    corners = features.get("corners") or {}
    home_team, away_team = teams.get("home"), teams.get("away")
    home_corners = _nonnegative_int(corners.get("live_home_corners"))
    away_corners = _nonnegative_int(corners.get("live_away_corners"))
    if match_minute is None or not league_id or not home_team or not away_team:
        unavailable["reason"] = "Faltan minuto, competición o nombres de equipos."
        return unavailable
    if home_corners is None or away_corners is None:
        unavailable["reason"] = "Faltan los córners actuales de uno o ambos equipos."
        return unavailable
    if match_minute >= 120:
        unavailable["reason"] = "El minuto indicado está fuera del rango admitido."
        return unavailable
    if not isinstance(history_rows, list):
        unavailable["reason"] = "El histórico live no tiene el formato esperado."
        return unavailable

    minimum = max(1, _nonnegative_int(minimum_matches) or 8)
    # The persisted minute-level history uses the competition name when available.
    league_key = features.get("league_name") or str(league_id)
    common = {"league": str(league_key), "minute": match_minute, "minimum_matches": minimum}
    home_result = estimator(
        history_rows, team=home_team, venue="home",
        corners_for=home_corners, corners_against=away_corners, **common,
    )
    away_result = estimator(
        history_rows, team=away_team, venue="away",
        corners_for=away_corners, corners_against=home_corners, **common,
    )
    home_result = home_result if isinstance(home_result, dict) else {"available": False}
    away_result = away_result if isinstance(away_result, dict) else {"available": False}
    valid = [("home", home_result), ("away", away_result)]
    valid = [(side, result) for side, result in valid if result.get("available")]
    if not valid:
        unavailable["reason"] = "No hay muestra histórica suficiente para este minuto y estado de córners."
        unavailable["perspectives"] = {"home": home_result, "away": away_result}
        return unavailable

    def blend(field: str) -> float | None:
        pairs = []
        for _, result in valid:
            value = _number(result.get(field))
            sample = _nonnegative_int(result.get("sample_size"))
            if value is not None and sample:
                pairs.append((value, sample))
        return _weighted(pairs)

    total_mean = blend("mean_corners_after")
    if total_mean is None:
        unavailable["reason"] = "El histórico no contiene una media válida de córners restantes."
        return unavailable

    current_total = home_corners + away_corners
    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "model_label": "Estimador empírico live de córners restantes",
        "reason": None,
        "minute": match_minute,
        "current_corners": {"home": home_corners, "away": away_corners, "total": current_total},
        "expected_remaining_corners": total_mean,
        "projected_final_total_corners": current_total + total_mean,
        "probability_remaining_at_least_1": blend("prob_at_least_1_corner"),
        "probability_remaining_at_least_2": blend("prob_at_least_2_corners"),
        "team_probability_gets_corner": {
            "home": home_result.get("prob_team_gets_corner") if home_result.get("available") else None,
            "away": away_result.get("prob_team_gets_corner") if away_result.get("available") else None,
        },
        "sample": {
            "home_perspective": home_result.get("sample_size", 0),
            "away_perspective": away_result.get("sample_size", 0),
            "perspectives_used": [side for side, _ in valid],
        },
        "live_context": {
            "shots_total": {"home": _number(live.get("home_shots_total")), "away": _number(live.get("away_shots_total"))},
            "shots_on_target": {"home": _number(live.get("home_shots_on_target")), "away": _number(live.get("away_shots_on_target"))},
            "possession": {"home": _number(live.get("home_possession")), "away": _number(live.get("away_possession"))},
            "note": "Estadísticas descriptivas; todavía no modifican las probabilidades empíricas.",
        },
        "warnings": [
            "Frecuencias empíricas por minuto y estado; no son probabilidades calibradas.",
            "Las perspectivas del local y visitante describen el mismo total; se combinan ponderadas por muestra, no se suman.",
            "La presión ofensiva se muestra como contexto y no altera el cálculo hasta validación histórica.",
            "No incorpora cuotas, valor esperado ni recomendaciones de apuesta.",
        ],
    }
