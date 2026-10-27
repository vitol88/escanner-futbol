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
    result["red_cards_total"] = sum(num(result.get(k)) or 0 for k in ("red_home", "red_away"))
    result["context_status"] = "completo" if result["core_complete"] and result["possession_home"] is not None and result["possession_away"] is not None else "parcial" if any(v is not None for v in result.values()) else "sin datos"
    return result
