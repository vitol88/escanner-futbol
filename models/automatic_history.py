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

    diagnostics: dict[str, Any] = {"league_id": league_id, "season": season, "teams": {}, "historical_stats": {"requested": 0, "nonempty_responses": 0, "responses_with_corners": 0, "empty_responses": 0, "errors": []}}

    def team_fixtures(team_id: int) -> list[dict[str, Any]]:
        key = f"team-fixtures-v5:{team_id}:{league_id}:{season}"
        if key not in cache:
            # Cap team-fixture discovery calls for the whole scan; cached teams do not
            # consume the budget again. This avoids one hidden request per live fixture.
            if int(cache.get("_automatic_history_team_fixture_calls", 0)) >= 40:
                # No guardar [] como si la API hubiera confirmado que no hay partidos.
                # Es un límite temporal de esta pasada; el equipo debe poder reintentarse
                # en el siguiente escaneo, especialmente si es el partido seleccionado.
                budget_message = "Límite temporal de consultas históricas por escaneo alcanzado; se reintentará en el próximo escaneo."
                diagnostics["teams"][str(team_id)] = {"returned": 0, "error": budget_message, "source": "budget"}
                return []
            # Ventana más amplia para encontrar suficientes partidos según la localía.
            params = {"team": team_id, "last": 30, "league": league_id, "season": season}
            try:
                cache["_automatic_history_team_fixture_calls"] = int(cache.get("_automatic_history_team_fixture_calls", 0)) + 1
                payload = api_get("fixtures", params)
                cache[key] = (payload.get("response") or [])
                diagnostics["teams"][str(team_id)] = {"returned": len(cache[key]), "params": params, "error": None}
            except Exception as exc:
                cache[key] = []
                cache["error:" + key] = str(exc)
                diagnostics["teams"][str(team_id)] = {"returned": 0, "params": params, "error": str(exc)}
        if str(team_id) not in diagnostics["teams"]:
            diagnostics["teams"][str(team_id)] = {"returned": len(cache[key]), "error": cache.get("error:" + key), "source": "cache"}
        return cache[key]

    # Solo partidos finalizados de la misma competición y temporada del partido en vivo.
    finished = {"FT", "AET", "PEN"}
    def same_competition_finished(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item for item in items
            if (item.get("fixture") or {}).get("status", {}).get("short") in finished
            and (item.get("league") or {}).get("id") == league_id
            and str((item.get("league") or {}).get("season")) == str(season)
        ]
    home_raw = team_fixtures(home["id"])
    away_raw = team_fixtures(away["id"])
    home_fixtures = same_competition_finished(home_raw)
    away_fixtures = same_competition_finished(away_raw)
    diagnostics["home_fixture_rows"] = len(home_raw)
    diagnostics["away_fixture_rows"] = len(away_raw)
    diagnostics["home_finished_same_competition"] = len(home_fixtures)
    diagnostics["away_finished_same_competition"] = len(away_fixtures)

    # Repartir las consultas entre local y visitante evita que el primer equipo
    # consuma todo el presupuesto y deje al segundo sin muestra histórica.
    total_budget = max(0, int(stats_budget))
    home_budget = [(total_budget + 1) // 2]
    away_budget = [total_budget // 2]

    def averages(matches: list[dict[str, Any]], team_id: int, venue: str, request_budget: list[int]) -> dict[str, Any]:
        gf: list[float] = []
        ga: list[float] = []
        cf: list[float] = []
        ca: list[float] = []
        used = 0
        stats_attempted = 0
        stats_nonempty = 0
        stats_with_corners = 0
        stats_errors: list[str] = []
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
            stats_key = f"historical-stats-v2:{old_id}"
            if old_id and stats_key not in cache and request_budget[0] > 0 and not cache.get("_automatic_history_rate_limited"):
                try:
                    stats_payload = api_get("fixtures/statistics", {"fixture": old_id})
                    stats_response = stats_payload.get("response") or []
                    stats_attempted += 1
                    diagnostics["historical_stats"]["requested"] += 1
                    cache["_automatic_history_stats_calls"] = cache.get("_automatic_history_stats_calls", 0) + 1
                    request_budget[0] -= 1
                    # Guardar también respuestas vacías: evita repetir la misma
                    # consulta en cada rerun de Streamlit.
                    cache[stats_key] = stats_response
                    if stats_response:
                        stats_nonempty += 1
                        diagnostics["historical_stats"]["nonempty_responses"] += 1
                    else:
                        diagnostics["historical_stats"]["empty_responses"] += 1
                except Exception as exc:
                    stats_errors.append(str(exc))
                    diagnostics["historical_stats"]["errors"].append({"fixture_id": old_id, "error": str(exc)})
                    if "HTTP 429" in str(exc):
                        cache["_automatic_history_rate_limited"] = True
                        break
            stats = cache.get(stats_key, [])
            # API-Football normalmente ordena local/visitante, pero identificar por ID
            # evita asociar córners al equipo equivocado si la respuesta cambia de orden.
            own_stats_index = next(
                (idx for idx, row in enumerate(stats or [])
                 if (row.get("team") or {}).get("id") == team_id),
                0 if is_home else 1,
            )
            opponent_id = ((old_teams.get("away") if is_home else old_teams.get("home")) or {}).get("id")
            opponent_stats_index = next(
                (idx for idx, row in enumerate(stats or [])
                 if (row.get("team") or {}).get("id") == opponent_id),
                1 - own_stats_index,
            )
            own_c = _stat(stats, own_stats_index, "Corner Kicks")
            opp_c = _stat(stats, opponent_stats_index, "Corner Kicks")
            if own_c is not None and opp_c is not None:
                cf.append(own_c); ca.append(opp_c)
                stats_with_corners += 1
                diagnostics["historical_stats"]["responses_with_corners"] += 1
            used += 1
        return {"matches": used, "gf": _mean(gf), "ga": _mean(ga), "cf": _mean(cf), "ca": _mean(ca), "corner_sample": len(cf), "goal_sample": len(gf), "stats_attempted": stats_attempted, "stats_nonempty": stats_nonempty, "stats_with_corners": stats_with_corners, "stats_errors": stats_errors}

    h = averages(home_fixtures, home["id"], "home", home_budget)
    # Si el local tuvo menos partidos consultables de los previstos, transferir
    # el remanente al visitante sin superar el presupuesto total.
    away_budget[0] += home_budget[0]
    a = averages(away_fixtures, away["id"], "away", away_budget)
    result.update({
        "available": bool(h["matches"] or a["matches"]),
        "home_matches": h["matches"], "away_matches": a["matches"],
        "home_goals_for": h["gf"], "home_goals_against": h["ga"],
        "away_goals_for": a["gf"], "away_goals_against": a["ga"],
        "home_corners_for": h["cf"], "home_corners_against": h["ca"],
        "away_corners_for": a["cf"], "away_corners_against": a["ca"],
        "home_corner_sample": h["corner_sample"], "away_corner_sample": a["corner_sample"],
        "home_goal_sample": h["goal_sample"], "away_goal_sample": a["goal_sample"],
        "diagnostics": {**diagnostics, "home_venue_matches_checked": h["matches"], "away_venue_matches_checked": a["matches"], "home_stats_attempted": h["stats_attempted"], "away_stats_attempted": a["stats_attempted"], "home_stats_nonempty": h["stats_nonempty"], "away_stats_nonempty": a["stats_nonempty"], "home_stats_with_corners": h["stats_with_corners"], "away_stats_with_corners": a["stats_with_corners"], "stats_budget_remaining": home_budget[0] + away_budget[0]},
        "note": "Promedios calculados con partidos finalizados de la misma competición y temporada. La muestra cuenta únicamente partidos con estadísticas de córners disponibles.",
    })
    return result
