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
        "verified_live_odd": 1.55, "verified_bookmaker": "Casa A", "bookmaker_verified": True,
        "verified_odds_market": "Más de 1.5 goles", "estimated_edge": 0.04,
    })
    assert "América vs Cali" in message
    assert "Marcador: 1-0" in message
    assert "Minuto: 67'" in message
    assert "Más de 1.5 goles" in message
    assert "82.0%" in message
    assert "CUOTA: 1.55" in message
    assert "MODO SEGURO" in message
    assert "\\n" not in message
    assert "Casa A" in message
    assert "Ventaja estimada" in message


def test_send_telegram_signal_uses_chat_id_and_does_not_leak_token():
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    ok, detail = send_telegram_signal(
        {"home": "A", "away": "B", "market": "Empate", "verified_live_odd": 1.50,
         "verified_bookmaker": "Casa A", "bookmaker_verified": True, "verified_odds_market": "Empate final", "estimated_edge": 0.03},
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
        {"home": "A", "away": "B", "verified_live_odd": 1.50, "verified_bookmaker": "Casa A", "verified_odds_market": "Empate final", "estimated_edge": 0.03}, "secret-token", "-1004668474905", post=fake_post,
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



def test_format_signal_message_labels_high_risk_odds():
    message = format_signal_message({
        "home": "Local", "away": "Visitante", "market": "Ambos marcan",
        "verified_live_odd": 1.75, "verified_bookmaker": "Casa B", "bookmaker_verified": True,
        "verified_odds_market": "Ambos equipos marcan: Sí", "estimated_edge": 0.03,
    })
    assert "MODO ARRIESGADO" in message
    assert "CUOTA: 1.75" in message
    assert "Casa B" in message

def test_format_signal_message_does_not_claim_unknown_bookmaker():
    message = format_signal_message({
        "home": "Local", "away": "Visitante", "market": "Más de 8.5 córners",
        "verified_live_odd": 1.55,
        "verified_bookmaker": "Referencia API-Football LIVE (casa no especificada)",
        "bookmaker_verified": False,
        "odds_source": "API-Football LIVE",
        "verified_odds_market": "Más de 8.5 córners",
        "estimated_edge": 0.04,
    })
    assert "CUOTA: 1.55" in message
    assert "Fuente: API-Football LIVE" in message
    assert "casa no especificada" in message
    assert "Casa: Referencia" not in message


def test_send_telegram_signal_rejects_unidentified_bookmaker_even_with_fallback_label():
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    ok, detail = send_telegram_signal(
        {
            "home": "Local", "away": "Visitante", "market": "Menos de 2.5 goles",
            "verified_live_odd": 1.48,
            "verified_bookmaker": "Referencia API-Football LIVE (casa no especificada)",
            "bookmaker_verified": False,
            "verified_odds_market": "Menos de 2.5 goles",
            "estimated_edge": 0.163,
        },
        "secret-token", "-1004668474905", post=fake_post,
    )
    assert ok is False
    assert "cuota real" in detail
    assert calls == []
