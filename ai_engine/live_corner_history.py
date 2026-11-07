"""Validated loader for minute-level live-corner history datasets.

The loader never derives probabilities or fetches data. It accepts completed-match
snapshots where the remaining corner counts are explicitly known.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = (
    "fixture_id", "league", "team", "venue", "minute",
    "corners_for", "corners_against",
    "corners_for_after", "corners_against_after",
)


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def load_live_corner_history_csv(path: str | Path) -> dict[str, Any]:
    """Load validated minute-level observations from a CSV file.

    Each row represents one team's perspective in one completed fixture at an
    exact minute. The *_after fields are additional corners after that cutoff,
    not final totals. Duplicate fixture/team/venue/minute snapshots are ignored.
    """
    source = Path(path)
    report: dict[str, Any] = {
        "available": False,
        "path": str(source),
        "rows": [],
        "received": 0,
        "valid": 0,
        "invalid": 0,
        "duplicates": 0,
        "reason": None,
    }
    if not source.is_file():
        report["reason"] = "No existe el archivo de histórico minuto a minuto."
        return report

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int]] = set()
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            missing = [column for column in REQUIRED_COLUMNS if column not in headers]
            if missing:
                report["reason"] = "Faltan columnas obligatorias: " + ", ".join(missing)
                return report

            for raw in reader:
                report["received"] += 1
                fixture_id = _text(raw.get("fixture_id"))
                league = _text(raw.get("league"))
                team = _text(raw.get("team"))
                venue = _text(raw.get("venue")).casefold()
                venue = {"local": "home", "visitante": "away"}.get(venue, venue)
                numeric = {
                    key: _nonnegative_int(raw.get(key))
                    for key in REQUIRED_COLUMNS[4:]
                }
                minute = numeric["minute"]
                if (
                    not fixture_id or not league or not team
                    or venue not in {"home", "away"}
                    or minute is None or minute < 1 or minute > 120
                    or any(value is None for value in numeric.values())
                ):
                    report["invalid"] += 1
                    continue

                identity = (fixture_id, team.casefold(), venue, minute)
                if identity in seen:
                    report["duplicates"] += 1
                    continue
                seen.add(identity)
                rows.append({
                    "fixture_id": fixture_id,
                    "league": league,
                    "team": team,
                    "venue": venue,
                    **numeric,
                })
    except (OSError, UnicodeError, csv.Error) as exc:
        report["reason"] = f"No se pudo leer el histórico: {exc}"
        return report

    report["rows"] = rows
    report["valid"] = len(rows)
    report["available"] = bool(rows)
    if not rows:
        report["reason"] = "El archivo no contiene observaciones válidas."
    return report
