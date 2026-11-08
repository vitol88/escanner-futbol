"""Supabase-backed idempotency store for Telegram alerts."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import requests


def build_alert_key(row: dict[str, Any]) -> str:
    """One alert per fixture and normalized verified market."""
    fixture_id = str(row.get("fixture_id") or "").strip()
    market = " ".join(str(row.get("verified_odds_market") or "").casefold().split())
    if not fixture_id or not market:
        return ""
    raw = f"{fixture_id}|{market}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reserve_telegram_alert(
    row: dict[str, Any],
    supabase_url: str,
    secret_key: str,
    *,
    post=None,
    timeout: float = 8.0,
) -> tuple[bool, str, str]:
    """Atomically reserve an alert; unique primary key blocks concurrent duplicates."""
    alert_key = build_alert_key(row)
    if not alert_key:
        return False, "", "Falta fixture_id o mercado verificado."
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        return False, "", "Faltan credenciales de Supabase."
    sender = post or requests.post
    payload = {
        "alert_key": alert_key,
        "fixture_id": str(row.get("fixture_id")),
        "market": str(row.get("verified_odds_market")),
        "bookmaker": str(row.get("verified_bookmaker") or ""),
        "odds": row.get("verified_live_odd"),
        "match_minute": row.get("minute"),
        "score": (
            f"{row.get('score_home')}-{row.get('score_away')}"
            if row.get("score_home") is not None and row.get("score_away") is not None
            else None
        ),
        "status": "reserved",
        "message": "",
    }
    try:
        response = sender(
            f"{url}/rest/v1/telegram_alerts",
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
        if isinstance(created, list) and created:
            return True, alert_key, "Alerta reservada."
        return False, alert_key, "Alerta duplicada: ya existe en Supabase."
    except Exception as exc:
        return False, "", f"No se pudo reservar alerta ({type(exc).__name__})."


def update_telegram_alert(
    alert_key: str,
    status: str,
    supabase_url: str,
    secret_key: str,
    *,
    error: str = "",
    patch=None,
    timeout: float = 8.0,
) -> bool:
    """Update the delivery result without exposing credentials."""
    if not alert_key or status not in {"sent", "failed"}:
        return False
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        return False
    updater = patch or requests.patch
    payload = {"status": status, "error": error[:500] or None}
    if status == "sent":
        payload["sent_at"] = "now()"
    try:
        response = updater(
            f"{url}/rest/v1/telegram_alerts",
            params={"alert_key": f"eq.{alert_key}"},
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except Exception:
        return False
