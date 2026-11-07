"""Explicit execution gates for experimental Football Lab model families.

This module decides whether a baseline may be evaluated with the supplied data.
It does not execute models, fetch data, emit picks, or claim calibration.
"""
from __future__ import annotations

from typing import Any


def _valid_nonnegative(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        number = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError, OverflowError):
        return False
    return number >= 0 and number < float("inf")


def _gate(ready: bool, reason: str | None, *, calibrated: bool = False) -> dict[str, Any]:
    return {
        "eligible": bool(ready),
        "status": "eligible_experimental" if ready else "abstain",
        "reason": None if ready else (reason or "No se cumplen los requisitos mínimos de datos."),
        "calibrated": calibrated,
        "may_emit_betting_signal": False,
    }


def build_model_eligibility(
    features: dict[str, Any],
    coverage_report: dict[str, Any],
    *,
    live_corner_history_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return independent go/abstain gates for each current experimental model.

    Coverage thresholds are inherited from build_data_coverage_report. A model
    may be eligible for an experimental calculation while still being prohibited
    from emitting a betting signal until chronological validation/calibration.
    """
    features = features if isinstance(features, dict) else {}
    coverage_report = coverage_report if isinstance(coverage_report, dict) else {}
    ready = coverage_report.get("ready") or {}
    goals = features.get("goals") or {}
    corners = features.get("corners") or {}
    live = features.get("live") or {}
    cards = features.get("cards") or {}

    goal_rates = (
        goals.get("home_goals_for_avg"), goals.get("home_goals_against_avg"),
        goals.get("away_goals_for_avg"), goals.get("away_goals_against_avg"),
    )
    corner_rates = (
        corners.get("home_corners_for_avg"), corners.get("home_corners_against_avg"),
        corners.get("away_corners_for_avg"), corners.get("away_corners_against_avg"),
    )

    goal_ok = bool(ready.get("prematch_goals")) and all(_valid_nonnegative(v) for v in goal_rates)
    corner_ok = bool(ready.get("prematch_corners")) and all(_valid_nonnegative(v) for v in corner_rates)
    card_ok = bool(ready.get("prematch_yellow_cards")) and (
        isinstance(coverage_report.get("markets"), dict)
        and isinstance(coverage_report["markets"].get("prematch_yellow_cards"), dict)
    )
    live_rows_present = isinstance(live_corner_history_rows, list) and bool(live_corner_history_rows)
    live_ok = (
        bool(ready.get("live_remaining_corners"))
        and live_rows_present
        and _valid_nonnegative(live.get("minute"))
        and _valid_nonnegative(corners.get("live_home_corners"))
        and _valid_nonnegative(corners.get("live_away_corners"))
        and bool(features.get("league_id"))
        and bool((features.get("teams") or {}).get("home"))
        and bool((features.get("teams") or {}).get("away"))
    )

    reasons = {
        "prematch_goals": "Falta muestra suficiente por localía o alguno de los cuatro promedios de goles.",
        "prematch_corners": "Falta muestra suficiente por localía o alguno de los cuatro promedios de córners.",
        "prematch_yellow_cards": "Falta muestra histórica válida por liga y sede para uno o ambos equipos.",
        "live_remaining_corners": "Falta histórico minuto-a-minuto suficiente, minuto o córners actuales de ambos equipos.",
    }
    return {
        "schema_version": "1.0",
        "fixture_id": features.get("fixture_id"),
        "models": {
            "prematch_goals": _gate(goal_ok, reasons["prematch_goals"]),
            "prematch_corners": _gate(corner_ok, reasons["prematch_corners"]),
            "prematch_yellow_cards": _gate(card_ok, reasons["prematch_yellow_cards"]),
            "live_remaining_corners": _gate(live_ok, reasons["live_remaining_corners"]),
        },
        "referee_adjustment": _gate(
            bool(ready.get("referee_adjustment")),
            "No existe todavía muestra arbitral suficiente junto con un promedio representativo e independiente de la liga.",
        ),
        "global_policy": {
            "experimental_calculations_only": True,
            "betting_signals_enabled": False,
            "reason": "Los modelos siguen sin calibración y validación cronológica suficiente para emitir recomendaciones.",
        },
    }
