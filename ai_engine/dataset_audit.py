"""Read-only quality audit for exported forecast datasets."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def _parse_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError, OverflowError):
        return False


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


def audit_forecast_dataset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count usable, verified, malformed and duplicate forecast records.

    This function never edits rows or infers an outcome. A forecast is structurally
    usable when fixture, market, timestamp and probability are valid. A verified
    result is counted separately only when its explicit verification flag and
    binary outcome are both valid.
    """
    if not isinstance(rows, list):
        rows = []

    seen: set[tuple[str, ...]] = set()
    duplicate_count = 0
    invalid_metadata = 0
    invalid_probability = 0
    verified_valid = 0
    verified_invalid = 0
    structurally_valid = 0
    distinct_valid = 0
    markets: set[str] = set()
    leagues: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            invalid_metadata += 1
            continue

        fixture = str(row.get("fixture_id") or "").strip()
        market = str(row.get("market") or "").strip()
        timestamp = row.get("recorded_at")
        metadata_ok = bool(fixture and market and _parse_timestamp(timestamp))
        if not metadata_ok:
            invalid_metadata += 1

        try:
            probability = float(row.get("estimated_probability_exploratory"))
        except (TypeError, ValueError, OverflowError):
            probability = math.nan
        probability_ok = math.isfinite(probability) and 0 <= probability <= 1
        if not probability_ok:
            invalid_probability += 1

        if metadata_ok and probability_ok:
            structurally_valid += 1
            markets.add(market)
            league = str(row.get("league") or "").strip()
            if league:
                leagues.add(league)
            key = (
                fixture, market, str(row.get("minute") or "").strip(),
                str(row.get("score_home") or "").strip(),
                str(row.get("score_away") or "").strip(),
            )
            if key in seen:
                duplicate_count += 1
            else:
                seen.add(key)
                distinct_valid += 1

        if _verified(row.get("outcome_verified")):
            if probability_ok and _binary(row.get("outcome")) is not None:
                verified_valid += 1
            else:
                verified_invalid += 1

    return {
        "row_count": len(rows),
        "structurally_valid_rows": structurally_valid,
        "distinct_valid_forecasts": distinct_valid,
        "duplicate_forecasts": duplicate_count,
        "invalid_metadata_rows": invalid_metadata,
        "invalid_probability_rows": invalid_probability,
        "verified_valid_outcomes": verified_valid,
        "verified_invalid_outcomes": verified_invalid,
        "market_count": len(markets),
        "league_count": len(leagues),
        "markets": sorted(markets, key=str.casefold),
        "leagues": sorted(leagues, key=str.casefold),
        "warnings": [
            "La auditoría no corrige ni elimina filas.",
            "Los duplicados se identifican por partido, mercado, minuto y marcador.",
            "Un resultado solo cuenta como verificado si outcome_verified es explícito y outcome es binario.",
            "La calidad estructural no demuestra calibración ni rentabilidad.",
        ],
    }
