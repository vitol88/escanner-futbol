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

        raw_probability = row.get("estimated_probability_exploratory")
        if raw_probability in (None, ""):
            raw_probability = row.get("probability")
        try:
            probability = float(raw_probability)
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


def audit_prediction_history(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only integrity audit for canonical ledger rows joined with verified outcomes.

    Exact duplicates require the same fixture/event identity, model/version,
    timestamp and probability. Repeated snapshots at different timestamps are
    legitimate. Conflicting verified outcomes are checked across model versions
    but only within the same fixture, market, selection, line and phase.
    """
    if not isinstance(rows, list):
        rows = []

    duplicate_groups: dict[tuple[str, ...], list[int]] = {}
    outcome_groups: dict[tuple[str, ...], set[int]] = {}
    missing_fields = {
        field: 0 for field in (
            "fixture_id", "market", "selection", "line", "phase",
            "model_id", "model_version", "recorded_at",
        )
    }
    invalid_probability = 0
    invalid_verified_outcomes = 0
    valid_verified_outcomes = 0

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            for field in missing_fields:
                missing_fields[field] += 1
            continue

        values = {
            "fixture_id": str(row.get("fixture_id") or "").strip(),
            "market": str(row.get("market_type") or row.get("market") or "").strip(),
            "selection": str(row.get("selection") or "").strip(),
            "line": str(row.get("line") or "").strip(),
            "phase": str(row.get("phase") or "").strip(),
            "model_id": str(row.get("model_id") or "").strip(),
            "model_version": str(row.get("model_version") or "").strip(),
            "recorded_at": str(row.get("recorded_at") or "").strip(),
        }
        for field, value in values.items():
            if not value:
                missing_fields[field] += 1

        raw_probability = row.get("probability")
        if raw_probability in (None, ""):
            raw_probability = row.get("estimated_probability_exploratory")
        try:
            probability = float(raw_probability)
        except (TypeError, ValueError, OverflowError):
            probability = math.nan
        probability_ok = math.isfinite(probability) and 0 <= probability <= 1
        if not probability_ok:
            invalid_probability += 1

        # A timestamped exact identity distinguishes a duplicate row from a
        # legitimate later live snapshot. Missing identity is not guessed.
        identity_fields = (
            values["fixture_id"], values["market"], values["selection"],
            values["line"], values["phase"], values["model_id"],
            values["model_version"], values["recorded_at"],
        )
        if all(identity_fields) and probability_ok:
            duplicate_key = identity_fields + (format(probability, ".15g"),)
            duplicate_groups.setdefault(duplicate_key, []).append(index)

        if _verified(row.get("outcome_verified")):
            outcome = _binary(row.get("outcome"))
            if outcome is None:
                invalid_verified_outcomes += 1
            else:
                valid_verified_outcomes += 1
                # Do not mix different market definitions. Model/version is
                # intentionally omitted: the real outcome is fixture-level.
                event_fields = (
                    values["fixture_id"], values["market"], values["selection"],
                    values["line"], values["phase"],
                )
                if all(event_fields):
                    outcome_groups.setdefault(event_fields, set()).add(outcome)

    duplicate_row_count = sum(len(indices) - 1 for indices in duplicate_groups.values())
    duplicate_groups_count = sum(1 for indices in duplicate_groups.values() if len(indices) > 1)
    contradictory_groups = [
        key for key, outcomes in outcome_groups.items() if len(outcomes) > 1
    ]
    return {
        "row_count": len(rows),
        "exact_duplicate_rows": duplicate_row_count,
        "exact_duplicate_groups": duplicate_groups_count,
        "contradictory_verified_outcome_groups": len(contradictory_groups),
        "contradictory_event_samples": [
            {
                "fixture_id": key[0], "market": key[1], "selection": key[2],
                "line": key[3], "phase": key[4],
            }
            for key in contradictory_groups[:10]
        ],
        "missing_metadata": missing_fields,
        "invalid_probability_rows": invalid_probability,
        "verified_valid_outcomes": valid_verified_outcomes,
        "verified_invalid_outcomes": invalid_verified_outcomes,
        "warnings": [
            "Auditoría de solo lectura: no modifica, elimina ni corrige registros.",
            "Snapshots del mismo evento en momentos distintos se conservan como históricos legítimos.",
            "Los resultados contradictorios se comparan solo con la misma identidad de partido, mercado, selección, línea y fase; las versiones del modelo no separan el resultado real.",
            "Los hallazgos requieren revisión manual y no prueban por sí solos cuál registro es correcto.",
        ],
    }
