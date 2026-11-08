from ai_engine.telegram_store import build_alert_key, reserve_telegram_alert, update_telegram_alert


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else []

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def sample_row():
    return {
        "fixture_id": 12345,
        "verified_odds_market": "Más de 1.5 goles",
        "verified_bookmaker": "Casa A",
        "verified_live_odd": 1.55,
        "minute": 67,
        "score_home": 1,
        "score_away": 0,
    }


def test_alert_key_is_stable_for_fixture_and_market():
    row = sample_row()
    assert build_alert_key(row) == build_alert_key(dict(row))
    changed = {**row, "minute": 80, "verified_live_odd": 1.70}
    assert build_alert_key(row) == build_alert_key(changed)
    other_market = {**row, "verified_odds_market": "Empate final"}
    assert build_alert_key(row) != build_alert_key(other_market)


def test_reserve_alert_returns_key_when_inserted():
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse([{"alert_key": "abc"}])
    reserved, key, detail = reserve_telegram_alert(sample_row(), "https://example.supabase.co", "secret", post=fake_post)
    assert reserved is True
    assert key == build_alert_key(sample_row())
    assert calls[0][1]["headers"]["Prefer"] == "resolution=ignore-duplicates,return=representation"
    assert calls[0][1]["json"]["status"] == "reserved"


def test_reserve_alert_blocks_duplicate():
    reserved, key, detail = reserve_telegram_alert(
        sample_row(), "https://example.supabase.co", "secret",
        post=lambda *a, **k: FakeResponse([]),
        patch=lambda *a, **k: FakeResponse([]),
    )
    assert reserved is False
    assert key == build_alert_key(sample_row())
    assert "duplicada" in detail


def test_failed_alert_can_be_reserved_for_retry():
    patch_calls = []
    def fake_patch(url, **kwargs):
        patch_calls.append((url, kwargs))
        return FakeResponse([{"alert_key": build_alert_key(sample_row()), "status": "reserved"}])

    reserved, key, detail = reserve_telegram_alert(
        sample_row(), "https://example.supabase.co", "secret",
        post=lambda *a, **k: FakeResponse([]),
        patch=fake_patch,
    )
    assert reserved is True
    assert key == build_alert_key(sample_row())
    assert "reintento" in detail
    assert patch_calls[0][1]["params"]["status"] == "eq.failed"
    assert patch_calls[0][1]["json"]["status"] == "reserved"
    assert patch_calls[0][1]["json"]["error"] is None


def test_sent_alert_cannot_be_retried():
    patch_calls = []
    def fake_patch(url, **kwargs):
        patch_calls.append(kwargs)
        return FakeResponse([])

    reserved, key, detail = reserve_telegram_alert(
        sample_row(), "https://example.supabase.co", "secret",
        post=lambda *a, **k: FakeResponse([]),
        patch=fake_patch,
    )
    assert reserved is False
    assert key == build_alert_key(sample_row())
    assert "duplicada" in detail
    assert patch_calls[0]["params"]["status"] == "eq.failed"


def test_update_alert_marks_sent():
    calls = []
    def fake_patch(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse([])
    assert update_telegram_alert("abc", "sent", "https://example.supabase.co", "secret", patch=fake_patch)
    assert calls[0][1]["json"]["status"] == "sent"
    sent_at = calls[0][1]["json"]["sent_at"]
    assert isinstance(sent_at, str) and sent_at.endswith("+00:00")
