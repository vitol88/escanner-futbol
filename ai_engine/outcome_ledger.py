"""Append-only, auditable verification events for stored predictions.

Forecast rows are never modified. A verified result is stored as a separate
event keyed to prediction_id; corrections require an explicit reason and create
a new event rather than rewriting history.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_outcome_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL,
    outcome INTEGER NOT NULL CHECK (outcome IN (0, 1)),
    source TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    correction_reason TEXT,
    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id)
)
"""
_INDEX = """
CREATE INDEX IF NOT EXISTS idx_outcome_events_prediction
ON prediction_outcome_events(prediction_id, event_id)
"""


def record_verified_outcome(
    database_path: str | Path,
    prediction_id: str,
    outcome: int,
    *,
    source: str,
    verified_by: str,
    correction_reason: str = "",
    verified_at: str | None = None,
) -> dict[str, Any]:
    """Append a verified binary result; never updates forecast or prior events."""
    prediction_id = str(prediction_id or "").strip()
    source = str(source or "").strip()
    verified_by = str(verified_by or "").strip()
    correction_reason = str(correction_reason or "").strip()
    if not prediction_id:
        raise ValueError("prediction_id es obligatorio")
    if isinstance(outcome, bool) or outcome not in (0, 1):
        raise ValueError("outcome debe ser 0 o 1")
    if not source or not verified_by:
        raise ValueError("source y verified_by son obligatorios")
    timestamp = verified_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("verified_at debe ser una fecha ISO válida") from exc
    if parsed.tzinfo is None:
        raise ValueError("verified_at debe incluir zona horaria")

    path = Path(database_path)
    if not path.exists():
        raise FileNotFoundError("No existe el registro central de pronósticos")
    with sqlite3.connect(str(path), timeout=15) as connection:
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute(_SCHEMA)
        connection.execute(_INDEX)
        exists = connection.execute(
            "SELECT 1 FROM predictions WHERE prediction_id = ?", (prediction_id,)
        ).fetchone()
        if not exists:
            raise KeyError("prediction_id no existe en el registro central")
        previous = connection.execute(
            "SELECT outcome FROM prediction_outcome_events WHERE prediction_id = ? ORDER BY event_id DESC LIMIT 1",
            (prediction_id,),
        ).fetchone()
        if previous and not correction_reason:
            if int(previous[0]) == outcome:
                return {"inserted": False, "duplicate": True, "event_id": None, "outcome": outcome}
            raise ValueError("El resultado ya existe; una corrección requiere correction_reason")
        if previous and not correction_reason:
            raise ValueError("Una nueva verificación requiere motivo de corrección")
        cursor = connection.execute(
            """INSERT INTO prediction_outcome_events
               (prediction_id, outcome, source, verified_by, verified_at, correction_reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (prediction_id, outcome, source, verified_by, str(timestamp), correction_reason or None),
        )
        return {"inserted": True, "duplicate": False, "event_id": cursor.lastrowid, "outcome": outcome}


def load_verified_outcomes(database_path: str | Path) -> dict[str, dict[str, Any]]:
    """Return the latest explicit verification per prediction, retaining event history."""
    path = Path(database_path)
    if not path.exists():
        return {}
    with sqlite3.connect(str(path), timeout=15) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(_SCHEMA)
        rows = connection.execute(
            """SELECT e.* FROM prediction_outcome_events e
               JOIN (SELECT prediction_id, MAX(event_id) AS latest_event
                     FROM prediction_outcome_events GROUP BY prediction_id) latest
                 ON latest.latest_event = e.event_id
               ORDER BY e.event_id"""
        ).fetchall()
    return {
        row["prediction_id"]: {
            "outcome": int(row["outcome"]),
            "outcome_verified": True,
            "outcome_source": row["source"],
            "outcome_verified_by": row["verified_by"],
            "outcome_verified_at": row["verified_at"],
            "outcome_event_id": row["event_id"],
            "correction_reason": row["correction_reason"],
        }
        for row in rows
    }
