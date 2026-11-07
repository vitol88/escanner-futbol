"""Safe Telegram publishing for newly recorded Football Lab signals."""
from __future__ import annotations

from typing import Any, Callable

import requests


TELEGRAM_API_BASE = "https://api.telegram.org"


def format_signal_message(row: dict[str, Any]) -> str:
    """Create a concise plain-text message from one recorded live signal."""
    home = str(row.get("home") or "Local")
    away = str(row.get("away") or "Visitante")
    market = str(row.get("market") or "Señal")
    minute = row.get("minute")
    score_home = row.get("score_home")
    score_away = row.get("score_away")
    probability = row.get("probability")

    score = ""
    if score_home is not None and score_away is not None:
        score = f"Marcador: {score_home}-{score_away}\n"
    minute_text = f"Minuto: {minute}'\n" if minute is not None else ""
    probability_text = ""
    try:
        probability_text = f"Probabilidad exploratoria: {float(probability) * 100:.1f}%\n"
    except (TypeError, ValueError):
        pass

    return (
        "⚽ FOOTBALL LAB · SEÑAL EN VIVO\n\n"
        f"{home} vs {away}\n"
        f"{score}{minute_text}"
        f"Mercado: {market}\n"
        f"{probability_text}\n"
        "Análisis informativo; verifica las cuotas y el contexto antes de decidir."
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
