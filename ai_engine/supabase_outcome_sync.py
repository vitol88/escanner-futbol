"""Sync finished API-Football fixtures into Supabase outcome event history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import requests

FINISHED_STATUSES = {"FT", "AET", "PEN"}


def _stat_total(statistics: list[dict[str, Any]], label: str) -> int | None:
    values = []
    for team_stats in statistics or []:
        for item in team_stats.get("statistics") or []:
            if str(item.get("type") or "").strip().casefold() == label.casefold():
                value = item.get("value")
                if value is not None:
                    try:
                        values.append(int(str(value).replace("%", "").strip()))
                    except (TypeError, ValueError):
                        pass
    return sum(values) if values else None


def build_outcome_event(fixture: dict[str, Any], statistics: list[dict[str, Any]] | None,
                        *, verified_by: str = "football-lab-api-football") -> dict[str, Any] | None:
    """Return a final-result event only for completed fixtures with a valid score."""
    info = fixture.get("fixture") or {}
    status = (info.get("status") or {}).get("short")
    goals = fixture.get("goals") or {}
    home_score, away_score = goals.get("home"), goals.get("away")
    if status not in FINISHED_STATUSES or not isinstance(home_score, int) or not isinstance(away_score, int):
        return None
    stats = statistics or []
    corners = _stat_total(stats, "Corner Kicks")
    yellow_cards = _stat_total(stats, "Yellow Cards")
    return {
        "fixture_id": str(info.get("id") or ""),
        "final_home_score": home_score,
        "final_away_score": away_score,
        "final_total_corners": corners,
        "final_total_yellow_cards": yellow_cards,
        "source": "api-football",
        "verified_by": verified_by,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "correction_reason": None,
    }


def _supabase_get(url: str, key: str, table: str, params: dict[str, Any],
                  *, get=None, timeout: float = 15.0) -> list[dict[str, Any]]:
    reader = get or requests.get
    response = reader(
        f"{url.rstrip('/')}/rest/v1/{table}",
        params=params,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"Respuesta inesperada de Supabase en {table}.")
    return payload


def sync_finished_fixture_outcomes(supabase_url: str, secret_key: str, api_get,
                                   *, max_fixtures: int | None = 100,
                                   get=None, post=None) -> dict[str, Any]:
    """Verify recent fixtures referenced by either raw snapshots or predictions.

    The bounded default protects the API-Football request budget. Newest fixture
    references are considered first; repeated references across tables collapse
    to one fixture lookup. Pass max_fixtures=None only for an intentional full scan.
    """
    url, key = str(supabase_url or "").strip().rstrip("/"), str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY.")

    fixture_ids: list[str] = []
    seen_fixture_ids: set[str] = set()
    # The canonical prediction ledger is now the source of truth for evaluated
    # candidates, including forecasts that were not promoted to Telegram signals.
    # Keep raw snapshots too, since they contain model projections for MAE reports.
    for table in ("prediction_ledger", "analysis_snapshots"):
        start, page_size = 0, 500
        while True:
            page = _supabase_get(url, key, table,
                {"select": "fixture_id", "order": "recorded_at.desc",
                 "offset": start, "limit": page_size}, get=get)
            for row in page:
                fixture_id = str(row.get("fixture_id") or "").strip()
                if fixture_id and fixture_id not in seen_fixture_ids:
                    seen_fixture_ids.add(fixture_id)
                    fixture_ids.append(fixture_id)
            if len(page) < page_size:
                break
            start += page_size
    if max_fixtures is not None:
        fixture_ids = fixture_ids[:max(0, int(max_fixtures))]

    existing_rows: list[dict[str, Any]] = []
    for offset in range(0, len(fixture_ids), 50):
        batch = fixture_ids[offset:offset + 50]
        if not batch:
            continue
        in_filter = "(" + ",".join(batch) + ")"
        existing_rows.extend(_supabase_get(url, key, "latest_match_outcomes",
            {"select": "fixture_id,final_home_score,final_away_score,final_total_corners,final_total_yellow_cards",
             "fixture_id": f"in.{in_filter}"}, get=get))
    existing = {str(row.get("fixture_id")): row for row in existing_rows}

    checked = finished = inserted = unchanged = skipped = 0
    errors: list[str] = []
    sender = post or requests.post
    for fixture_id in fixture_ids:
        checked += 1
        try:
            fixture_payload = api_get("fixtures", {"id": fixture_id})
            fixture_items = fixture_payload.get("response") or []
            if not fixture_items:
                skipped += 1
                continue
            fixture = fixture_items[0]
            status = ((fixture.get("fixture") or {}).get("status") or {}).get("short")
            if status not in FINISHED_STATUSES:
                skipped += 1
                continue
            stats_payload = api_get("fixtures/statistics", {"fixture": fixture_id})
            event = build_outcome_event(fixture, stats_payload.get("response") or [])
            if not event:
                skipped += 1
                continue
            finished += 1
            previous = existing.get(fixture_id) or {}
            # La API puede omitir estadísticas temporalmente. Nunca reemplazar
            # un dato final ya verificado por NULL; sí permitir completar NULL
            # cuando una consulta posterior devuelve el dato real.
            for stat_field in ("final_total_corners", "final_total_yellow_cards"):
                if event.get(stat_field) is None and previous.get(stat_field) is not None:
                    event[stat_field] = previous[stat_field]
            fields = ("final_home_score", "final_away_score",
                      "final_total_corners", "final_total_yellow_cards")
            if previous and all(previous.get(field) == event.get(field) for field in fields):
                unchanged += 1
                continue
            response = sender(
                f"{url}/rest/v1/match_outcome_events",
                headers={"apikey": key, "Authorization": f"Bearer {key}",
                         "Content-Type": "application/json",
                         "Prefer": "return=representation"},
                json=event, timeout=15,
            )
            response.raise_for_status()
            inserted += 1
            existing[fixture_id] = event
        except Exception as exc:
            errors.append(f"{fixture_id}: {type(exc).__name__}: {exc}")
    return {
        "fixtures_found": len(fixture_ids), "checked": checked, "finished": finished,
        "inserted": inserted, "unchanged": unchanged, "skipped": skipped,
        "errors": errors,
    }


def load_latest_match_outcomes(supabase_url: str, secret_key: str, *, get=None,
                               timeout: float = 15.0) -> dict[str, dict[str, Any]]:
    """Load verified final outcomes indexed by fixture ID for read-only settlement."""
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY.")
    reader = get or requests.get
    outcomes: dict[str, dict[str, Any]] = {}
    start, page_size = 0, 500
    while True:
        response = reader(
            f"{url}/rest/v1/latest_match_outcomes",
            params={
                "select": "fixture_id,final_home_score,final_away_score,final_total_corners,final_total_yellow_cards,source,verified_at",
                "order": "verified_at.desc",
                "offset": start,
                "limit": page_size,
            },
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError("Respuesta inesperada de latest_match_outcomes.")
        for row in page:
            if not isinstance(row, dict):
                continue
            fixture_id = str(row.get("fixture_id") or "").strip()
            if fixture_id and fixture_id not in outcomes:
                outcomes[fixture_id] = row
        if len(page) < page_size:
            break
        start += page_size
    return outcomes
