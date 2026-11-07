from ai_engine.telegram_publisher import format_signal_message, send_telegram_signal


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {"ok": True}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_format_signal_message_includes_match_market_and_probability():
    message = format_signal_message({
        "home": "América", "away": "Cali", "score_home": 1, "score_away": 0,
        "minute": 67, "market": "Más de 1.5 goles", "probability": 0.82,
        "verified_live_odd": 1.55, "verified_bookmaker": "Casa A",
        "verified_odds_market": "Más de 1.5 goles", "estimated_edge": 0.04,
    })
    assert "América vs Cali" in message
    assert "Marcador: 1-0" in message
    assert "Minuto: 67'" in message
    assert "Más de 1.5 goles" in message
    assert "82.0%" in message
    assert "Cuota real: 1.55" in message
    assert "Casa A" in message
    assert "Ventaja estimada" in message


def test_send_telegram_signal_uses_chat_id_and_does_not_leak_token():
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    ok, detail = send_telegram_signal(
        {"home": "A", "away": "B", "market": "Empate", "verified_live_odd": 1.50,
         "verified_bookmaker": "Casa A", "verified_odds_market": "Empate final", "estimated_edge": 0.03},
        "secret-token", "-1004668474905", post=fake_post,
    )
    assert ok is True
    assert "secret-token" not in detail
    assert calls[0][0].endswith("/botsecret-token/sendMessage")
    assert calls[0][1]["json"]["chat_id"] == "-1004668474905"


def test_send_telegram_signal_handles_api_rejection_without_leaking_token():
    def fake_post(url, **kwargs):
        return FakeResponse({"ok": False, "description": "Unauthorized"})

    ok, detail = send_telegram_signal(
        {"home": "A", "away": "B"}, "secret-token", "-1004668474905", post=fake_post,
    )
    assert ok is False
    assert "secret-token" not in detail


def test_send_telegram_signal_rejects_missing_or_out_of_band_odds():
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    ok, detail = send_telegram_signal(
        {"home": "A", "away": "B", "market": "Empate"},
        "secret-token", "-1004668474905", post=fake_post,
    )
    assert ok is False
    assert "cuota real" in detail
    assert calls == []
