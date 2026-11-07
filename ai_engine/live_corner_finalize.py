"""Finalize captured live-corner snapshots against verified full-time statistics.

This module performs no network requests. The caller must supply a completed fixture
and its final fixture/statistics payload obtained from an existing, budgeted API flow.
Only then are provisional snapshots converted into minute-level training observations.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from ai_engine.live_corner_capture import _corner_value, _connect


_FINISHED_STATUSES = {"FT", "AET", "PEN"}


def _team_corner_count(statistics: list[dict[str, Any]], team_id: Any) -> int | None:
    target = str(team_id or "").strip()
    if not target:
        return None
    for row in statistics:
        if str((row.get("team") or {}).get("id") or "").strip() == target:
            values = row.get("statistics") or []
            return _corner_value([{"statistics": values}], 0)
    return None


def finalize_live_corner_fixture(
    database_path: str | Path,
    fixture: dict[str, Any],
    final_statistics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert every captured minute into two validated team-perspective rows.

    A fixture is finalized only when its status is FT/AET/PEN, identity matches
    the stored snapshots, and final corner counts are present and not below any
    observed live count. Existing rows are idempotently ignored on repeat calls.
    """
    fixture_data = fixture.get("fixture") or {}
    status = str((fixture_data.get("status") or {}).get("short") or "").upper()
    fixture_id = str(fixture_data.get("id") or "").strip()
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    home_name = str(home.get("name") or "").strip()
    away_name = str(away.get("name") or "").strip()
    league = fixture.get("league") or {}
    league_name = str(league.get("name") or "").strip()

    if status not in _FINISHED_STATUSES:
        return {"finalized": False, "reason": "fixture_not_finished"}
    if not fixture_id or not home_id or not away_id or not home_name or not away_name or not league_name:
        return {"finalized": False, "reason": "missing_fixture_identity"}

    final_home = _team_corner_count(final_statistics, home_id)
    final_away = _team_corner_count(final_statistics, away_id)
    if final_home is None or final_away is None:
        return {"finalized": False, "reason": "final_corner_statistics_unavailable"}

    inserted = 0
    snapshots_seen = 0
    with closing(_connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
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
            )
            snapshots = connection.execute(
                """
                SELECT minute, home_team_id, away_team_id, home_team, away_team,
                       league_name, home_corners, away_corners
                FROM live_corner_capture_snapshots
                WHERE fixture_id = ?
                ORDER BY minute
                """,
                (fixture_id,),
            ).fetchall()
            snapshots_seen = len(snapshots)
            if not snapshots:
                return {
                    "finalized": False,
                    "reason": "no_captured_snapshots",
                    "fixture_id": fixture_id,
                }

            for row in snapshots:
                minute, stored_home_id, stored_away_id, stored_home, stored_away, stored_league, seen_home, seen_away = row
                if (
                    str(stored_home_id or "") != str(home_id)
                    or str(stored_away_id or "") != str(away_id)
                    or str(stored_home).strip() != home_name
                    or str(stored_away).strip() != away_name
                ):
                    return {
                        "finalized": False,
                        "reason": "fixture_identity_mismatch",
                        "fixture_id": fixture_id,
                    }
                if stored_league and stored_league != league_name:
                    return {
                        "finalized": False,
                        "reason": "league_identity_mismatch",
                        "fixture_id": fixture_id,
                    }
                if final_home < seen_home or final_away < seen_away:
                    return {
                        "finalized": False,
                        "reason": "final_count_below_live_snapshot",
                        "fixture_id": fixture_id,
                        "minute": minute,
                    }

            for row in snapshots:
                minute, _, _, stored_home, stored_away, stored_league, seen_home, seen_away = row
                values = (
                    (
                        fixture_id, league_name, home_name,
                        " ".join(home_name.casefold().split()), "home", minute,
                        seen_home, seen_away, final_home - seen_home, final_away - seen_away,
                    ),
                    (
                        fixture_id, league_name, away_name,
                        " ".join(away_name.casefold().split()), "away", minute,
                        seen_away, seen_home, final_away - seen_away, final_home - seen_home,
                    ),
                )
                for value in values:
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO live_corner_observations (
                            fixture_id, league, team, team_key, venue, minute,
                            corners_for, corners_against,
                            corners_for_after, corners_against_after
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        value,
                    )
                    inserted += max(0, cursor.rowcount)

    return {
        "finalized": True,
        "fixture_id": fixture_id,
        "snapshots_processed": snapshots_seen,
        "observations_inserted": inserted,
        "observations_already_present": max(0, snapshots_seen * 2 - inserted),
        "verified_final_corners": {"home": final_home, "away": final_away},
    }
