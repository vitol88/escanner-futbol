"""Append-only SQLite ledger for canonical Football Lab forecasts.

The ledger is separate from the legacy signal CSV. Writes are transactional,
idempotent by prediction_id, and never overwrite an existing forecast.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ai_engine.prediction_schema import normalize_prediction_record

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    fixture_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    phase TEXT NOT NULL,
    market TEXT NOT NULL,
    line TEXT,
    probability REAL NOT NULL,
    model_id TEXT,
    model_version TEXT,
    record_json TEXT NOT NULL
)
"""


def append_prediction_records(
    database_path: str | Path,
    records: list[dict[str, Any]],
) -> dict[str, int]:
    """Persist valid records once; duplicate identities are safely ignored.

    Invalid rows are counted and skipped. A transaction ensures a batch is
    committed completely or not at all if a database error occurs.
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [
        normalize_prediction_record(row)
        for row in (records if isinstance(records, list) else [])
        if isinstance(row, dict)
    ]
    valid = [row for row in normalized if row["valid"]]
    invalid_count = len(normalized) - len(valid)

    inserted = 0
    with sqlite3.connect(str(path), timeout=15) as connection:
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute(_SCHEMA)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_predictions_fixture_time "
            "ON predictions(fixture_id, recorded_at)"
        )
        connection.execute("BEGIN IMMEDIATE")
        for row in valid:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO predictions (
                    prediction_id, fixture_id, recorded_at, phase, market,
                    line, probability, model_id, model_version, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["prediction_id"], row["fixture_id"], row["recorded_at"],
                    row["phase"], row["market"], row["line"], row["probability"],
                    row["model_id"], row["model_version"],
                    json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
                ),
            )
            inserted += max(0, cursor.rowcount)
        connection.commit()

    return {
        "received": len(records) if isinstance(records, list) else 0,
        "valid": len(valid),
        "invalid": invalid_count,
        "inserted": inserted,
        "duplicates": len(valid) - inserted,
    }


def load_prediction_records(database_path: str | Path) -> list[dict[str, Any]]:
    """Read ledger rows in chronological order for evaluation/export workflows."""
    path = Path(database_path)
    if not path.exists():
        return []
    with sqlite3.connect(str(path), timeout=15) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT record_json FROM predictions ORDER BY recorded_at, prediction_id"
        ).fetchall()
    return [json.loads(row["record_json"]) for row in rows]
