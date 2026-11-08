"""Supabase-backed idempotency store for Telegram alerts."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
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
    patch=None,
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

        # A failed delivery may be retried, but sent/reserved alerts remain locked.
        # The status filter makes the transition atomic: only the first retry can
        # change failed -> reserved, preventing two concurrent publishers.
        updater = patch or requests.patch
        retry_payload = {
            **payload,
            "status": "reserved",
            "error": None,
            "sent_at": None,
        }
        retry_response = updater(
            f"{url}/rest/v1/telegram_alerts",
            params={"alert_key": f"eq.{alert_key}", "status": "eq.failed"},
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=retry_payload,
            timeout=timeout,
        )
        retry_response.raise_for_status()
        retried = retry_response.json()
        if isinstance(retried, list) and retried:
            return True, alert_key, "Alerta fallida reservada para reintento."
        return False, alert_key, "Alerta duplicada: ya existe o está en proceso de envío en Supabase."
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
        payload["sent_at"] = datetime.now(timezone.utc).isoformat()
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


def check_supabase_connection(supabase_url: str, secret_key: str, *, get=None, timeout: float = 8.0) -> tuple[bool, str]:
    """Read-only connectivity check against the alert table; never sends Telegram."""
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        return False, "Faltan SUPABASE_URL o SUPABASE_SECRET_KEY."
    reader = get or requests.get
    try:
        response = reader(
            f"{url}/rest/v1/telegram_alerts",
            params={"select": "alert_key", "limit": "1"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        return True, "Conexión correcta. Supabase respondió y la tabla telegram_alerts es accesible."
    except Exception as exc:
        return False, f"No se pudo verificar Supabase ({type(exc).__name__})."

def test_supabase_duplicate_protection(supabase_url: str, secret_key: str) -> tuple[bool, str]:
    """Insert one synthetic row, verify duplicate rejection, then remove the test row."""
    test_row = {
        "fixture_id": "FOOTBALL_LAB_SUPABASE_SELF_TEST",
        "verified_odds_market": "SELF_TEST_ONLY_DO_NOT_PUBLISH",
        "verified_bookmaker": "SELF_TEST",
        "verified_live_odd": 1.5,
        "minute": 0,
        "score_home": 0,
        "score_away": 0,
    }
    reserved, alert_key, detail = reserve_telegram_alert(test_row, supabase_url, secret_key)
    if not reserved:
        return False, f"No se pudo crear el registro temporal: {detail}"
    duplicate_reserved, duplicate_key, duplicate_detail = reserve_telegram_alert(
        test_row, supabase_url, secret_key
    )
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    deleted = False
    try:
        response = requests.delete(
            f"{url}/rest/v1/telegram_alerts",
            params={"alert_key": f"eq.{alert_key}"},
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "return=minimal",
            },
            timeout=8.0,
        )
        response.raise_for_status()
        deleted = True
    except Exception:
        deleted = False
    if duplicate_reserved or duplicate_key != alert_key:
        return False, "La segunda reserva no fue bloqueada como duplicado. " + (
            "El registro temporal se eliminó." if deleted else "No se pudo confirmar la eliminación del registro temporal."
        )
    if not deleted:
        return False, "La protección contra duplicados funcionó, pero no se pudo eliminar el registro temporal. Elimínalo manualmente después."
    return True, "Prueba correcta: la primera reserva se creó, la segunda fue bloqueada y el registro temporal se eliminó."
