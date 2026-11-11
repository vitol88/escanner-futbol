"""Safe Telegram publishing for newly recorded Football Lab signals."""
from __future__ import annotations

from typing import Any, Callable

import requests


TELEGRAM_API_BASE = "https://api.telegram.org"


def format_signal_message(row: dict[str, Any]) -> str:
    """Create a clear Telegram alert with the verified odds prominently displayed."""
    home = str(row.get("home") or "Local")
    away = str(row.get("away") or "Visitante")
    market = str(row.get("market") or "Señal")
    minute = row.get("minute")
    score_home = row.get("score_home")
    score_away = row.get("score_away")
    probability = row.get("probability")
    live_odd = row.get("verified_live_odd")
    bookmaker = str(row.get("verified_bookmaker") or "")
    bookmaker_verified = row.get("bookmaker_verified") is True
    odds_source = str(row.get("odds_source") or "API-Football LIVE")
    edge = row.get("estimated_edge")

    score = ""
    if score_home is not None and score_away is not None:
        score = f"Marcador: {score_home}-{score_away}\n"
    minute_text = f"Minuto: {minute}'\n" if minute is not None else ""

    if bookmaker_verified:
        odds_origin = f"Casa: {bookmaker}"
    else:
        odds_origin = f"Fuente: {odds_source} · casa no especificada"
    odds_text = f"CUOTA: {float(live_odd):.2f} · {odds_origin}\n"
    risk_mode = "MODO SEGURO" if 1.35 <= float(live_odd) <= 1.60 else "MODO ARRIESGADO"

    analysis_parts = []
    try:
        analysis_parts.append(f"Probabilidad estimada: {float(probability) * 100:.1f}%")
    except (TypeError, ValueError):
        pass
    if isinstance(edge, (int, float)):
        analysis_parts.append(f"Ventaja estimada: {float(edge) * 100:.1f}%")
    analysis_text = "\n".join(analysis_parts)

    return (
        "⚽ FOOTBALL LAB · SEÑAL EN VIVO\n\n"
        f"{home} vs {away}\n"
        f"{score}{minute_text}"
        f"Mercado: {market}\n"
        f"{risk_mode}\n"
        f"{odds_text}\n"
        f"ANÁLISIS\n{analysis_text}\n\n"
        "Verifica que la cuota siga vigente antes de decidir."
    )


def send_telegram_signal(
    row: dict[str, Any],
    bot_token: str,
    chat_id: str,
    *,
    post: Callable[..., Any] | None = None,
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """Send one signal without exposing credentials in returned diagnostics."""
    token = str(bot_token or "").strip()
    destination = str(chat_id or "").strip()
    if not token:
        return False, "Falta configurar TELEGRAM_BOT_TOKEN."
    if not destination:
        return False, "Falta configurar TELEGRAM_CHAT_ID."
    odd = row.get("verified_live_odd")
    edge = row.get("estimated_edge")
    if (not isinstance(odd, (int, float)) or not row.get("verified_bookmaker")
        or not row.get("verified_odds_market") or not isinstance(edge, (int, float))
        or edge < 0.02 or not (1.35 <= float(odd) <= 1.60 or float(odd) >= 1.70)):
        return False, "Señal retenida: falta una cuota real coincidente dentro de los rangos permitidos."

    sender = post or requests.post
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    try:
        response = sender(
            url,
            json={"chat_id": destination, "text": format_signal_message(row)},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            return False, "Telegram rechazó el envío."
        return True, "Publicado en Telegram."
    except Exception as exc:
        # Do not return exception text: request errors can contain the bot token URL.
        return False, f"No se pudo publicar ({type(exc).__name__})."



def send_telegram_test_message(
    bot_token: str,
    chat_id: str,
    *,
    post: Callable[..., Any] | None = None,
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """Send a clearly labeled connectivity test; never touches Supabase or alert rows."""
    token = str(bot_token or "").strip()
    destination = str(chat_id or "").strip()
    if not token:
        return False, "Falta configurar TELEGRAM_BOT_TOKEN."
    if not destination:
        return False, "Falta configurar TELEGRAM_CHAT_ID."
    sender = post or requests.post
    try:
        response = sender(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": destination,
                "text": (
                    "🧪 PRUEBA DE CONEXIÓN · FOOTBALL LAB\\n\\n"
                    "Este es un mensaje de prueba técnica. No es una señal de apuesta "
                    "ni corresponde a un partido real.\\n\\n"
                    "Si recibes este mensaje, el bot y el canal están comunicándose correctamente."
                ),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            return False, "Telegram rechazó el mensaje de prueba."
        return True, "Mensaje de prueba enviado correctamente al canal de Telegram."
    except Exception as exc:
        return False, f"No se pudo enviar la prueba ({type(exc).__name__})."
