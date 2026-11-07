"""SQLite bridge for validated minute-level live-corner history.

CSV input is validated by live_corner_history; this module persists only accepted
observations and supplies the stored rows to the experimental model pipeline.
It does not fetch data, alter Streamlit state, or emit betting recommendations.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ai_engine.live_corner_history import load_live_corner_history_csv
from ai_engine.pipeline import analyze_experimental_models


_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_corner_observations (
    fixture_id TEXT NOT NULL,
    league TEXT NOT NULL,
    team TEXT NOT NULL,
    team_key TEXT NOT NULL,
    venue TEXT NOT NULL CHECK (venue IN ('home', 'away')),
    minute INTEGER NOT NULL CHECK (minute BETWEEN 1 AND 120),
    corners_for INTEGER NOT NULL CHECK (corners_for >= 0),
    corners_against INTEGER NOT NULL CHECK (corners_against >= 0),
    corners_for_after INTEGER NOT NULL CHECK (corners_for_after >= 0),
    corners_against_after INTEGER NOT NULL CHECK (corners_against_after >= 0),
    PRIMARY KEY (fixture_id, team_key, venue, minute)
)
"""


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15)
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute(_SCHEMA)
    return connection


def sync_live_corner_history_to_sqlite(
    database_path: str | Path,
    csv_path: str | Path,
) -> dict[str, Any]:
    """Validate a CSV and append accepted observations idempotently to SQLite."""
    report = load_live_corner_history_csv(csv_path)
    rows = report.get("rows", []) if isinstance(report, dict) else []
    inserted = 0
    with _connect(database_path) as connection:
        for row in rows:
            team = str(row["team"]).strip()
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO live_corner_observations (
                    fixture_id, league, team, team_key, venue, minute,
                    corners_for, corners_against,
                    corners_for_after, corners_against_after
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row["fixture_id"]), str(row["league"]), team,
                    " ".join(team.casefold().split()), row["venue"], int(row["minute"]),
                    int(row["corners_for"]), int(row["corners_against"]),
                    int(row["corners_for_after"]), int(row["corners_against_after"]),
                ),
            )
            inserted += max(0, cursor.rowcount)

    result = dict(report)
    result["persisted"] = inserted
    result["already_stored"] = max(0, len(rows) - inserted)
    result["database_path"] = str(database_path)
    return result


def load_live_corner_history_from_sqlite(
    database_path: str | Path,
) -> list[dict[str, Any]]:
    """Return persisted observations in the shape expected by the live model."""
    path = Path(database_path)
    if not path.exists():
        return []
    with _connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT fixture_id, league, team, venue, minute,
                   corners_for, corners_against,
                   corners_for_after, corners_against_after
            FROM live_corner_observations
            ORDER BY fixture_id, team_key, venue, minute
            """
        ).fetchall()
    return [dict(row) for row in rows]


def analyze_with_persisted_live_corner_history(
    database_path: str | Path,
    csv_path: str | Path,
    features: dict[str, Any],
    history: dict[str, Any] | None = None,
    **pipeline_options: Any,
) -> dict[str, Any]:
    """Sync the CSV, then run the pipeline with the complete SQLite history.

    Previously stored observations remain available when the CSV is missing or
    contains no valid rows. The sync report is returned separately for audit.
    """
    sync_report = sync_live_corner_history_to_sqlite(database_path, csv_path)
    stored_rows = load_live_corner_history_from_sqlite(database_path)
    analysis = analyze_experimental_models(
        features,
        history,
        live_corner_history_rows=stored_rows,
        **pipeline_options,
    )
    return {
        "history_sync": sync_report,
        "history_observations": len(stored_rows),
        "analysis": analysis,
    }
