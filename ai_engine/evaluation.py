"""Calibration metrics for verified binary Football Lab forecasts.

This module is deliberately pure: it does not fetch data, write files, or make picks.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
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




def evaluate_chronological_holdout(
    rows: list[dict[str, Any]],
    *,
    timestamp_key: str = "recorded_at",
    fixture_key: str = "fixture_id",
    train_fraction: float = 0.8,
    minimum_train_fixtures: int = 5,
    minimum_test_fixtures: int = 5,
    probability_key: str = "estimated_probability_exploratory",
    outcome_key: str = "outcome",
    verified_key: str = "outcome_verified",
) -> dict[str, Any]:
    """Evaluate later unseen fixtures using a deterministic chronological holdout.

    All snapshots for one fixture remain in one partition, avoiding fixture leakage.
    Only verified outcomes in the later test partition are scored.
    """
    if isinstance(train_fraction, bool) or not isinstance(train_fraction, (int, float)) or not 0 < train_fraction < 1:
        raise ValueError("train_fraction debe estar entre 0 y 1")
    for name, value in (("minimum_train_fixtures", minimum_train_fixtures), ("minimum_test_fixtures", minimum_test_fixtures)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} debe ser un entero mayor que cero")

    fixtures: dict[str, dict[str, Any]] = {}
    excluded_temporal = 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            excluded_temporal += 1
            continue
        fixture_id = str(row.get(fixture_key, "") or "").strip()
        raw_timestamp = str(row.get(timestamp_key, "") or "").strip()
        if not fixture_id or not raw_timestamp:
            excluded_temporal += 1
            continue
        try:
            parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            # A naive legacy timestamp has no defensible absolute ordering.
            # Exclude it rather than silently assuming UTC in chronological tests.
            if parsed.tzinfo is None:
                excluded_temporal += 1
                continue
            epoch = parsed.astimezone(timezone.utc).timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            excluded_temporal += 1
            continue
        entry = fixtures.setdefault(fixture_id, {"first_timestamp": epoch, "rows": []})
        entry["first_timestamp"] = min(entry["first_timestamp"], epoch)
        entry["rows"].append(row)

    ordered = sorted(fixtures.items(), key=lambda item: (item[1]["first_timestamp"], item[0]))
    fixture_count = len(ordered)
    split_at = int(fixture_count * float(train_fraction))
    if fixture_count >= 2:
        split_at = min(fixture_count - 1, max(1, split_at))
    train_items, test_items = ordered[:split_at], ordered[split_at:]
    train_rows = [row for _, item in train_items for row in item["rows"]]
    test_rows = [row for _, item in test_items for row in item["rows"]]
    enough = len(train_items) >= minimum_train_fixtures and len(test_items) >= minimum_test_fixtures
    metrics = evaluate_binary_forecasts(test_rows, probability_key=probability_key, outcome_key=outcome_key, verified_key=verified_key) if enough else evaluate_binary_forecasts([], probability_key=probability_key, outcome_key=outcome_key, verified_key=verified_key)
    return {
        "available": enough,
        "train_fixture_count": len(train_items),
        "test_fixture_count": len(test_items),
        "train_row_count": len(train_rows),
        "test_row_count": len(test_rows),
        "excluded_temporal_rows": excluded_temporal,
        "train_last_timestamp": datetime.fromtimestamp(train_items[-1][1]["first_timestamp"], timezone.utc).isoformat() if train_items else None,
        "test_first_timestamp": datetime.fromtimestamp(test_items[0][1]["first_timestamp"], timezone.utc).isoformat() if test_items else None,
        "test_metrics": metrics,
        "test_metrics_by_market": evaluate_forecasts_by_market(
            test_rows, probability_key=probability_key,
            outcome_key=outcome_key, verified_key=verified_key,
        ) if enough else [],
        "test_metrics_by_market_line": evaluate_forecasts_by_market_line(
            test_rows, probability_key=probability_key,
            outcome_key=outcome_key, verified_key=verified_key,
        ) if enough else [],
        "test_metrics_by_league": evaluate_forecasts_by_group(
            test_rows, group_key="league", probability_key=probability_key,
            outcome_key=outcome_key, verified_key=verified_key,
        ) if enough else [],
        "warnings": [
            "Partición por partido completo: no mezcla snapshots del mismo fixture.",
            "Solo se puntúan resultados verificados del bloque cronológico posterior.",
            "Los timestamps sin zona horaria se excluyen del holdout; no se asume UTC para datos legacy.",
            "Los desgloses por mercado y liga usan exclusivamente el bloque de prueba posterior.",
            "No entrena modelos ni demuestra rentabilidad futura.",
        ],
    }
def evaluate_forecasts_by_group(
    rows: list[dict[str, Any]],
    *,
    group_key: str,
    probability_key: str = "estimated_probability_exploratory",
    outcome_key: str = "outcome",
    verified_key: str = "outcome_verified",
    minimum_sample: int = 30,
) -> list[dict[str, Any]]:
    """Evaluate verified forecasts separately by a non-empty category.

    Rows without a usable group label are omitted from this breakdown. Each
    group uses the same strict verification and probability validation rules
    as the overall evaluator.
    """
    if not isinstance(group_key, str) or not group_key.strip():
        raise ValueError("group_key debe ser un texto no vacío")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        label = str(row.get(group_key, "") or "").strip()
        if not label:
            continue
        grouped.setdefault(label, []).append(row)

    results = []
    for label in sorted(grouped, key=str.casefold):
        metrics = evaluate_binary_forecasts(
            grouped[label],
            probability_key=probability_key,
            outcome_key=outcome_key,
            verified_key=verified_key,
            minimum_sample=minimum_sample,
        )
        results.append({"group": label, **metrics})
    return results



def evaluate_forecasts_by_market(
    rows: list[dict[str, Any]],
    *,
    probability_key: str = "estimated_probability_exploratory",
    outcome_key: str = "outcome",
    verified_key: str = "outcome_verified",
    minimum_sample: int = 30,
) -> list[dict[str, Any]]:
    """Group by canonical market type, with legacy-label fallback."""
    normalized = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("market_type") or row.get("market") or "").strip()
        if label:
            normalized.append({**row, "_evaluation_market_group": label})
    return evaluate_forecasts_by_group(
        normalized, group_key="_evaluation_market_group",
        probability_key=probability_key, outcome_key=outcome_key,
        verified_key=verified_key, minimum_sample=minimum_sample,
    )


def evaluate_forecasts_by_market_line(
    rows: list[dict[str, Any]],
    *,
    probability_key: str = "estimated_probability_exploratory",
    outcome_key: str = "outcome",
    verified_key: str = "outcome_verified",
    minimum_sample: int = 30,
) -> list[dict[str, Any]]:
    """Evaluate separately by market, selection, line, phase and model version.

    Keeping lines and model versions separate avoids pooling unlike binary
    events into one calibration statistic. Rows missing market or line are
    omitted because their event definition is incomplete.
    """
    grouped: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        market = str(row.get("market_type") or row.get("market") or "").strip()
        line = str(row.get("line") or "").strip()
        if not market or not line:
            continue
        key = (
            market,
            str(row.get("selection") or "unknown").strip() or "unknown",
            line,
            str(row.get("phase") or "unknown").strip() or "unknown",
            str(row.get("model_id") or "unknown").strip() or "unknown",
            str(row.get("model_version") or "unknown").strip() or "unknown",
        )
        grouped.setdefault(key, []).append(row)

    results = []
    for key in sorted(grouped, key=lambda item: tuple(part.casefold() for part in item)):
        metrics = evaluate_binary_forecasts(
            grouped[key],
            probability_key=probability_key,
            outcome_key=outcome_key,
            verified_key=verified_key,
            minimum_sample=minimum_sample,
        )
        results.append({
            "market": key[0],
            "selection": key[1],
            "line": key[2],
            "phase": key[3],
            "model_id": key[4],
            "model_version": key[5],
            **metrics,
        })
    return results

def _deduplicate_fixture_snapshots(
    scored_rows: list[tuple[float, int, dict[str, Any]]],
) -> tuple[list[tuple[float, int]], int]:
    """Keep the latest verified snapshot per fixture/event/model.

    Raw ledger rows are never changed. Rows without enough identity or a
    parseable timestamp remain individually scoreable rather than being
    guessed into a group.
    """
    selected: dict[tuple[str, ...], tuple[float, int, float, int]] = {}
    passthrough: list[tuple[float, int]] = []
    duplicates = 0
    for index, (probability, outcome, row) in enumerate(scored_rows):
        fixture = str(row.get("fixture_id") or "").strip()
        market = str(row.get("market_type") or row.get("market") or "").strip()
        selection = str(row.get("selection") or "").strip()
        raw_timestamp = str(row.get("recorded_at") or "").strip()
        if not fixture or not market or not selection or not raw_timestamp:
            passthrough.append((probability, outcome))
            continue
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            order = timestamp.timestamp() if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            passthrough.append((probability, outcome))
            continue
        key = (
            fixture, market, selection,
            str(row.get("line") or "").strip(),
            str(row.get("phase") or "unknown").strip(),
            str(row.get("model_id") or "unknown").strip(),
            str(row.get("model_version") or "unknown").strip(),
        )
        previous = selected.get(key)
        if previous is None:
            selected[key] = (order, index, probability, outcome)
        else:
            duplicates += 1
            if (order, index) > (previous[0], previous[1]):
                selected[key] = (order, index, probability, outcome)
    retained = passthrough + [(item[2], item[3]) for item in selected.values()]
    return retained, duplicates


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

    scored_rows: list[tuple[float, int, dict[str, Any]]] = []
    excluded = 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not _verified(row.get(verified_key, "")):
            excluded += 1
            continue
        outcome = _outcome(row.get(outcome_key))
        raw_probability = row.get(probability_key)
        if raw_probability in (None, "") and probability_key != "probability":
            # Canonical versioned records use "probability"; legacy CSVs retain
            # "estimated_probability_exploratory".
            raw_probability = row.get("probability")
        try:
            probability = float(raw_probability)
        except (TypeError, ValueError, OverflowError):
            probability = math.nan
        if outcome is None or not math.isfinite(probability) or not 0 <= probability <= 1:
            excluded += 1
            continue
        scored.append((probability, outcome))

    n = len(scored)
    if not n:
        return {
            "sample_size": 0, "raw_verified_sample_size": 0,\n            "deduplicated_snapshots": duplicate_snapshots, "excluded": excluded, "brier_score": None,
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
