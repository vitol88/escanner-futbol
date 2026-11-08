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
        "goals_mae": _mean(goals, "goals_absolute_error"),
        "goals_bias": _mean(goals, "projected_final_goals") - _mean(goals, "actual_final_goals")
            if goals and _mean(goals, "projected_final_goals") is not None and _mean(goals, "actual_final_goals") is not None else None,
        "corners_count": len(corners),
        "corners_mae": _mean(corners, "corners_absolute_error"),
        "corners_bias": _mean(corners, "projected_final_corners") - _mean(corners, "final_total_corners")
            if corners and _mean(corners, "projected_final_corners") is not None and _mean(corners, "final_total_corners") is not None else None,
    }
