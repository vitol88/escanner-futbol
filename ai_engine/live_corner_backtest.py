"""Leakage-safe baseline backtest for verified live-corner observations.

This is an evaluation baseline, not a trained betting model. Splits are performed
by fixture ID so no minute snapshots from one match can appear on both sides.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from pathlib import Path
from typing import Any


def _minute_bucket(minute: int) -> str:
    start = ((int(minute) - 1) // 15) * 15 + 1
    return f"{start:02d}-{min(start + 14, 120):02d}"


def _fixture_in_test(fixture_id: str, test_fraction: float) -> bool:
    digest = hashlib.sha256(str(fixture_id).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF < test_fraction


def run_live_corner_baseline_backtest(
    database_path: str | Path,
    *,
    test_fraction: float = 0.25,
    min_train_fixtures: int = 5,
    min_test_fixtures: int = 2,
) -> dict[str, Any]:
    """Evaluate minute-bucket mean remaining corners on fixture-held-out data.

    Home and away perspectives are retained as separate observations, but split
    membership is determined solely by fixture ID. Predictions use only training
    fixture targets from the same minute bucket, with a training-wide fallback.
    """
    if not 0.05 <= test_fraction <= 0.5:
        raise ValueError("test_fraction must be between 0.05 and 0.5")
    if min_train_fixtures < 1 or min_test_fixtures < 1:
        raise ValueError("minimum fixture counts must be positive")

    path = Path(database_path)
    if not path.exists():
        return {"available": False, "reason": "database_not_found"}

    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_corner_observations'"
        ).fetchone()
        if not exists:
            return {"available": False, "reason": "verified_history_table_not_found"}
        rows = connection.execute(
            """
            SELECT fixture_id, league, team, venue, minute,
                   corners_for_after, corners_against_after
            FROM live_corner_observations
            ORDER BY fixture_id, minute, venue
            """
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        return {"available": False, "reason": "no_verified_observations"}

    # Each target is a team's remaining corners; fixture-level splitting prevents
    # the mirrored opponent perspective or another minute from leaking across.
    fixture_ids = sorted({str(row["fixture_id"]) for row in rows})
    test_ids = {fid for fid in fixture_ids if _fixture_in_test(fid, test_fraction)}
    train_ids = set(fixture_ids) - test_ids
    if len(test_ids) < min_test_fixtures or len(train_ids) < min_train_fixtures:
        return {
            "available": False,
            "reason": "insufficient_fixture_count_for_holdout",
            "fixtures": len(fixture_ids),
            "train_fixtures": len(train_ids),
            "test_fixtures": len(test_ids),
            "required_train_fixtures": min_train_fixtures,
            "required_test_fixtures": min_test_fixtures,
        }

    train = [row for row in rows if str(row["fixture_id"]) in train_ids]
    test = [row for row in rows if str(row["fixture_id"]) in test_ids]
    by_bucket: dict[str, list[float]] = {}
    train_targets = []
    for row in train:
        target = float(row["corners_for_after"])
        train_targets.append(target)
        by_bucket.setdefault(_minute_bucket(row["minute"]), []).append(target)

    global_mean = sum(train_targets) / len(train_targets)
    absolute_errors = []
    signed_errors = []
    bucket_metrics: dict[str, dict[str, Any]] = {}
    for row in test:
        bucket = _minute_bucket(row["minute"])
        bucket_values = by_bucket.get(bucket) or train_targets
        prediction = sum(bucket_values) / len(bucket_values)
        actual = float(row["corners_for_after"])
        error = prediction - actual
        absolute_errors.append(abs(error))
        signed_errors.append(error)
        metric = bucket_metrics.setdefault(bucket, {"n": 0, "absolute_errors": [], "signed_errors": []})
        metric["n"] += 1
        metric["absolute_errors"].append(abs(error))
        metric["signed_errors"].append(error)

    mae = sum(absolute_errors) / len(absolute_errors)
    bias = sum(signed_errors) / len(signed_errors)
    return {
        "available": True,
        "evaluation": "fixture_holdout_minute_bucket_mean_baseline",
        "warning": "Baseline only; not evidence of betting profitability or model superiority.",
        "split": {
            "method": "stable_sha256_fixture_id_holdout",
            "test_fraction_requested": test_fraction,
            "train_fixtures": len(train_ids),
            "test_fixtures": len(test_ids),
            "train_observations": len(train),
            "test_observations": len(test),
            "fixture_overlap": len(train_ids & test_ids),
        },
        "metrics": {
            "mae_remaining_corners": mae,
            "mean_signed_error_prediction_minus_actual": bias,
            "mean_absolute_percentage_error": None,
        },
        "by_minute_bucket": [
            {
                "minute_bucket": bucket,
                "observations": metric["n"],
                "mae_remaining_corners": sum(metric["absolute_errors"]) / metric["n"],
                "mean_signed_error": sum(metric["signed_errors"]) / metric["n"],
            }
            for bucket, metric in sorted(bucket_metrics.items())
        ],
        "training_reference": {
            "global_mean_remaining_corners": global_mean,
            "minute_bucket_training_samples": {
                bucket: len(values) for bucket, values in sorted(by_bucket.items())
            },
        },
    }
