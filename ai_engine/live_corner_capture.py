"""Capture raw live-corner snapshots without making API requests."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_corner_capture_snapshots (
    fixture_id TEXT NOT NULL,
    fixture_date TEXT,
    fixture_timestamp INTEGER,
    league_id TEXT,
    league_name TEXT NOT NULL,
    home_team_id TEXT,
    away_team_id TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    minute INTEGER NOT NULL CHECK (minute BETWEEN 1 AND 120),
    home_corners INTEGER NOT NULL CHECK (home_corners >= 0),
    away_corners INTEGER NOT NULL CHECK (away_corners >= 0),
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    PRIMARY KEY (fixture_id, minute)
)
"""


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0 or not number.is_integer():
        return None
    return int(number)


def _corner_value(stat_rows: list[dict[str, Any]], team_id: Any) -> int | None:
    """Read corners only from the statistics row matching the requested team ID."""
    expected_id = str(team_id or "").strip()
    if not expected_id:
        return None
    for row in stat_rows:
        row_team_id = str(((row.get("team") or {}).get("id")) or "").strip()
        if row_team_id != expected_id:
            continue
        for item in row.get("statistics") or []:
            if item.get("type") == "Corner Kicks":
                return _nonnegative_int(item.get("value"))
        return None
    return None


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15)
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute(_SCHEMA)
    # Safe additive migration for databases created by earlier app versions.
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(live_corner_capture_snapshots)"
    )}
    if "fixture_timestamp" not in columns:
        connection.execute(
            "ALTER TABLE live_corner_capture_snapshots ADD COLUMN fixture_timestamp INTEGER"
        )
    return connection


def capture_live_corner_snapshot(
    database_path: str | Path,
    fixture: dict[str, Any],
    statistics: list[dict[str, Any]],
    *,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist one valid live fixture snapshot; make no network/API calls."""
    fixture_data = fixture.get("fixture") or {}
    status = fixture_data.get("status") or {}
    status_short = str(status.get("short") or "").upper()
    minute = _nonnegative_int(status.get("elapsed"))
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    league = fixture.get("league") or {}
    fixture_id = str(fixture_data.get("id") or "").strip()
    home_name = str(home.get("name") or "").strip()
    away_name = str(away.get("name") or "").strip()
    home_team_id = str(home.get("id") or "").strip()
    away_team_id = str(away.get("id") or "").strip()
    home_corners = _corner_value(statistics, home_team_id)
    away_corners = _corner_value(statistics, away_team_id)
    timestamp = _nonnegative_int(fixture_data.get("timestamp"))

    if status_short in {"", "NS", "HT", "FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"}:
        return {"stored": False, "reason": "fixture_not_in_live_play"}
    if not fixture_id or not home_name or not away_name:
        return {"stored": False, "reason": "missing_fixture_identity"}
    if not home_team_id or not away_team_id or home_team_id == away_team_id:
        return {"stored": False, "reason": "missing_fixture_team_identity"}
    if minute is None or not 1 <= minute <= 120:
        return {"stored": False, "reason": "invalid_elapsed_minute"}
    if home_corners is None or away_corners is None:
        return {"stored": False, "reason": "corner_statistics_unavailable"}

    stamp = captured_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    stamp_text = stamp.astimezone(timezone.utc).isoformat()
    inserted = False
    with closing(_connect(database_path)) as connection:
        with connection:
            existing = connection.execute(
                "SELECT 1 FROM live_corner_capture_snapshots WHERE fixture_id = ? AND minute = ?",
                (fixture_id, minute),
            ).fetchone()
            inserted = existing is None
            connection.execute(
                """
                INSERT INTO live_corner_capture_snapshots (
                    fixture_id, fixture_date, fixture_timestamp, league_id, league_name,
                    home_team_id, away_team_id, home_team, away_team, minute,
                    home_corners, away_corners, first_seen_at_utc, last_seen_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fixture_id, minute) DO UPDATE SET
                    home_corners = MAX(home_corners, excluded.home_corners),
                    away_corners = MAX(away_corners, excluded.away_corners),
                    fixture_timestamp = COALESCE(fixture_timestamp, excluded.fixture_timestamp),
                    last_seen_at_utc = excluded.last_seen_at_utc
                """,
                (
                    fixture_id, str(fixture_data.get("date") or ""), timestamp,
                    str(league.get("id") or ""), str(league.get("name") or "Unknown league"),
                    str(home.get("id") or ""), str(away.get("id") or ""),
                    home_name, away_name, minute, home_corners, away_corners,
                    stamp_text, stamp_text,
                ),
            )

    return {
        "stored": True, "inserted": inserted, "fixture_id": fixture_id,
        "minute": minute, "home_corners": home_corners, "away_corners": away_corners,
    }


def count_live_corner_snapshots(database_path: str | Path) -> int:
    """Return the number of captured fixture/minute snapshots."""
    path = Path(database_path)
    if not path.exists():
        return 0
    with closing(_connect(path)) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM live_corner_capture_snapshots"
        ).fetchone()
    return int(row[0])
