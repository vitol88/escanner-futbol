"""Append-only Supabase storage for raw Football Lab analysis snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

import requests


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))
    except (TypeError, ValueError):
        return str(value)


def build_analysis_snapshot(
    *, fixture_id: Any, analysis_type: str, match: dict[str, Any],
    inputs: dict[str, Any], outputs: dict[str, Any],
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an idempotent five-minute snapshot; never invent missing fields."""
    if fixture_id in (None, ""):
        raise ValueError("El snapshot necesita fixture_id.")
    kind = str(analysis_type or "").strip().lower()
    if kind not in {"goals", "corners", "h2h"}:
        raise ValueError("Tipo de análisis no reconocido.")
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    minute = match.get("minute")
    bucket = int(now.timestamp() // 300)
    identity = {
        "fixture_id": str(fixture_id), "analysis_type": kind,
        "minute": minute, "home_score": match.get("home_score"),
        "away_score": match.get("away_score"), "time_bucket": bucket,
    }
    snapshot_id = sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    payload = {
        "snapshot_id": snapshot_id,
        "schema_version": "1.0",
        "fixture_id": str(fixture_id),
        "analysis_type": kind,
        "recorded_at": now.isoformat(),
        "match": _json_safe(match),
        "inputs": _json_safe(inputs),
        "outputs": _json_safe(outputs),
    }
    return payload


def append_supabase_analysis_snapshots(
    snapshots: list[dict[str, Any]], supabase_url: str, secret_key: str,
    *, post=None, timeout: float = 12.0,
) -> dict[str, int]:
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan credenciales de Supabase.")
    rows = [row for row in snapshots if isinstance(row, dict) and row.get("snapshot_id") and row.get("fixture_id")]
    payload = [{
        "snapshot_id": str(row["snapshot_id"]),
        "fixture_id": str(row["fixture_id"]),
        "recorded_at": str(row["recorded_at"]),
        "analysis_type": str(row["analysis_type"]),
        "snapshot_json": row,
    } for row in rows]
    if not payload:
        return {"received": len(snapshots), "inserted": 0, "duplicates": 0}
    sender = post or requests.post
    response = sender(
        f"{url}/rest/v1/analysis_snapshots",
        params={"on_conflict": "snapshot_id"},
        headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=representation",
        },
        json=payload, timeout=timeout,
    )
    response.raise_for_status()
    created = response.json()
    inserted = len(created) if isinstance(created, list) else 0
    return {"received": len(snapshots), "inserted": inserted, "duplicates": len(payload) - inserted}


def load_supabase_analysis_snapshots(
    supabase_url: str, secret_key: str, *, get=None, timeout: float = 12.0,
) -> list[dict[str, Any]]:
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan credenciales de Supabase.")
    reader = get or requests.get
    rows: list[dict[str, Any]] = []
    start, page_size = 0, 500
    while True:
        response = reader(
            f"{url}/rest/v1/analysis_snapshots",
            params={"select": "snapshot_json", "order": "recorded_at.asc,snapshot_id.asc"},
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Range-Unit": "items", "Range": f"{start}-{start + page_size - 1}"},
            timeout=timeout,
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError("Respuesta inesperada al leer analysis_snapshots.")
        rows.extend(item["snapshot_json"] for item in page
                    if isinstance(item, dict) and isinstance(item.get("snapshot_json"), dict))
        if len(page) < page_size:
            break
        start += page_size
    return rows
