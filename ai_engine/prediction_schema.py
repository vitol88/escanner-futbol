"""Versioned, market-agnostic contract for Football Lab forecast records.

Pure helpers only: no API, filesystem, Streamlit, or betting recommendations.
Legacy scanner CSV rows remain readable; missing metadata is never fabricated.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

PREDICTION_SCHEMA_VERSION = "1.1"


def _parse_timestamp(value: Any) -> tuple[str | None, str]:
    raw = str(value or "").strip()
    if not raw:
        return None, "missing"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None, "invalid"
    if parsed.tzinfo is None:
        # Old scanner logs used datetime.now().isoformat() without an offset.
        # Preserve the original wall time rather than silently guessing a zone.
        return parsed.isoformat(timespec="seconds"), "naive_legacy"
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "aware_utc"


def _probability(row: dict[str, Any]) -> float | None:
    raw = row.get("probability")
    if raw in (None, ""):
        raw = row.get("estimated_probability_exploratory")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def _verified(value: Any) -> bool:
    return str(value or "").strip().casefold() in {
        "1", "true", "yes", "si", "sí", "verified", "verificado"
    }


def _binary(value: Any) -> int | None:
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "si", "sí"}:
        return 1
    if text in {"0", "false", "no"}:
        return 0
    return None


def normalize_prediction_record(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one new or legacy CSV row into the versioned forecast contract.

    Required fields are fixture_id, market, a parseable recorded_at, and a
    probability in [0, 1]. Optional metadata stays None/unknown when absent.
    Naive legacy timestamps are preserved and explicitly flagged, not guessed.
    """
    if not isinstance(row, dict):
        raise TypeError("prediction row debe ser un diccionario")

    timestamp, timestamp_status = _parse_timestamp(row.get("recorded_at"))
    probability = _probability(row)
    fixture_id = str(row.get("fixture_id") or "").strip() or None
    market = str(row.get("market") or "").strip() or None
    verified = _verified(row.get("outcome_verified"))
    outcome = _binary(row.get("outcome")) if verified else None

    phase = str(row.get("phase") or "").strip().casefold() or "unknown"
    if phase not in {"pre_match", "live", "unknown"}:
        phase = "unknown"

    record = {
        "schema_version": PREDICTION_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "recorded_at": timestamp,
        "timestamp_status": timestamp_status,
        "league_id": str(row.get("league_id") or "").strip() or None,
        "league": str(row.get("league") or "").strip() or None,
        "home": str(row.get("home") or "").strip() or None,
        "away": str(row.get("away") or "").strip() or None,
        "phase": phase,
        "minute": row.get("minute") if row.get("minute") not in ("",) else None,
        "score_home": row.get("score_home") if row.get("score_home") not in ("",) else None,
        "score_away": row.get("score_away") if row.get("score_away") not in ("",) else None,
        "market": market,
        "market_type": str(row.get("market_type") or "").strip() or None,
        "selection": str(row.get("selection") or "").strip() or None,
        "line": str(row.get("line") or "").strip() or None,
        "probability": probability,
        "model_id": str(row.get("model_id") or "").strip() or None,
        "model_version": str(row.get("model_version") or "").strip() or None,
        "source": str(row.get("source") or "").strip() or None,
        "snapshot_id": str(row.get("snapshot_id") or "").strip() or None,
        "odds_decimal": row.get("odds_decimal") if row.get("odds_decimal") not in ("",) else None,
        "outcome": outcome,
        "outcome_verified": verified and outcome is not None,
    }

    errors = []
    if not fixture_id:
        errors.append("missing_fixture_id")
    if not market:
        errors.append("missing_market")
    if timestamp is None:
        errors.append("invalid_or_missing_recorded_at")
    if probability is None:
        errors.append("invalid_or_missing_probability")
    record["valid"] = not errors
    record["validation_errors"] = errors

    # Stable identity for deduplication. A caller should supply snapshot_id when
    # materially different live snapshots can occur within the same minute/score.
    identity = {
        "fixture_id": fixture_id,
        "phase": phase,
        "market": market,
        "market_type": record["market_type"],
        "selection": record["selection"],
        "line": record["line"],
        "minute": record["minute"],
        "score_home": record["score_home"],
        "score_away": record["score_away"],
        "model_id": record["model_id"],
        "model_version": record["model_version"],
        "snapshot_id": record["snapshot_id"],
    }
    identity_text = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
    record["prediction_id"] = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()[:24]
    return record


def normalize_prediction_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize a dataset and report validity/duplicate counts without editing it."""
    if not isinstance(rows, list):
        rows = []
    records = [normalize_prediction_record(row) for row in rows if isinstance(row, dict)]
    seen: set[str] = set()
    duplicates = 0
    for record in records:
        if not record["valid"]:
            continue
        if record["prediction_id"] in seen:
            duplicates += 1
        else:
            seen.add(record["prediction_id"])
    return {
        "schema_version": PREDICTION_SCHEMA_VERSION,
        "row_count": len(rows),
        "normalized_count": len(records),
        "valid_count": sum(record["valid"] for record in records),
        "invalid_count": sum(not record["valid"] for record in records),
        "duplicate_count": duplicates,
        "records": records,
        "warnings": [
            "Los campos ausentes permanecen desconocidos; no se infieren mercados, líneas ni versiones.",
            "Las marcas temporales antiguas sin zona se conservan como naive_legacy y no se convierten a UTC.",
            "Para diferenciar snapshots en vivo dentro del mismo minuto y marcador, el productor debe proporcionar snapshot_id.",
            "Un resultado solo se conserva como binario si outcome_verified es explícito.",
        ],
    }
