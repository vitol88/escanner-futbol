"""Supabase-backed durable store for canonical Football Lab predictions."""
from __future__ import annotations

from typing import Any
import requests

from ai_engine.prediction_schema import normalize_prediction_record


def append_supabase_prediction_records(
    records: list[dict[str, Any]], supabase_url: str, secret_key: str,
    *, post=None, timeout: float = 12.0,
) -> dict[str, int]:
    """Insert valid predictions idempotently; prediction_id is the remote PK."""
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan credenciales de Supabase.")
    normalized = [
        normalize_prediction_record(row)
        for row in (records if isinstance(records, list) else [])
        if isinstance(row, dict)
    ]
    valid = [row for row in normalized if row["valid"]]
    payload = [{
        "prediction_id": row["prediction_id"],
        "fixture_id": row["fixture_id"],
        "recorded_at": row["recorded_at"],
        "record_json": row,
    } for row in valid]
    if not payload:
        return {"received": len(normalized), "valid": 0,
                "invalid": len(normalized), "inserted": 0,
                "duplicates": 0}
    sender = post or requests.post
    response = sender(
        f"{url}/rest/v1/prediction_ledger",
        params={"on_conflict": "prediction_id"},
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=representation",
        },
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    created = response.json()
    inserted = len(created) if isinstance(created, list) else 0
    return {
        "received": len(normalized),
        "valid": len(valid),
        "invalid": len(normalized) - len(valid),
        "inserted": inserted,
        "duplicates": len(valid) - inserted,
    }


def load_supabase_prediction_records(
    supabase_url: str, secret_key: str, *, get=None, timeout: float = 12.0,
) -> list[dict[str, Any]]:
    """Read all ledger pages in stable chronological order."""
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan credenciales de Supabase.")
    reader = get or requests.get
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows: list[dict[str, Any]] = []
    start = 0
    page_size = 500
    while True:
        response = reader(
            f"{url}/rest/v1/prediction_ledger",
            params={"select": "record_json", "order": "recorded_at.asc,prediction_id.asc"},
            headers={**headers, "Range-Unit": "items",
                     "Range": f"{start}-{start + page_size - 1}"},
            timeout=timeout,
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError("Respuesta inesperada al leer prediction_ledger.")
        rows.extend(
            item["record_json"] for item in page
            if isinstance(item, dict) and isinstance(item.get("record_json"), dict)
        )
        if len(page) < page_size:
            break
        start += page_size
    return rows
