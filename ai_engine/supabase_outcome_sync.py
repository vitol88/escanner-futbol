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
                                   *, max_fixtures: int | None = None,
                                   get=None, post=None) -> dict[str, Any]:
    """Evaluate stored fixture IDs, fetch final API data and append changed outcomes."""
    url, key = str(supabase_url or "").strip().rstrip("/"), str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY.")
    fixture_rows: list[dict[str, Any]] = []
    start, page_size = 0, 500
    while True:
        page = _supabase_get(url, key, "analysis_snapshots",
            {"select": "fixture_id", "order": "fixture_id.asc",
             "offset": start, "limit": page_size}, get=get)
        fixture_rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    fixture_ids = list(dict.fromkeys(
        str(row.get("fixture_id")) for row in fixture_rows if row.get("fixture_id")
    ))
    if max_fixtures:
        fixture_ids = fixture_ids[:max_fixtures]

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
