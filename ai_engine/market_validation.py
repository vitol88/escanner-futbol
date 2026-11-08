"""Readiness diagnostics for empirical calibration of live count markets.

This module deliberately does not produce betting probabilities. It reports
whether the local, verified historical sample is large enough to begin
calibration work, without making API calls or modifying the database.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def corner_calibration_readiness(
    database_path: str | Path,
    *,
    min_fixtures: int = 30,
    min_observations: int = 100,
) -> dict[str, Any]:
    """Summarize finalized live-corner observations by distinct fixture.

    Each finalized snapshot yields a home and away perspective row. The fixture
    count, not row count, is the primary guard against overstating sample size.
    """
    path = Path(database_path)
    if not path.exists():
        return {
            "available": False,
            "ready_for_calibration": False,
            "reason": "database_not_found",
            "fixtures": 0,
            "observations": 0,
        }

    try:
        with sqlite3.connect(str(path), timeout=5) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_corner_observations'"
            ).fetchone()
            if not table:
                return {
                    "available": False,
                    "ready_for_calibration": False,
                    "reason": "observations_table_not_found",
                    "fixtures": 0,
                    "observations": 0,
                }
            observations, fixtures, min_minute, max_minute = connection.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT fixture_id),
                       MIN(minute), MAX(minute)
                FROM live_corner_observations
                WHERE minute BETWEEN 1 AND 120
                  AND corners_for >= 0 AND corners_against >= 0
                  AND corners_for_after >= 0 AND corners_against_after >= 0
                """
            ).fetchone()
    except sqlite3.Error as exc:
        return {
            "available": False,
            "ready_for_calibration": False,
            "reason": "database_read_error",
            "detail": str(exc)[:240],
            "fixtures": 0,
            "observations": 0,
        }

    fixtures = int(fixtures or 0)
    observations = int(observations or 0)
    ready = fixtures >= min_fixtures and observations >= min_observations
    return {
        "available": True,
        "ready_for_calibration": ready,
        "reason": "minimum_sample_reached" if ready else "insufficient_verified_sample",
        "fixtures": fixtures,
        "observations": observations,
        "minute_range": [min_minute, max_minute] if observations else None,
        "minimum_fixtures": min_fixtures,
        "minimum_observations": min_observations,
    }


def card_calibration_readiness(
    history_rows: list[dict[str, Any]] | None,
    *,
    min_fixtures: int = 30,
) -> dict[str, Any]:
    """Check unique, timestamped historical fixtures with both teams' card counts."""
    unique: dict[str, dict[str, Any]] = {}
    for row in history_rows or []:
        if not isinstance(row, dict):
            continue
        fixture_id = str(row.get("fixture_id") or "").strip()
        timestamp = row.get("fixture_timestamp")
        home = row.get("home_yellow_cards")
        away = row.get("away_yellow_cards")
        valid_counts = all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
            for value in (home, away)
        )
        valid_timestamp = (
            isinstance(timestamp, (int, float))
            and not isinstance(timestamp, bool)
            and timestamp > 0
        )
        if fixture_id and valid_counts and valid_timestamp:
            unique[fixture_id] = row

    count = len(unique)
    ready = count >= min_fixtures
    return {
        "available": count > 0,
        "ready_for_calibration": ready,
        "reason": "minimum_sample_reached" if ready else "insufficient_verified_sample",
        "fixtures": count,
        "minimum_fixtures": min_fixtures,
    }
