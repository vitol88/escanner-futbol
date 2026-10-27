from typing import Any

def summarize_live_context(stats: list[dict[str, Any]], elapsed: int | None) -> dict[str, Any]:
    def stat(name: str, team: int):
        if team >= len(stats or []):
            return None
        return next((item.get("value") for item in (stats[team].get("statistics") or []) if item.get("type") == name), None)
    result = {}
    for label, api_name in (("corners", "Corner Kicks"), ("shots", "Total Shots"), ("shots_on", "Shots on Goal"), ("possession", "Ball Possession"), ("yellow", "Yellow Cards"), ("red", "Red Cards")):
        result[label + "_home"] = stat(api_name, 0)
        result[label + "_away"] = stat(api_name, 1)
    def num(v):
        try:
            return float(str(v).replace("%", "")) if v is not None else None
        except (TypeError, ValueError):
            return None
    core = [num(result.get(k)) for k in ("corners_home", "corners_away", "shots_home", "shots_away")]
    result["core_complete"] = all(v is not None for v in core)
    result["elapsed"] = elapsed
    result["corners_total"] = sum(core[:2]) if all(v is not None for v in core[:2]) else None
    result["shots_total"] = sum(core[2:]) if all(v is not None for v in core[2:]) else None
    shots_on = [num(result.get(k)) for k in ("shots_on_home", "shots_on_away")]
    result["shots_on_total"] = sum(shots_on) if all(v is not None for v in shots_on) else None
    red_cards = [num(result.get(k)) for k in ("red_home", "red_away")]
    result["red_cards_total"] = sum(red_cards) if all(value is not None for value in red_cards) else None
    has_any_stats = any(v is not None for k, v in result.items() if k not in ("elapsed", "core_complete", "context_status"))
    result["context_status"] = "completo" if result["core_complete"] and result["possession_home"] is not None and result["possession_away"] is not None else "parcial" if has_any_stats else "sin datos"
    return result


def qualifies_as_corner_candidate(
    minute: int | None,
    total_corners: int | float | None,
    pace_per_90: int | float | None,
    home_shots: int | float | None,
    away_shots: int | float | None,
) -> bool:
    """Apply the experimental corner-candidate gate without imputing missing shots."""
    numeric_values = (total_corners, pace_per_90, home_shots, away_shots)
    if any(not isinstance(value, (int, float)) for value in numeric_values):
        return False
    if not isinstance(minute, int) or isinstance(minute, bool):
        return False
    if any(value < 0 for value in numeric_values):
        return False
    return (
        15 <= minute <= 78
        and total_corners >= 5
        and pace_per_90 >= 10
        and home_shots + away_shots >= 8
    )
