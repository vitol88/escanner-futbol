"""Read-only audit of provisional and verified live-corner SQLite history."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def audit_live_corner_database(database_path: str | Path) -> dict[str, Any]:
    """Summarize history coverage and flag inconsistent paired team observations.

    The audit is read-only: it never creates tables, repairs rows, fetches data,
    or makes a claim about model accuracy or betting value.
    """
    path = Path(database_path)
    if not path.exists():
        return {
            "available": False,
            "reason": "database_not_found",
            "database_path": str(path),
            "captures": {"snapshots": 0, "fixtures": 0, "pending_fixtures": 0},
            "verified_history": {"observations": 0, "fixtures": 0, "complete_pairs": 0},
            "quality": {"incomplete_pairs": 0, "mismatched_pairs": 0},
            "by_league": [],
            "by_minute_bucket": [],
            "by_team_venue": [],
            "warnings": ["Todavía no existe una base SQLite de córners en esta ruta."],
        }

    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        has_captures = _table_exists(connection, "live_corner_capture_snapshots")
        has_history = _table_exists(connection, "live_corner_observations")
        captures = []
        observations = []
        if has_captures:
            captures = connection.execute(
                """
                SELECT fixture_id, league_name, minute
                FROM live_corner_capture_snapshots
                ORDER BY fixture_id, minute
                """
            ).fetchall()
        if has_history:
            observations = connection.execute(
                """
                SELECT fixture_id, league, team, team_key, venue, minute,
                       corners_for, corners_against,
                       corners_for_after, corners_against_after
                FROM live_corner_observations
                ORDER BY fixture_id, minute, venue
                """
            ).fetchall()

        captured_fixtures = {str(row["fixture_id"]) for row in captures}
        verified_fixtures = {str(row["fixture_id"]) for row in observations}
        pending_fixtures = captured_fixtures - verified_fixtures
        captured_minutes = {
            (str(row["fixture_id"]), int(row["minute"])) for row in captures
        }

        grouped: dict[tuple[str, int], dict[str, sqlite3.Row]] = {}
        incomplete_pairs = 0
        mismatched_pairs = 0
        team_timelines: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for row in observations:
            key = (str(row["fixture_id"]), int(row["minute"]))
            grouped.setdefault(key, {})[str(row["venue"])] = row
            timeline_key = (str(row["fixture_id"]), str(row["team_key"] if "team_key" in row.keys() else row["team"]), str(row["venue"]))
            team_timelines.setdefault(timeline_key, []).append(row)

        for pair in grouped.values():
            home = pair.get("home")
            away = pair.get("away")
            if home is None or away is None:
                incomplete_pairs += 1
                continue
            mirrored = (
                int(home["corners_for"]) == int(away["corners_against"])
                and int(home["corners_against"]) == int(away["corners_for"])
                and int(home["corners_for_after"]) == int(away["corners_against_after"])
                and int(home["corners_against_after"]) == int(away["corners_for_after"])
            )
            if not mirrored:
                mismatched_pairs += 1

        inconsistent_remaining_progression = 0
        inconsistent_final_totals = 0
        for timeline in team_timelines.values():
            ordered = sorted(timeline, key=lambda item: int(item["minute"]))
            previous_remaining = None
            expected_final_total = None
            for item in ordered:
                remaining = int(item["corners_for_after"])
                final_total = int(item["corners_for"]) + remaining
                if previous_remaining is not None and remaining > previous_remaining:
                    inconsistent_remaining_progression += 1
                if expected_final_total is None:
                    expected_final_total = final_total
                elif final_total != expected_final_total:
                    inconsistent_final_totals += 1
                previous_remaining = remaining

        league_counts: dict[str, dict[str, int]] = {}
        for row in captures:
            label = str(row["league_name"] or "Unknown league")
            item = league_counts.setdefault(label, {"snapshots": 0, "fixtures": 0})
            item["snapshots"] += 1
        capture_leagues: dict[str, set[str]] = {}
        for row in captures:
            capture_leagues.setdefault(str(row["league_name"] or "Unknown league"), set()).add(str(row["fixture_id"]))
        for label, fixture_ids in capture_leagues.items():
            league_counts[label]["fixtures"] = len(fixture_ids)

        history_leagues: dict[str, dict[str, int]] = {}
        for row in observations:
            label = str(row["league"] or "Unknown league")
            item = history_leagues.setdefault(label, {"observations": 0, "fixtures": 0})
            item["observations"] += 1
        for label, item in history_leagues.items():
            item["fixtures"] = len({
                str(row["fixture_id"]) for row in observations
                if str(row["league"] or "Unknown league") == label
            })

        bucket_counts: dict[str, int] = {}
        for row in captures:
            minute = int(row["minute"])
            start = ((minute - 1) // 15) * 15 + 1
            label = f"{start:02d}-{min(start + 14, 120):02d}"
            bucket_counts[label] = bucket_counts.get(label, 0) + 1

        team_counts: dict[tuple[str, str], set[str]] = {}
        for row in observations:
            key = (str(row["team"]), str(row["venue"]))
            team_counts.setdefault(key, set()).add(str(row["fixture_id"]))

        league_report = []
        for label in sorted(set(league_counts) | set(history_leagues), key=str.casefold):
            cap = league_counts.get(label, {"snapshots": 0, "fixtures": 0})
            hist = history_leagues.get(label, {"observations": 0, "fixtures": 0})
            league_report.append({
                "league": label,
                "capture_snapshots": cap["snapshots"],
                "capture_fixtures": cap["fixtures"],
                "verified_observations": hist["observations"],
                "verified_fixtures": hist["fixtures"],
            })

        verified_minutes = set(grouped)
        pending_snapshots = captured_minutes - verified_minutes
        orphan_observation_minutes = verified_minutes - captured_minutes

        warnings = []
        if not has_captures:
            warnings.append("No existe la tabla de capturas provisionales.")
        if not has_history:
            warnings.append("No existe la tabla de observaciones verificadas.")
        if pending_fixtures:
            warnings.append("Hay partidos capturados que todavía no tienen cierre verificado.")
        if pending_snapshots:
            warnings.append("Hay snapshots capturados sin pareja de observaciones verificadas local/visitante.")
        if orphan_observation_minutes:
            warnings.append("Hay observaciones verificadas sin snapshot de captura correspondiente.")
        if incomplete_pairs:
            warnings.append("Hay observaciones sin su pareja local/visitante.")
        if mismatched_pairs:
            warnings.append("Hay parejas local/visitante cuyos conteos no coinciden.")
        if inconsistent_remaining_progression:
            warnings.append("Hay secuencias donde los córners restantes aumentan con el avance del partido.")
        if inconsistent_final_totals:
            warnings.append("Hay secuencias cuyo total final implícito cambia entre snapshots.")
        if not observations:
            warnings.append("No hay observaciones verificadas para evaluar el modelo live.")

        return {
            "available": has_captures or has_history,
            "database_path": str(path),
            "captures": {
                "snapshots": len(captures),
                "fixtures": len(captured_fixtures),
                "pending_fixtures": len(pending_fixtures),
            },
            "verified_history": {
                "observations": len(observations),
                "fixtures": len(verified_fixtures),
                "complete_pairs": sum(
                    1 for pair in grouped.values()
                    if "home" in pair and "away" in pair
                ),
            },
            "quality": {
                "incomplete_pairs": incomplete_pairs,
                "mismatched_pairs": mismatched_pairs,
                "pending_snapshots": len(pending_snapshots),
                "orphan_observation_minutes": len(orphan_observation_minutes),
                "inconsistent_remaining_progression": inconsistent_remaining_progression,
                "inconsistent_final_totals": inconsistent_final_totals,
            },
            "by_league": league_report,
            "by_minute_bucket": [
                {"minute_bucket": label, "snapshots": bucket_counts[label]}
                for label in sorted(bucket_counts)
            ],
            "by_team_venue": [
                {"team": team, "venue": venue, "fixtures": len(fixtures)}
                for (team, venue), fixtures in sorted(
                    team_counts.items(), key=lambda item: (item[0][0].casefold(), item[0][1])
                )
            ],
            "warnings": warnings,
        }
    finally:
        connection.close()
