"""Read and summarize the Supabase snapshot evaluation view."""
from __future__ import annotations

from typing import Any
import requests

EVALUATION_COLUMNS = (
    "snapshot_id,fixture_id,analysis_type,recorded_at,home_team,away_team,"
    "minute_at_capture,home_score_at_capture,away_score_at_capture,"
    "final_home_score,final_away_score,actual_final_goals,projected_final_goals,"
    "goals_absolute_error,projected_final_corners,final_total_corners,"
    "corners_absolute_error,final_total_yellow_cards,result_source,result_verified_at"
)


def load_supabase_evaluations(supabase_url: str, secret_key: str, *, get=None,
                              timeout: float = 15.0) -> list[dict[str, Any]]:
    url = str(supabase_url or "").strip().rstrip("/")
    key = str(secret_key or "").strip()
    if not url or not key:
        raise ValueError("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY.")
    reader = get or requests.get
    rows: list[dict[str, Any]] = []
    start, page_size = 0, 500
    while True:
        response = reader(
            f"{url}/rest/v1/analysis_snapshot_evaluation",
            params={"select": EVALUATION_COLUMNS,
                    "order": "recorded_at.desc,snapshot_id.asc",
                    "offset": start, "limit": page_size},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError("Respuesta inesperada de analysis_snapshot_evaluation.")
        rows.extend(item for item in page if isinstance(item, dict))
        if len(page) < page_size:
            break
        start += page_size
    return rows


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = []
    for row in rows:
        value = row.get(field)
        try:
            if value is not None:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None



def classify_sample_reliability(independent_matches: int) -> str:
    """Describe evidence volume without implying statistical significance."""
    count = max(0, int(independent_matches or 0))
    if count < 10:
        return "Muestra insuficiente"
    if count < 30:
        return "En observación"
    return "Base amplia · seguimiento"


def _distinct_fixtures(rows: list[dict[str, Any]]) -> int:
    return len({
        str(row.get("fixture_id")).strip()
        for row in rows
        if row.get("fixture_id") not in (None, "")
    })


def summarize_supabase_evaluations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [row for row in rows if row.get("result_verified_at")]
    goals = [row for row in verified if row.get("goals_absolute_error") is not None]
    corners = [row for row in verified if row.get("corners_absolute_error") is not None]
    fixtures = {str(row.get("fixture_id")) for row in rows if row.get("fixture_id")}
    return {
        "total": len(rows),
        "verified": len(verified),
        "pending": len(rows) - len(verified),
        "fixtures": len(fixtures),
        "goals_count": len(goals),
        "goals_fixtures": _distinct_fixtures(goals),
        "goals_reliability": classify_sample_reliability(_distinct_fixtures(goals)),
        "goals_mae": _mean(goals, "goals_absolute_error"),
        "goals_bias": _mean(goals, "projected_final_goals") - _mean(goals, "actual_final_goals")
            if goals and _mean(goals, "projected_final_goals") is not None and _mean(goals, "actual_final_goals") is not None else None,
        "corners_count": len(corners),
        "corners_fixtures": _distinct_fixtures(corners),
        "corners_reliability": classify_sample_reliability(_distinct_fixtures(corners)),
        "corners_mae": _mean(corners, "corners_absolute_error"),
        "corners_bias": _mean(corners, "projected_final_corners") - _mean(corners, "final_total_corners")
            if corners and _mean(corners, "projected_final_corners") is not None and _mean(corners, "final_total_corners") is not None else None,
    }


def summarize_evaluations_by_minute(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group verified prediction errors by market and capture-minute band."""
    bands = (
        ("0-29", 0, 29),
        ("30-59", 30, 59),
        ("60-74", 60, 74),
        ("75-90+", 75, 200),
    )
    verified = [row for row in rows if row.get("result_verified_at")]
    output: list[dict[str, Any]] = []
    for market, error_field in (
        ("goals", "goals_absolute_error"),
        ("corners", "corners_absolute_error"),
    ):
        for label, low, high in bands:
            group = []
            for row in verified:
                if row.get("analysis_type") != market or row.get(error_field) is None:
                    continue
                try:
                    minute = int(row.get("minute_at_capture"))
                except (TypeError, ValueError):
                    continue
                if low <= minute <= high:
                    group.append(row)
            if not group:
                continue
            output.append({
                "Mercado": market,
                "Minuto de captura": label,
                "Muestras": len(group),
                "Partidos distintos": len({str(r.get("fixture_id")) for r in group if r.get("fixture_id")}),
                "Clasificación": classify_sample_reliability(_distinct_fixtures(group)),
                "Error medio absoluto": round(_mean(group, error_field), 2),
            })
    return output
