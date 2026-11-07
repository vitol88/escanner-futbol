"""Calibration metrics for verified binary Football Lab forecasts.

This module is deliberately pure: it does not fetch data, write files, or make picks.
"""
from __future__ import annotations

import math
from typing import Any


def _verified(value: Any) -> bool:
    return str(value).strip().casefold() in {
        "1", "true", "yes", "si", "sí", "verified", "verificado"
    }


def _outcome(value: Any) -> int | None:
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "si", "sí"}:
        return 1
    if text in {"0", "false", "no"}:
        return 0
    return None


def evaluate_binary_forecasts(
    rows: list[dict[str, Any]],
    *,
    probability_key: str = "estimated_probability_exploratory",
    outcome_key: str = "outcome",
    verified_key: str = "outcome_verified",
    bins: int = 10,
    minimum_sample: int = 30,
) -> dict[str, Any]:
    """Score only explicitly verified binary outcomes and report calibration.

    Reliability bins are equal-width intervals over [0, 1]. The upper endpoint
    is inclusive in the final bin. No accuracy/ROI claim is inferred.
    """
    if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
        raise ValueError("bins debe ser un entero mayor que cero")
    if isinstance(minimum_sample, bool) or not isinstance(minimum_sample, int) or minimum_sample < 1:
        raise ValueError("minimum_sample debe ser un entero mayor que cero")

    scored: list[tuple[float, int]] = []
    excluded = 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not _verified(row.get(verified_key, "")):
            excluded += 1
            continue
        outcome = _outcome(row.get(outcome_key))
        try:
            probability = float(row.get(probability_key))
        except (TypeError, ValueError, OverflowError):
            probability = math.nan
        if outcome is None or not math.isfinite(probability) or not 0 <= probability <= 1:
            excluded += 1
            continue
        scored.append((probability, outcome))

    n = len(scored)
    if not n:
        return {
            "sample_size": 0, "excluded": excluded, "brier_score": None,
            "log_loss": None, "mean_probability": None, "observed_rate": None,
            "calibration_gap": None, "reliability": [],
            "minimum_sample": minimum_sample, "minimum_sample_reached": False,
        }

    epsilon = 1e-15
    brier = sum((p - y) ** 2 for p, y in scored) / n
    log_loss = -sum(
        y * math.log(max(epsilon, min(1 - epsilon, p)))
        + (1 - y) * math.log(max(epsilon, min(1 - epsilon, 1 - p)))
        for p, y in scored
    ) / n
    mean_probability = sum(p for p, _ in scored) / n
    observed_rate = sum(y for _, y in scored) / n

    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for probability, outcome in scored:
        index = min(bins - 1, int(probability * bins))
        buckets[index].append((probability, outcome))

    reliability = []
    weighted_gap = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        count = len(bucket)
        predicted = sum(p for p, _ in bucket) / count
        observed = sum(y for _, y in bucket) / count
        gap = abs(predicted - observed)
        weighted_gap += count / n * gap
        reliability.append({
            "lower_bound": index / bins,
            "upper_bound": (index + 1) / bins,
            "sample_size": count,
            "mean_probability": round(predicted, 6),
            "observed_rate": round(observed, 6),
            "absolute_gap": round(gap, 6),
        })

    return {
        "sample_size": n,
        "excluded": excluded,
        "brier_score": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "mean_probability": round(mean_probability, 6),
        "observed_rate": round(observed_rate, 6),
        "calibration_gap": round(weighted_gap, 6),
        "reliability": reliability,
        "minimum_sample": minimum_sample,
        "minimum_sample_reached": n >= minimum_sample,
        "warnings": [
            "Métricas descriptivas: no garantizan rendimiento futuro ni rentabilidad.",
            "Use validación cronológica y separe por liga, mercado y línea antes de comparar modelos.",
        ],
    }
