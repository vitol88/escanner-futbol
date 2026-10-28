"""Automatic recent-form history using API-Football, with bounded requests and caching."""
from __future__ import annotations

from typing import Any, Callable


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _stat(stats: list[dict[str, Any]], team_index: int, name: str) -> float | None:
    if team_index >= len(stats or []):
        return None
    for item in (stats[team_index].get("statistics") or []):
        if item.get("type") == name:
            return _num(item.get("value"))
    return None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def build_automatic_history(
    fixture: dict[str, Any],
    *,
    api_get: Callable[..., dict[str, Any]],
    cache: dict[str, Any],
    stats_budget: int = 8,
) -> dict[str, Any]:
    """Build local/home and visitor/away recent averages without any CSV upload.

    Historical fixture statistics are requested lazily, cached for this Streamlit
    session, and capped by stats_budget. Missing values stay missing, never zero.
    """
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    league = fixture.get("league") or {}
    league_id = league.get("id")
    season = league.get("season")
    result: dict[str, Any] = {
        "available": False, "home_team": home.get("name"), "away_team": away.get("name"),
        "home_matches": 0, "away_matches": 0, "h2h_matches": 0,
        "home_corners_for": None, "home_corners_against": None,
        "away_corners_for": None, "away_corners_against": None,
        "home_goals_for": None, "home_goals_against": None,
        "away_goals_for": None, "away_goals_against": None,
        "h2h_corners_total": None, "h2h_goals_total": None,
        "note": "Historial no disponible todavía.",
    }
    if not home.get("id") or not away.get("id") or not league_id or not season:
        result["note"] = "Faltan IDs de equipos, liga o temporada para consultar el historial."
        return result

    def team_fixtures(team_id: int) -> list[dict[str, Any]]:
        key = f"team-fixtures-v2:{team_id}:{league_id}:{season}"
        if key not in cache:
            # Cap team-fixture discovery calls for the whole scan; cached teams do not
            # consume the budget again. This avoids one hidden request per live fixture.
            if int(cache.get("_automatic_history_team_fixture_calls", 0)) >= 12:
                cache[key] = []
                cache["error:" + key] = "Límite de consultas históricas por escaneo alcanzado."
                return cache[key]
            # Ventana más amplia para encontrar suficientes partidos según la localía.
            params = {"team": team_id, "last": 20, "league": league_id, "season": season}
            try:
                cache["_automatic_history_team_fixture_calls"] = int(cache.get("_automatic_history_team_fixture_calls", 0)) + 1
                cache[key] = (api_get("fixtures", params).get("response") or [])
            except Exception as exc:
                cache[key] = []
                cache["error:" + key] = str(exc)
        return cache[key]

    home_fixtures = [f for f in team_fixtures(home["id"]) if (f.get("fixture") or {}).get("status", {}).get("short") in {"FT", "AET", "PEN"}]
    away_fixtures = [f for f in team_fixtures(away["id"]) if (f.get("fixture") or {}).get("status", {}).get("short") in {"FT", "AET", "PEN"}]

    budget = [max(0, int(stats_budget))]

    def averages(matches: list[dict[str, Any]], team_id: int, venue: str) -> dict[str, Any]:
        gf: list[float] = []
        ga: list[float] = []
        cf: list[float] = []
        ca: list[float] = []
        used = 0
        for old in matches:
            old_teams = old.get("teams") or {}
            is_home = (old_teams.get("home") or {}).get("id") == team_id
            if venue == "home" and not is_home:
                continue
            if venue == "away" and is_home:
                continue
            goals = old.get("goals") or {}
            own_goals = goals.get("home" if is_home else "away")
            opp_goals = goals.get("away" if is_home else "home")
            if isinstance(own_goals, (int, float)) and isinstance(opp_goals, (int, float)):
                gf.append(float(own_goals)); ga.append(float(opp_goals))
            old_id = (old.get("fixture") or {}).get("id")
            stats_key = f"historical-stats:{old_id}"
            if old_id and stats_key not in cache and budget[0] > 0 and not cache.get("_automatic_history_rate_limited"):
                try:
                    cache[stats_key] = api_get("fixtures/statistics", {"fixture": old_id}).get("response") or []
                    cache["_automatic_history_stats_calls"] = cache.get("_automatic_history_stats_calls", 0) + 1
                    budget[0] -= 1
                except Exception as exc:
                    cache[stats_key] = []
                    cache[f"error:{stats_key}"] = str(exc)
                    if "HTTP 429" in str(exc):
                        cache["_automatic_history_rate_limited"] = True
                        break
            stats = cache.get(stats_key, [])
            index = 0 if is_home else 1
            own_c = _stat(stats, index, "Corner Kicks")
            opp_c = _stat(stats, 1-index, "Corner Kicks")
            if own_c is not None and opp_c is not None:
                cf.append(own_c); ca.append(opp_c)
            used += 1
        return {"matches": used, "gf": _mean(gf), "ga": _mean(ga), "cf": _mean(cf), "ca": _mean(ca), "corner_sample": len(cf), "goal_sample": len(gf)}

    h = averages(home_fixtures, home["id"], "home")
    a = averages(away_fixtures, away["id"], "away")
    result.update({
        "available": bool(h["matches"] or a["matches"]),
        "home_matches": h["matches"], "away_matches": a["matches"],
        "home_goals_for": h["gf"], "home_goals_against": h["ga"],
        "away_goals_for": a["gf"], "away_goals_against": a["ga"],
        "home_corners_for": h["cf"], "home_corners_against": h["ca"],
        "away_corners_for": a["cf"], "away_corners_against": a["ca"],
        "home_corner_sample": h["corner_sample"], "away_corner_sample": a["corner_sample"],
        "home_goal_sample": h["goal_sample"], "away_goal_sample": a["goal_sample"],
        "note": "Promedios automáticos de partidos recientes de esta liga/temporada; los córners solo se muestran cuando la API devuelve estadísticas históricas.",
    })
    return result
