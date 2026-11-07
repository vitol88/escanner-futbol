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
    global_values = [float(row["corners_for_after"]) for row in train]
    global_mean = sum(global_values) / len(global_values)
    league_values: dict[str, list[float]] = {}
    bucket_values: dict[tuple[str, str], list[float]] = {}
    for row in train:
        league = str(row["league"] or "Unknown")
        target = float(row["corners_for_after"])
        league_values.setdefault(league, []).append(target)
        bucket_values.setdefault((league, _minute_bucket(row["minute"])), []).append(target)

    abs_errors, signed_errors = [], []
    for row in rows:
        league = str(row["league"] or "Unknown")
        values = bucket_values.get((league, _minute_bucket(row["minute"])))
        if not values:
            values = league_values.get(league) or global_values
        prediction = sum(values) / len(values) if values else global_mean
        error = prediction - float(row["corners_for_after"])
        abs_errors.append(abs(error))
        signed_errors.append(error)
    return {
        "observations": len(rows),
        "mae_remaining_corners": sum(abs_errors) / len(abs_errors),
        "mean_signed_error": sum(signed_errors) / len(signed_errors),
    }


def run_live_corner_baseline_backtest(
    database_path: str | Path,
    *,
    test_fraction: float = 0.25,
    min_train_fixtures: int = 5,
    min_test_fixtures: int = 2,
    min_league_test_fixtures: int = 2,
) -> dict[str, Any]:
    """Train on earlier fixtures and evaluate on the latest chronological fixtures.

    All minute snapshots and both team perspectives from a fixture stay together.
    Prediction fallback is league+minute bucket, league-wide, then global.
    """
    if not 0.05 <= test_fraction <= 0.5:
        raise ValueError("test_fraction must be between 0.05 and 0.5")
    if min_train_fixtures < 1 or min_test_fixtures < 1 or min_league_test_fixtures < 1:
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

    ordered_fixtures = sorted(timestamps, key=lambda fixture_id: (timestamps[fixture_id], fixture_id))
    test_count = max(min_test_fixtures, int(math.ceil(len(ordered_fixtures) * test_fraction)))
    test_count = min(test_count, len(ordered_fixtures) - min_train_fixtures)
    if test_count < min_test_fixtures or len(ordered_fixtures) - test_count < min_train_fixtures:
        return {
            "available": False, "reason": "insufficient_fixture_count_for_chronological_split",
            "fixtures": len(ordered_fixtures), "required_train_fixtures": min_train_fixtures,
            "required_test_fixtures": min_test_fixtures,
        }

    train_ids = set(ordered_fixtures[:-test_count])
    test_ids = set(ordered_fixtures[-test_count:])
    train = [row for row in rows if str(row["fixture_id"]) in train_ids]
    test = [row for row in rows if str(row["fixture_id"]) in test_ids]
    overall = _metrics(test, train)

    league_ids = sorted({str(row["league"] or "Unknown") for row in test})
    by_league = []
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
            continue
        metrics = _metrics(league_test, league_train or train)
        by_league.append({
            "league": league, "available": True,
            "train_fixtures_in_league": len({str(row["fixture_id"]) for row in league_train}),
            "test_fixtures": fixture_count,
            **metrics,
        })

    return {
        "available": True,
        "evaluation": "chronological_fixture_holdout_minute_bucket_mean_baseline",
        "warning": "Baseline only; not evidence of betting profitability or model superiority.",
        "split": {
            "method": "chronological_fixture_timestamp",
            "train_fixtures": len(train_ids), "test_fixtures": len(test_ids),
            "train_observations": len(train), "test_observations": len(test),
            "fixture_overlap": len(train_ids & test_ids),
            "train_latest_timestamp": max(timestamps[item] for item in train_ids),
            "test_earliest_timestamp": min(timestamps[item] for item in test_ids),
        },
        "metrics": overall,
        "by_league": by_league,
    }
