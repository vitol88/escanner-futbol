"""Chronological, fixture-leakage-safe baseline backtest for live corners."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any


def _minute_bucket(minute: int) -> str:
    start = ((int(minute) - 1) // 15) * 15 + 1
    return f"{start:02d}-{min(start + 14, 120):02d}"


def _metrics(rows: list[sqlite3.Row], train: list[sqlite3.Row]) -> dict[str, Any]:
    if not rows or not train:
        return {"observations": len(rows), "mae_remaining_corners": None, "mean_signed_error": None}
    abs_errors, signed_errors = [], []
    for row in rows:
        prediction = _predict_remaining(row, train)
        error = prediction - float(row["corners_for_after"])
        abs_errors.append(abs(error))
        signed_errors.append(error)
    return {
        "observations": len(rows),
        "mae_remaining_corners": sum(abs_errors) / len(abs_errors),
        "mean_signed_error": sum(signed_errors) / len(signed_errors),
        "training_weighting": "equal_fixture_weight_within_minute_bucket_league_and_global_fallback",
    }




def _fixture_balanced_values(rows: list[sqlite3.Row]) -> list[float]:
    """Return one mean target per fixture so dense snapshots cannot dominate."""
    by_fixture: dict[str, list[float]] = {}
    for item in rows:
        by_fixture.setdefault(str(item["fixture_id"]), []).append(
            float(item["corners_for_after"])
        )
    return [
        sum(values) / len(values)
        for values in by_fixture.values() if values
    ]


def _predict_remaining(row: sqlite3.Row, train: list[sqlite3.Row]) -> float:
    """Predict from training data, giving each fixture equal weight per segment."""
    league = str(row["league"] or "Unknown")
    bucket = _minute_bucket(row["minute"])
    league_rows = [
        item for item in train if str(item["league"] or "Unknown") == league
    ]
    bucket_rows = [
        item for item in league_rows if _minute_bucket(item["minute"]) == bucket
    ]
    values = (
        _fixture_balanced_values(bucket_rows)
        or _fixture_balanced_values(league_rows)
        or _fixture_balanced_values(train)
    )
    return sum(values) / len(values)


def _fixture_weighted_metrics(
    rows: list[sqlite3.Row], train: list[sqlite3.Row]
) -> dict[str, Any]:
    """Give each held-out fixture equal weight after averaging its row errors."""
    if not rows or not train:
        return {
            "fixtures": 0, "observations": len(rows),
            "mae_remaining_corners": None, "mean_signed_error": None,
        }
    errors_by_fixture: dict[str, list[float]] = {}
    for row in rows:
        prediction = _predict_remaining(row, train)
        actual = float(row["corners_for_after"])
        errors_by_fixture.setdefault(str(row["fixture_id"]), []).append(prediction - actual)
    fixture_maes = [
        sum(abs(error) for error in errors) / len(errors)
        for errors in errors_by_fixture.values()
    ]
    fixture_biases = [
        sum(errors) / len(errors) for errors in errors_by_fixture.values()
    ]
    return {
        "fixtures": len(errors_by_fixture),
        "observations": len(rows),
        "mae_remaining_corners": sum(fixture_maes) / len(fixture_maes),
        "mean_signed_error": sum(fixture_biases) / len(fixture_biases),
        "weighting": "equal_fixture_weight_after_within_fixture_observation_average",
    }


def _line_metrics(
    rows: list[sqlite3.Row], train: list[sqlite3.Row], lines: tuple[float, ...]
) -> list[dict[str, Any]]:
    """Classify over/under half-point lines; this is not a probability or signal."""
    results = []
    for line in lines:
        tp = tn = fp = fn = 0
        for row in rows:
            actual_over = float(row["corners_for_after"]) > line
            predicted_over = _predict_remaining(row, train) > line
            if predicted_over and actual_over:
                tp += 1
            elif predicted_over and not actual_over:
                fp += 1
            elif not predicted_over and actual_over:
                fn += 1
            else:
                tn += 1
        total = tp + tn + fp + fn
        over_actual = tp + fn
        under_actual = tn + fp
        sensitivity = tp / over_actual if over_actual else None
        specificity = tn / under_actual if under_actual else None
        balanced = (
            (sensitivity + specificity) / 2
            if sensitivity is not None and specificity is not None else None
        )
        results.append({
            "line": line, "observations": total,
            "actual_over_rate": over_actual / total if total else None,
            "predicted_over_rate": (tp + fp) / total if total else None,
            "accuracy": (tp + tn) / total if total else None,
            "sensitivity_over": sensitivity,
            "specificity_under": specificity,
            "balanced_accuracy": balanced,
            "confusion_matrix": {
                "true_over": tp, "false_over": fp,
                "missed_over": fn, "true_under": tn,
            },
            "decision_rule": "predicted_mean_and_actual_remaining_corners_greater_than_line",
            "warning": "Descriptive threshold classification only; no probability, odds, ROI, or betting signal.",
        })
    return results

def _rolling_origin_metrics(rows, timestamps, ordered_timestamps, *, folds, min_train_fixtures, min_test_fixtures):
    """Evaluate future blocks with expanding, strictly earlier training."""
    if folds < 2:
        raise ValueError("rolling_folds must be at least 2")
    if len(ordered_timestamps) < folds + 1:
        return {"available": False, "reason": "insufficient_kickoff_groups_for_rolling_folds"}
    by_time = {}
    for fixture_id, timestamp in timestamps.items():
        by_time.setdefault(timestamp, set()).add(fixture_id)
    initial_groups = max(1, len(ordered_timestamps) // (folds + 1))
    remaining = ordered_timestamps[initial_groups:]
    if len(remaining) < folds:
        return {"available": False, "reason": "insufficient_kickoff_groups_for_rolling_folds"}
    results = []
    for index in range(folds):
        start = len(remaining) * index // folds
        end = len(remaining) * (index + 1) // folds
        test_times = remaining[start:end]
        train_ids = {fid for fid, ts in timestamps.items() if ts < test_times[0]}
        test_ids = set().union(*(by_time[ts] for ts in test_times))
        if len(train_ids) < min_train_fixtures or len(test_ids) < min_test_fixtures:
            return {"available": False, "reason": "insufficient_fixtures_in_rolling_fold",
                    "fold": index + 1, "train_fixtures": len(train_ids),
                    "test_fixtures": len(test_ids)}
        train = [r for r in rows if str(r["fixture_id"]) in train_ids]
        test = [r for r in rows if str(r["fixture_id"]) in test_ids]
        metrics = _metrics(test, train)
        fixture_means = _fixture_balanced_values(train)
        mean = sum(fixture_means) / len(fixture_means)
        errors = [mean - float(r["corners_for_after"]) for r in test]
        benchmark = sum(abs(e) for e in errors) / len(errors)
        improvement = ((benchmark - metrics["mae_remaining_corners"]) / benchmark
                       if benchmark > 0 else None)
        results.append({
            "fold": index + 1, "train_fixtures": len(train_ids),
            "test_fixtures": len(test_ids),
            "train_latest_timestamp": max(timestamps[x] for x in train_ids),
            "test_earliest_timestamp": min(timestamps[x] for x in test_ids),
            "fixture_overlap": len(train_ids & test_ids),
            "metrics": metrics, "global_mean_benchmark_mae": benchmark,
            "mae_improvement_vs_global_mean": improvement,
        })
    total = sum(x["metrics"]["observations"] for x in results)
    mae = sum(x["metrics"]["mae_remaining_corners"] * x["metrics"]["observations"]
              for x in results) / total
    benchmark = sum(x["global_mean_benchmark_mae"] * x["metrics"]["observations"]
                    for x in results) / total
    improvements = [x["mae_improvement_vs_global_mean"] for x in results
                    if x["mae_improvement_vs_global_mean"] is not None]
    positive_folds = sum(value > 0 for value in improvements)
    negative_folds = sum(value < 0 for value in improvements)
    fold_maes = [x["metrics"]["mae_remaining_corners"] for x in results]
    weighted_improvement = (benchmark - mae) / benchmark if benchmark > 0 else None
    # Conservative descriptive status, not a model-approval or betting gate.
    if len(improvements) != len(results):
        stability = "not_assessable_zero_error_reference"
    elif positive_folds == len(results):
        stability = "improves_in_every_fold"
    elif negative_folds == len(results):
        stability = "worse_in_every_fold"
    elif positive_folds > 0 and negative_folds > 0:
        stability = "mixed_results"
    else:
        stability = "no_material_difference"
    return {
        "available": True, "method": "expanding_window_chronological_folds",
        "fold_count": len(results), "total_test_observations": total,
        "weighted_mae_remaining_corners": mae,
        "weighted_global_mean_benchmark_mae": benchmark,
        "weighted_mae_improvement_vs_global_mean": weighted_improvement,
        "positive_improvement_folds": positive_folds,
        "negative_improvement_folds": negative_folds,
        "fold_mae_min": min(fold_maes),
        "fold_mae_max": max(fold_maes),
        "fold_mae_range": max(fold_maes) - min(fold_maes),
        "stability": stability,
        "folds": results,
        "warning": "Descriptive stability only; not evidence of betting profitability or model approval.",
    }

def run_live_corner_baseline_backtest(
    database_path: str | Path,
    *,
    test_fraction: float = 0.25,
    min_train_fixtures: int = 5,
    min_test_fixtures: int = 2,
    min_league_test_fixtures: int = 2,
    min_bucket_test_fixtures: int = 2,
    rolling_folds: int = 3,
    over_under_lines: tuple[float, ...] = (),
) -> dict[str, Any]:
    """Train on earlier kickoff times and evaluate on the latest chronological block.

    All minute snapshots and both team perspectives from a fixture stay together.
    Fixtures sharing the same kickoff timestamp also stay on the same side of the
    split. Prediction fallback is league+minute bucket, league-wide, then global.
    """
    if rolling_folds < 2:
        raise ValueError("rolling_folds must be at least 2")
    normalized_lines = tuple(float(line) for line in over_under_lines)
    if any(not math.isfinite(line) or line < 0 or not math.isclose(line % 1, 0.5, abs_tol=1e-9) for line in normalized_lines):
        raise ValueError("over_under_lines must contain nonnegative half-point lines")
    if len(set(normalized_lines)) != len(normalized_lines):
        raise ValueError("over_under_lines must be unique")
    if not 0.05 <= test_fraction <= 0.5:
        raise ValueError("test_fraction must be between 0.05 and 0.5")
    if min(
        min_train_fixtures, min_test_fixtures,
        min_league_test_fixtures, min_bucket_test_fixtures,
    ) < 1:
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
        columns = {row["name"] for row in connection.execute(
            "PRAGMA table_info(live_corner_observations)"
        )}
        if "fixture_timestamp" not in columns:
            return {"available": False, "reason": "fixture_timestamps_not_recorded"}
        rows = connection.execute(
            """
            SELECT fixture_id, league, team, venue, minute,
                   corners_for_after, corners_against_after, fixture_timestamp
            FROM live_corner_observations
            ORDER BY fixture_timestamp, fixture_id, minute, venue
            """
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        return {"available": False, "reason": "no_verified_observations"}
    timestamps: dict[str, int] = {}
    for row in rows:
        if row["fixture_timestamp"] is None:
            return {
                "available": False, "reason": "incomplete_fixture_timestamps",
                "fixture_id": str(row["fixture_id"]),
            }
        fixture_id = str(row["fixture_id"])
        timestamp = int(row["fixture_timestamp"])
        if fixture_id in timestamps and timestamps[fixture_id] != timestamp:
            return {
                "available": False, "reason": "conflicting_fixture_timestamps",
                "fixture_id": fixture_id,
            }
        timestamps[fixture_id] = timestamp

    fixtures_by_timestamp: dict[int, set[str]] = {}
    for fixture_id, timestamp in timestamps.items():
        fixtures_by_timestamp.setdefault(timestamp, set()).add(fixture_id)
    ordered_timestamps = sorted(fixtures_by_timestamp)
    target_test_fixtures = max(
        min_test_fixtures, int(math.ceil(len(timestamps) * test_fraction))
    )
    test_timestamps: set[int] = set()
    test_fixture_ids: set[str] = set()
    for timestamp in reversed(ordered_timestamps):
        test_timestamps.add(timestamp)
        test_fixture_ids.update(fixtures_by_timestamp[timestamp])
        if len(test_fixture_ids) >= target_test_fixtures:
            break
    train_ids = set(timestamps) - test_fixture_ids
    test_ids = test_fixture_ids
    if len(train_ids) < min_train_fixtures or len(test_ids) < min_test_fixtures:
        return {
            "available": False, "reason": "insufficient_fixture_count_for_chronological_split",
            "fixtures": len(timestamps), "required_train_fixtures": min_train_fixtures,
            "required_test_fixtures": min_test_fixtures,
        }

    train = [row for row in rows if str(row["fixture_id"]) in train_ids]
    test = [row for row in rows if str(row["fixture_id"]) in test_ids]
    overall = _metrics(test, train)
    # Independent naive benchmark: one global mean from training, applied to
    # every held-out observation. This reveals whether segmented averages add
    # value beyond a constant prediction without using any test outcomes.
    fixture_training_means = _fixture_balanced_values(train)
    global_training_mean = sum(fixture_training_means) / len(fixture_training_means)
    global_errors = [
        global_training_mean - float(row["corners_for_after"]) for row in test
    ]
    global_mean_baseline = {
        "observations": len(test),
        "mae_remaining_corners": sum(abs(error) for error in global_errors) / len(global_errors),
        "mean_signed_error": sum(global_errors) / len(global_errors),
    }
    mae_improvement = (
        (global_mean_baseline["mae_remaining_corners"] - overall["mae_remaining_corners"])
        / global_mean_baseline["mae_remaining_corners"]
        if global_mean_baseline["mae_remaining_corners"] > 0 else None
    )

    rolling = _rolling_origin_metrics(
        rows, timestamps, ordered_timestamps, folds=rolling_folds,
        min_train_fixtures=min_train_fixtures, min_test_fixtures=min_test_fixtures,
    )

    league_ids = sorted({str(row["league"] or "Unknown") for row in test})
    by_league = []
    by_league_minute_bucket = []
    for league in league_ids:
        league_test = [row for row in test if str(row["league"] or "Unknown") == league]
        league_train = [row for row in train if str(row["league"] or "Unknown") == league]
        fixture_count = len({str(row["fixture_id"]) for row in league_test})
        if fixture_count < min_league_test_fixtures:
            by_league.append({
                "league": league, "available": False,
                "reason": "insufficient_test_fixtures_for_league",
                "test_fixtures": fixture_count,
                "required_test_fixtures": min_league_test_fixtures,
            })
        else:
            metrics = _metrics(league_test, league_train or train)
            by_league.append({
                "league": league, "available": True,
                "train_fixtures_in_league": len({str(row["fixture_id"]) for row in league_train}),
                "test_fixtures": fixture_count,
                "training_source": "league" if league_train else "global_fallback",
                **metrics,
            })

        buckets = sorted({_minute_bucket(row["minute"]) for row in league_test})
        for bucket in buckets:
            bucket_test = [
                row for row in league_test if _minute_bucket(row["minute"]) == bucket
            ]
            bucket_train = [
                row for row in league_train if _minute_bucket(row["minute"]) == bucket
            ]
            bucket_test_fixtures = len({str(row["fixture_id"]) for row in bucket_test})
            bucket_train_fixtures = len({str(row["fixture_id"]) for row in bucket_train})
            if bucket_test_fixtures < min_bucket_test_fixtures:
                by_league_minute_bucket.append({
                    "league": league, "minute_bucket": bucket, "available": False,
                    "reason": "insufficient_test_fixtures_for_bucket",
                    "train_fixtures_in_bucket": bucket_train_fixtures,
                    "test_fixtures": bucket_test_fixtures,
                    "required_test_fixtures": min_bucket_test_fixtures,
                })
                continue
            metrics = _metrics(bucket_test, bucket_train or league_train or train)
            by_league_minute_bucket.append({
                "league": league, "minute_bucket": bucket, "available": True,
                "train_fixtures_in_bucket": bucket_train_fixtures,
                "test_fixtures": bucket_test_fixtures,
                "training_source": (
                    "league_minute_bucket" if bucket_train
                    else "league_fallback" if league_train else "global_fallback"
                ),
                **metrics,
            })

    return {
        "available": True,
        "evaluation": "chronological_fixture_holdout_minute_bucket_mean_baseline",
        "warning": (
            "Baseline only; not evidence of betting profitability or model superiority. "
            "Read league and minute-bucket metrics together with their fixture counts."
        ),
        "split": {
            "method": "chronological_fixture_timestamp_grouped",
            "train_fixtures": len(train_ids), "test_fixtures": len(test_ids),
            "train_observations": len(train), "test_observations": len(test),
            "fixture_overlap": len(train_ids & test_ids),
            "train_latest_timestamp": max(timestamps[item] for item in train_ids),
            "test_earliest_timestamp": min(timestamps[item] for item in test_ids),
            "distinct_kickoff_timestamps": len(ordered_timestamps),
            "test_kickoff_timestamp_groups": len(test_timestamps),
        },
        "metrics": overall,
        "fixture_weighted_metrics": _fixture_weighted_metrics(test, train),
        "benchmark": {
            "name": "global_training_mean",
            **global_mean_baseline,
        },
        "mae_improvement_vs_global_mean": mae_improvement,
        "rolling_origin": rolling,
        "over_under_line_evaluation": _line_metrics(test, train, normalized_lines),
        "by_league": by_league,
        "by_league_minute_bucket": by_league_minute_bucket,
    }
