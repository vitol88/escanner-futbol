from __future__ import annotations

import sqlite3

import pytest

from ai_engine.prediction_ledger import append_prediction_records, load_prediction_records
from ai_engine.outcome_ledger import load_verified_outcomes, record_verified_outcome


def _db(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    append_prediction_records(path, [{
        "fixture_id": "123", "market": "Over 2.5 goals",
        "recorded_at": "2026-11-07T12:00:00Z", "probability": 0.7,
        "selection": "Over 2.5", "model_id": "test",
    }])
    return path, load_prediction_records(path)[0]["prediction_id"]


def test_verified_outcome_is_separate_and_does_not_mutate_forecast(tmp_path):
    path, prediction_id = _db(tmp_path)
    result = record_verified_outcome(
        path, prediction_id, 1, source="API-Football final score",
        verified_by="manual_review", verified_at="2026-11-07T13:00:00Z",
    )
    assert result["inserted"] is True
    assert load_verified_outcomes(path)[prediction_id]["outcome"] == 1
    forecast = load_prediction_records(path)[0]
    assert forecast["outcome"] is None
    assert forecast["outcome_verified"] is False


def test_duplicate_verification_is_idempotent(tmp_path):
    path, prediction_id = _db(tmp_path)
    kwargs = dict(source="official result", verified_by="reviewer",
                  verified_at="2026-11-07T13:00:00Z")
    first = record_verified_outcome(path, prediction_id, 0, **kwargs)
    second = record_verified_outcome(path, prediction_id, 0, **kwargs)
    assert first["inserted"] is True
    assert second["duplicate"] is True
    assert len(load_verified_outcomes(path)) == 1


def test_conflicting_result_requires_a_correction_reason(tmp_path):
    path, prediction_id = _db(tmp_path)
    kwargs = dict(source="official result", verified_by="reviewer",
                  verified_at="2026-11-07T13:00:00Z")
    record_verified_outcome(path, prediction_id, 0, **kwargs)
    with pytest.raises(ValueError, match="corrección"):
        record_verified_outcome(path, prediction_id, 1, **kwargs)
    corrected = record_verified_outcome(
        path, prediction_id, 1, correction_reason="Se corrigió el acta oficial",
        source="corrected official result", verified_by="reviewer",
        verified_at="2026-11-07T14:00:00Z",
    )
    assert corrected["inserted"] is True
    assert load_verified_outcomes(path)[prediction_id]["outcome"] == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM prediction_outcome_events WHERE prediction_id = ?",
            (prediction_id,),
        ).fetchone()[0] == 2


@pytest.mark.parametrize("bad", [True, -1, 2, "1", None])
def test_only_explicit_binary_integer_outcomes_are_accepted(tmp_path, bad):
    path, prediction_id = _db(tmp_path)
    with pytest.raises(ValueError):
        record_verified_outcome(
            path, prediction_id, bad, source="official", verified_by="reviewer"
        )


def test_unknown_prediction_and_missing_verification_source_are_rejected(tmp_path):
    path, _ = _db(tmp_path)
    with pytest.raises(KeyError):
        record_verified_outcome(path, "missing", 1, source="official", verified_by="reviewer")
    _, prediction_id = _db(tmp_path)
    with pytest.raises(ValueError):
        record_verified_outcome(path, prediction_id, 1, source="", verified_by="reviewer")
