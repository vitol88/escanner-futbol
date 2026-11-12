"""Automatic recent-form history using API-Football, with bounded requests and caching."""
from __future__ import annotations

from typing import Any, Callable
import time


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


def _corner_parts(stats: list[dict[str, Any]], team_index: int) -> tuple[float | None, float | None, float | None]:
    """Return full-match, first-half and second-half corners for one team."""
    if team_index < 0 or team_index >= len(stats or []):
        return None, None, None
    row = stats[team_index] or {}
    raw = row.get("statistics") or {}
    if isinstance(raw, dict):
        full = _num(raw.get("corner_kicks"))
    else:
        full = _stat(stats, team_index, "Corner Kicks")
    first = _num((row.get("first_half") or {}).get("corner_kicks"))
    second = _num((row.get("second_half") or {}).get("corner_kicks"))
    # Compatibility with older response variants that expose half stats as
    # nested objects in the statistics field.
    if first is None:
        first = _num((raw.get("first_half") or {}).get("corner_kicks")) if isinstance(raw, dict) else None
    if second is None:
        second = _num((raw.get("second_half") or {}).get("corner_kicks")) if isinstance(raw, dict) else None
    return full, first, second


def build_automatic_history(
    fixture: dict[str, Any],
    *,
    api_get: Callable[..., dict[str, Any]],
    cache: dict[str, Any],
    stats_budget: int = 8,
    live_corner_finalizer: Callable[[dict[str, Any], list[dict[str, Any]]], Any] | None = None,
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
        "available": False, "corners_available": False, "corners_pending": False, "home_team": home.get("name"), "away_team": away.get("name"),
        "home_matches": 0, "away_matches": 0, "h2h_matches": 0,
        "home_corners_for": None, "home_corners_against": None,
        "card_history_rows": [],
        "away_corners_for": None, "away_corners_against": None,
        "home_goals_for": None, "home_goals_against": None,
        "away_goals_for": None, "away_goals_against": None,
        "h2h_corners_total": None, "h2h_goals_total": None,
        "note": "Historial no disponible todavía.",
    }
    if not home.get("id") or not away.get("id") or not league_id or not season:
        result["note"] = "Faltan IDs de equipos, liga o temporada para consultar el historial."
        return result

    coverage_key = f"league-statistics-coverage-v1:{league_id}:{season}"
    coverage_error = None
    if coverage_key not in cache:
        try:
            coverage_payload = api_get("leagues", {"id": league_id, "season": season})
            coverage_rows = coverage_payload.get("response") or []
            coverage_value = None
            if coverage_rows:
                seasons = (coverage_rows[0].get("seasons") or [])
                season_row = next((row for row in seasons if str(row.get("year")) == str(season)), None)
                if season_row is not None:
                    fixtures_coverage = ((season_row.get("coverage") or {}).get("fixtures") or {})
                    raw_coverage = fixtures_coverage.get("statistics_fixtures")
                    coverage_value = raw_coverage if isinstance(raw_coverage, bool) else None
            cache[coverage_key] = coverage_value
        except Exception as exc:
            coverage_error = str(exc)
            cache[coverage_key] = None
    league_statistics_coverage = cache.get(coverage_key)
    diagnostics: dict[str, Any] = {
        "league_id": league_id,
        "season": season,
        "teams": {},
        "league_statistics_coverage": league_statistics_coverage,
        "league_statistics_coverage_error": coverage_error,
        "historical_stats": {"requested": 0, "nonempty_responses": 0, "responses_with_corners": 0, "empty_responses": 0, "skipped_unsupported": 0, "errors": []},
        "live_corner_finalization": {"attempted": 0, "finalized": 0, "observations_inserted": 0, "errors": []},
    }

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
        # Keep the same competition/season filter used by main for goals and
        # corners. Do not require optional timestamp metadata here: some valid
        # API responses omit it or serialize it differently, which would erase
        # every historical sample and display N/D despite available fixtures.
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

    card_history_rows: dict[str, dict[str, Any]] = {}

    def averages(matches: list[dict[str, Any]], team_id: int, venue: str, request_budget: list[int]) -> dict[str, Any]:
        gf: list[float] = []
        ga: list[float] = []
        cf: list[float] = []
        ca: list[float] = []
        cf_first: list[float] = []
        ca_first: list[float] = []
        cf_second: list[float] = []
        ca_second: list[float] = []
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
            full_stats_key = f"historical-stats-full-v1:{old_id}"
            half_stats_key = f"historical-stats-halves-v5:{old_id}"
            half_retry_key = f"{half_stats_key}:retry_after"
            full_retry_key = f"{full_stats_key}:retry_after"
            if old_id and full_stats_key not in cache and time.time() >= float(cache.get(full_retry_key, 0) or 0) and request_budget[0] > 0 and not cache.get("_automatic_history_rate_limited") and league_statistics_coverage is not False:
                try:
                    # Count every real historical-statistics request across all fixtures
                    # in this scan, including attempts that fail or return no data.
                    cache["_automatic_history_stats_calls"] = int(cache.get("_automatic_history_stats_calls", 0) or 0) + 1
                    stats_attempted += 1
                    diagnostics["historical_stats"]["requested"] += 1
                    # Consume budget before the call: failed/429 attempts are real requests too.
                    request_budget[0] -= 1
                    full_response = (api_get("fixtures/statistics", {"fixture": old_id}).get("response") or [])
                    if full_response:
                        cache[full_stats_key] = full_response
                        stats_nonempty += 1
                        diagnostics["historical_stats"]["nonempty_responses"] += 1
                    else:
                        cache[full_retry_key] = time.time() + 900
                        diagnostics["historical_stats"]["empty_responses"] += 1
                except Exception as exc:
                    stats_errors.append(str(exc))
                    diagnostics["historical_stats"]["errors"].append({"fixture_id": old_id, "source": "full", "error": str(exc)})
                    cache[full_retry_key] = time.time() + (300 if "429" in str(exc) else 180)
                    if "HTTP 429" in str(exc):
                        cache["_automatic_history_rate_limited"] = True
            if old_id and full_stats_key not in cache and league_statistics_coverage is False:
                diagnostics["historical_stats"]["skipped_unsupported"] += 1
            stats = cache.get(full_stats_key, [])

            # Reuse the same completed-fixture statistics already fetched for
            # recent-form history. No extra endpoint or request is introduced.
            if live_corner_finalizer is not None and stats:
                try:
                    diagnostics["live_corner_finalization"]["attempted"] += 1
                    finalized = live_corner_finalizer(old, stats)
                    if isinstance(finalized, dict) and finalized.get("finalized"):
                        diagnostics["live_corner_finalization"]["finalized"] += 1
                        diagnostics["live_corner_finalization"]["observations_inserted"] += int(
                            finalized.get("observations_inserted", 0) or 0
                        )
                except Exception as finalize_exc:
                    diagnostics["live_corner_finalization"]["errors"].append({
                        "fixture_id": old_id,
                        "error": str(finalize_exc),
                    })

            half_stats = cache.get(half_stats_key)
            if old_id and full_stats_key in cache and half_stats is None and len(cf) >= 3 and request_budget[0] > 1 and time.time() >= float(cache.get(half_retry_key, 0) or 0) and not cache.get("_automatic_history_rate_limited") and league_statistics_coverage is not False:
                # Prioritize full-match corner samples; half splits are secondary
                # and must not consume the budget before venue averages exist.
                try:
                    # Half-time statistics consume the same shared API budget.
                    cache["_automatic_history_stats_calls"] = int(cache.get("_automatic_history_stats_calls", 0) or 0) + 1
                    stats_attempted += 1
                    diagnostics["historical_stats"]["requested"] += 1
                    # Consume budget before the call: failed/429 attempts are real requests too.
                    request_budget[0] -= 1
                    half_response = (api_get("fixtures/statistics", {"fixture": old_id, "half": "true"}).get("response") or [])
                    if half_response:
                        cache[half_stats_key] = half_response
                        half_stats = half_response
                    else:
                        cache[half_retry_key] = time.time() + 1800
                        diagnostics["historical_stats"]["empty_responses"] += 1
                except Exception as exc:
                    stats_errors.append(str(exc))
                    diagnostics["historical_stats"]["errors"].append({"fixture_id": old_id, "source": "halves", "error": str(exc)})
                    cache[half_retry_key] = time.time() + (300 if "429" in str(exc) else 900)
                    if "HTTP 429" in str(exc):
                        cache["_automatic_history_rate_limited"] = True
            half_stats = half_stats or []
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
            old_home_id = (old_teams.get("home") or {}).get("id")
            old_away_id = (old_teams.get("away") or {}).get("id")
            home_stats_index = next(
                (idx for idx, row in enumerate(stats or [])
                 if (row.get("team") or {}).get("id") == old_home_id),
                0,
            )
            away_stats_index = next(
                (idx for idx, row in enumerate(stats or [])
                 if (row.get("team") or {}).get("id") == old_away_id),
                1,
            )
            home_yellow = _stat(stats, home_stats_index, "Yellow Cards")
            away_yellow = _stat(stats, away_stats_index, "Yellow Cards")
            old_fixture_info = old.get("fixture") or {}
            old_timestamp = old_fixture_info.get("timestamp")
            target_timestamp = (fixture.get("fixture") or {}).get("timestamp")
            # Strict temporal guard: card-model rows require both timestamps and
            # the historical fixture must be strictly earlier than the target kickoff.
            before_target = (
                isinstance(old_timestamp, (int, float))
                and not isinstance(old_timestamp, bool)
                and isinstance(target_timestamp, (int, float))
                and not isinstance(target_timestamp, bool)
                and old_timestamp < target_timestamp
            )
            if old_id and before_target and home_yellow is not None and away_yellow is not None:
                card_history_rows[str(old_id)] = {
                    "fixture_id": old_id,
                    "fixture_timestamp": old_timestamp,
                    "league_id": (old.get("league") or {}).get("id"),
                    "season": (old.get("league") or {}).get("season"),
                    "home_team_id": old_home_id,
                    "away_team_id": old_away_id,
                    "home_team": (old_teams.get("home") or {}).get("name"),
                    "away_team": (old_teams.get("away") or {}).get("name"),
                    "home_yellow_cards": home_yellow,
                    "away_yellow_cards": away_yellow,
                    "referee": old_fixture_info.get("referee"),
                }
            own_c, _, _ = _corner_parts(stats, own_stats_index)
            opp_c, _, _ = _corner_parts(stats, opponent_stats_index)
            _, own_first, own_second = _corner_parts(half_stats, own_stats_index)
            _, opp_first, opp_second = _corner_parts(half_stats, opponent_stats_index)
            if own_c is not None and opp_c is not None:
                cf.append(own_c); ca.append(opp_c)
                stats_with_corners += 1
                diagnostics["historical_stats"]["responses_with_corners"] += 1
                if all(value is not None for value in (own_first, own_second, opp_first, opp_second)):
                    cf_first.append(own_first); ca_first.append(opp_first)
                    cf_second.append(own_second); ca_second.append(opp_second)
            used += 1
        return {"matches": used, "gf": _mean(gf), "ga": _mean(ga), "cf": _mean(cf), "ca": _mean(ca), "corner_sample": len(cf), "goal_sample": len(gf), "cf_first": _mean(cf_first), "ca_first": _mean(ca_first), "cf_second": _mean(cf_second), "ca_second": _mean(ca_second), "corner_period_sample": len(cf_first), "goal_sample": len(gf), "stats_attempted": stats_attempted, "stats_nonempty": stats_nonempty, "stats_with_corners": stats_with_corners, "stats_errors": stats_errors}

    h = averages(home_fixtures, home["id"], "home", home_budget)
    # Si el local tuvo menos partidos consultables de los previstos, transferir
    # el remanente al visitante sin superar el presupuesto total.
    away_budget[0] += home_budget[0]
    a = averages(away_fixtures, away["id"], "away", away_budget)
    result.update({
        "available": bool(h["matches"] or a["matches"]),
        "corners_available": bool(h["corner_sample"] or a["corner_sample"]),
        "corners_pending": bool(
            (h["matches"] > 0 and h["corner_sample"] < min(3, h["matches"]))
            or (a["matches"] > 0 and a["corner_sample"] < min(3, a["matches"]))
        ),
        "home_matches": h["matches"], "away_matches": a["matches"],
        "home_goals_for": h["gf"], "home_goals_against": h["ga"],
        "away_goals_for": a["gf"], "away_goals_against": a["ga"],
        "home_corners_for": h["cf"], "home_corners_against": h["ca"],
        "away_corners_for": a["cf"], "away_corners_against": a["ca"],
        "home_corners_for_first": h["cf_first"], "home_corners_against_first": h["ca_first"],
        "away_corners_for_first": a["cf_first"], "away_corners_against_first": a["ca_first"],
        "home_corners_for_second": h["cf_second"], "home_corners_against_second": h["ca_second"],
        "away_corners_for_second": a["cf_second"], "away_corners_against_second": a["ca_second"],
        "home_corner_sample": h["corner_sample"], "away_corner_sample": a["corner_sample"],
        "home_corner_period_sample": h["corner_period_sample"], "away_corner_period_sample": a["corner_period_sample"],
        "home_goal_sample": h["goal_sample"], "away_goal_sample": a["goal_sample"],
        "card_history_rows": sorted(card_history_rows.values(), key=lambda row: row.get("fixture_timestamp") or 0),
        "diagnostics": {**diagnostics, "home_venue_matches_checked": h["matches"], "away_venue_matches_checked": a["matches"], "home_stats_attempted": h["stats_attempted"], "away_stats_attempted": a["stats_attempted"], "home_stats_nonempty": h["stats_nonempty"], "away_stats_nonempty": a["stats_nonempty"], "home_stats_with_corners": h["stats_with_corners"], "away_stats_with_corners": a["stats_with_corners"], "stats_budget_remaining": away_budget[0]},
        "note": "Promedios calculados con partidos finalizados de la misma competición y temporada. La muestra cuenta únicamente partidos con estadísticas de córners disponibles.",
    })
    return result
