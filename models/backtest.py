"""Small, auditable metrics for evaluating recorded binary predictions."""
from __future__ import annotations

import math
from typing import Any


def evaluate_binary_predictions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate rows with probability (0..1) and verified binary outcome (0/1).

    Unverified, malformed, and non-finite records are excluded rather than guessed.
    """
    scored: list[tuple[float, int]] = []
    excluded = 0
    for row in rows:
        try:
            probability = float(row.get("estimated_probability_exploratory"))
            outcome_value = row.get("outcome")
            verified = str(row.get("outcome_verified", "")).strip().casefold()
            if verified not in {"1", "true", "yes", "si", "sí", "verified", "verificado"}:
                excluded += 1
                continue
            outcome_text = str(outcome_value).strip().casefold()
            if outcome_text in {"1", "true", "yes", "si", "sí"}:
                outcome = 1
            elif outcome_text in {"0", "false", "no"}:
                outcome = 0
            else:
                excluded += 1
                continue
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                excluded += 1
                continue
            scored.append((probability, outcome))
        except (TypeError, ValueError):
            excluded += 1

    if not scored:
        return {"sample_size": 0, "excluded": excluded, "hit_rate": None, "brier_score": None, "mean_probability": None, "observed_rate": None}

    n = len(scored)
    return {
        "sample_size": n,
        "excluded": excluded,
        "hit_rate": sum(outcome for _, outcome in scored) / n,
        "brier_score": sum((probability - outcome) ** 2 for probability, outcome in scored) / n,
        "mean_probability": sum(probability for probability, _ in scored) / n,
        "observed_rate": sum(outcome for _, outcome in scored) / n,
    }
