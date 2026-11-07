"""Shared, provider-neutral data contract for Football Lab AI.

This module is deliberately side-effect free: it does not call the API, read
Streamlit session state, or change the existing application UI. The current
scanner can adopt the normalized snapshot incrementally.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable


SCHEMA_VERSION = "1.0"

_STAT_ALIASES = {
    "corner kicks": "corners",
    "total shots": "shots_total",
    "shots on goal": "shots_on_target",
    "shots on target": "shots_on_target",
    "shots off goal": "shots_off_target",
    "shots off target": "shots_off_target",
    "ball possession": "possession",
    "yellow cards": "yellow_cards",
    "red cards": "red_cards",
    "fouls": "fouls",
    "offsides": "offsides",
    "passes": "passes",
    "passes accurate": "passes_accurate",
    "total passes": "passes",
    "blocked shots": "shots_blocked",
    "shots insidebox": "shots_inside_box",
    "shots inside box": "shots_inside_box",
    "shots outsidebox": "shots_outside_box",
    "shots outside box": "shots_outside_box",
    "goalkeeper saves": "saves",
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number


def _normalized_name(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", raw.casefold()).strip()


def _stat_key(value: Any) -> str:
    normalized = _normalized_name(value)
    if normalized in _STAT_ALIASES:
        return _STAT_ALIASES[normalized]
    return normalized.replace(" ", "_") or "unknown"


def _stat_value(value: Any) -> tuple[int | float | None, str | None]:
    """Return a numeric value and unit without turning missing data into zero."""
    if isinstance(value, bool) or value is None:
        return None, None
    if isinstance(value, (int, float)):
        return (value if math.isfinite(float(value)) else None), None
    raw = str(value).strip()
    if not raw or raw.casefold() in {"null", "none", "n/a", "nd", "-"}:
        return None, None
    unit = "percent" if raw.endswith("%") else None
    candidate = raw[:-1].strip() if unit else raw
    candidate = candidate.replace(",", ".")
    try:
        number = float(candidate)
    except (TypeError, ValueError, OverflowError):
        return None, unit
    if not math.isfinite(number):
        return None, unit
    if number.is_integer():
        return int(number), unit
    return number, unit


def normalize_fixture(fixture: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize one API-Football fixture while preserving unavailable fields."""
    fixture = fixture if isinstance(fixture, dict) else {}
    fixture_info = fixture.get("fixture") or {}
    league_info = fixture.get("league") or {}
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = fixture.get("goals") or {}
    score = fixture.get("score") or {}
    status = fixture_info.get("status") or {}

    return {
        "fixture_id": fixture_info.get("id"),
        "date": _text(fixture_info.get("date")),
        "timestamp": _integer(fixture_info.get("timestamp")),
        "status": {
            "short": _text(status.get("short")),
            "long": _text(status.get("long")),
            "elapsed": _integer(status.get("elapsed")),
        },
        "league": {
            "id": league_info.get("id"),
            "name": _text(league_info.get("name")),
            "country": _text(league_info.get("country")),
            "season": league_info.get("season"),
            "round": _text(league_info.get("round")),\n            "referee": _text(fixture_info.get("referee")),
        },
        "teams": {
            "home": {"id": home.get("id"), "name": _text(home.get("name"))},
            "away": {"id": away.get("id"), "name": _text(away.get("name"))},
        },
        "goals": {
            "home": _integer(goals.get("home")),
            "away": _integer(goals.get("away")),
        },
        "halftime_score": {
            "home": _integer((score.get("halftime") or {}).get("home")),
            "away": _integer((score.get("halftime") or {}).get("away")),
        },
    }


def normalize_statistics(
    response: Any,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map API-Football statistics to home/away by team ID, not row order."""
    normalized_fixture = normalize_fixture(fixture)
    expected = normalized_fixture["teams"]
    expected_ids = {
        "home": expected["home"].get("id"),
        "away": expected["away"].get("id"),
    }
    expected_names = {
        "home": _normalized_name(expected["home"].get("name")),
        "away": _normalized_name(expected["away"].get("name")),
    }
    result: dict[str, Any] = {
        "available": False,
        "home": {"team_id": expected_ids["home"], "team_name": expected["home"]["name"], "values": {}},
        "away": {"team_id": expected_ids["away"], "team_name": expected["away"]["name"], "values": {}},
        "missing_teams": ["home", "away"],
        "stat_count": 0,
    }
    if isinstance(response, dict):
        response = response.get("response", [])
    if not isinstance(response, list):
        return result

    found: set[str] = set()
    for index, team_row in enumerate(response):
        if not isinstance(team_row, dict):
            continue
        team_info = team_row.get("team") or {}
        team_id = team_info.get("id")
        team_name = _text(team_info.get("name"))
        side = None
        for candidate in ("home", "away"):
            if expected_ids[candidate] is not None and team_id == expected_ids[candidate]:
                side = candidate
                break
        if side is None and team_name:
            row_name = _normalized_name(team_name)
            for candidate in ("home", "away"):
                if expected_names[candidate] and row_name == expected_names[candidate]:
                    side = candidate
                    break
        # Positional fallback is only used when provider team identity is absent.
        if side is None and team_id is None and not team_name and index in (0, 1):
            side = ("home", "away")[index]
        if side is None or side in found:
            continue

        values = {}
        stat_rows = team_row.get("statistics") or []
        if isinstance(stat_rows, list):
            for stat in stat_rows:
                if not isinstance(stat, dict):
                    continue
                original_name = _text(stat.get("type"))
                if not original_name:
                    continue
                key = _stat_key(original_name)
                numeric, unit = _stat_value(stat.get("value"))
                values[key] = {
                    "value": numeric,
                    "raw": stat.get("value"),
                    "unit": unit,
                    "source_name": original_name,
                }
        result[side] = {
            "team_id": team_id if team_id is not None else expected_ids[side],
            "team_name": team_name or expected[side]["name"],
            "values": values,
        }
        found.add(side)

    result["missing_teams"] = [side for side in ("home", "away") if side not in found]
    result["available"] = bool(found)
    result["stat_count"] = sum(len(result[side]["values"]) for side in ("home", "away"))
    return result


def build_match_snapshot(
    fixture: dict[str, Any],
    statistics: Any = None,
    *,
    events: Any = None,
    odds: Any = None,
    source: str = "api-football",
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Build the versioned match payload consumed by future AI model modules."""
    normalized_fixture = normalize_fixture(fixture)
    normalized_stats = normalize_statistics(statistics, fixture)
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "fetched_at": fetched_at,
        "match": normalized_fixture,
        "statistics": normalized_stats,
        "events": events if isinstance(events, list) else [],
        "odds": odds if isinstance(odds, (list, dict)) else {},
        "data_quality": {
            "fixture_id_available": normalized_fixture["fixture_id"] is not None,
            "team_names_available": all(
                normalized_fixture["teams"][side]["name"] for side in ("home", "away")
            ),
            "statistics_available": normalized_stats["available"],
            "statistics_missing_teams": list(normalized_stats["missing_teams"]),
            "statistics_count": normalized_stats["stat_count"],
        },
    }


def cache_key(resource: str, **identifiers: Any) -> str:
    """Create deterministic namespaced keys for shared data caches."""
    clean_resource = _normalized_name(resource).replace(" ", "_")
    parts = [f"{key}={identifiers[key]}" for key in sorted(identifiers) if identifiers[key] is not None]
    return ":".join([clean_resource or "resource", *parts])


class FootballDataEngine:
    """Small adapter around the app's existing api_get function and cache.

    The adapter is opt-in. It never creates a network client and never performs
    requests on import, so the current Streamlit flow remains unchanged until
    the app explicitly adopts it.
    """

    def __init__(
        self,
        api_get: Callable[..., dict[str, Any]],
        cache: dict[str, Any] | None = None,
    ) -> None:
        if not callable(api_get):
            raise TypeError("api_get debe ser una función invocable.")
        self._api_get = api_get
        self._cache = cache if cache is not None else {}

    def get_fixture_statistics(self, fixture_id: int | str) -> list[dict[str, Any]]:
        if fixture_id is None or str(fixture_id).strip() == "":
            raise ValueError("fixture_id es obligatorio.")
        key = cache_key("fixture_statistics", fixture=fixture_id)
        if key not in self._cache:
            # Reuse the legacy Streamlit stats_cache entry when this adapter is
            # introduced into the existing scanner; do not request the same
            # fixture statistics a second time.
            legacy_key = str(fixture_id)
            if legacy_key in self._cache and isinstance(self._cache[legacy_key], list):
                self._cache[key] = self._cache[legacy_key]
            elif fixture_id in self._cache and isinstance(self._cache[fixture_id], list):
                self._cache[key] = self._cache[fixture_id]
            else:
                payload = self._api_get("fixtures/statistics", {"fixture": fixture_id})
                response = payload.get("response", []) if isinstance(payload, dict) else []
                self._cache[key] = response if isinstance(response, list) else []
        return self._cache[key]

    def get_fixture_events(self, fixture_id: int | str) -> list[dict[str, Any]]:
        if fixture_id is None or str(fixture_id).strip() == "":
            raise ValueError("fixture_id es obligatorio.")
        key = cache_key("fixture_events", fixture=fixture_id)
        if key not in self._cache:
            payload = self._api_get("fixtures/events", {"fixture": fixture_id})
            response = payload.get("response", []) if isinstance(payload, dict) else []
            self._cache[key] = response if isinstance(response, list) else []
        return self._cache[key]

    def snapshot(
        self,
        fixture: dict[str, Any],
        *,
        statistics: Any = None,
        events: Any = None,
        odds: Any = None,
    ) -> dict[str, Any]:
        return build_match_snapshot(
            fixture,
            statistics,
            events=events,
            odds=odds,
        )
