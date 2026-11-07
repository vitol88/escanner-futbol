"""Orchestrate experimental Football Lab models behind explicit data gates.

This pipeline is pure orchestration: it makes no API calls, persists nothing,
and never emits betting recommendations.
"""
from __future__ import annotations

from typing import Any

from ai_engine.card_model import estimate_prematch_yellow_cards
from ai_engine.corner_model import estimate_prematch_corners
from ai_engine.coverage import build_data_coverage_report
from ai_engine.eligibility import build_model_eligibility
from ai_engine.goal_model import estimate_prematch_goals
from ai_engine.live_corner_model import estimate_live_remaining_corners


def analyze_experimental_models(
    features: dict[str, Any],
    history: dict[str, Any] | None = None,
    *,
    live_corner_history_rows: list[dict[str, Any]] | None = None,
    minimum_team_sample: int = 5,
    minimum_referee_sample: int = 8,
    minimum_live_corner_sample: int = 8,
) -> dict[str, Any]:
    """Run only eligible experimental calculations and report all abstentions."""
    features = features if isinstance(features, dict) else {}
    history = history if isinstance(history, dict) else {}
    live_rows = live_corner_history_rows if isinstance(live_corner_history_rows, list) else []

    coverage = build_data_coverage_report(
        features,
        history,
        live_corner_history_rows=live_rows,
        minimum_team_sample=minimum_team_sample,
        minimum_referee_sample=minimum_referee_sample,
        minimum_live_corner_sample=minimum_live_corner_sample,
    )
    eligibility = build_model_eligibility(
        features, coverage, live_corner_history_rows=live_rows
    )
    gates = eligibility["models"]
    card_rows = history.get("card_history_rows")
    if not isinstance(card_rows, list):
        card_rows = []

    models: dict[str, Any] = {}
    runners = {
        "prematch_goals": lambda: estimate_prematch_goals(
            features, minimum_sample=minimum_team_sample
        ),
        "prematch_corners": lambda: estimate_prematch_corners(
            features, minimum_sample=minimum_team_sample
        ),
        "prematch_yellow_cards": lambda: estimate_prematch_yellow_cards(
            features, card_rows, minimum_team_matches=minimum_team_sample,
            minimum_referee_matches=minimum_referee_sample,
        ),
        "live_remaining_corners": lambda: estimate_live_remaining_corners(
            features, live_rows, minimum_matches=minimum_live_corner_sample
        ),
    }
    for name, runner in runners.items():
        if gates[name]["eligible"]:
            result = runner()
            # Defensive consistency check: an eligible gate does not guarantee
            # a valid numerical result; preserve the model's own abstention.
            if not isinstance(result, dict) or not result.get("available"):
                models[name] = {
                    "available": False,
                    "status": "abstain",
                    "reason": (result or {}).get("reason")
                    if isinstance(result, dict)
                    else "El modelo no devolvió un resultado válido.",
                }
            else:
                models[name] = {
                    **result,
                    "status": "experimental_only",
                    "may_emit_betting_signal": False,
                }
        else:
            models[name] = {
                "available": False,
                "status": "abstain",
                "reason": gates[name]["reason"],
                "may_emit_betting_signal": False,
            }

    return {
        "schema_version": "1.0",
        "fixture_id": features.get("fixture_id"),
        "coverage": coverage,
        "eligibility": eligibility,
        "models": models,
        "policy": {
            "experimental_only": True,
            "betting_signals_enabled": False,
            "recommendations_enabled": False,
            "reason": eligibility["global_policy"]["reason"],
        },
    }
