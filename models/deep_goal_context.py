"""Deeper, quota-bounded match context for live goal decisions."""
from __future__ import annotations

from typing import Any, Callable


FINISHED = {"FT", "AET", "PEN"}


def _team_goals(fixture: dict[str, Any], team_id: int) -> tuple[int | None, int | None]:
    teams = fixture.get("teams") or {}
    goals = fixture.get("goals") or {}
    home_id = (teams.get("home") or {}).get("id")
    away_id = (teams.get("away") or {}).get("id")
    if team_id == home_id:
        return goals.get("home"), goals.get("away")
    if team_id == away_id:
        return goals.get("away"), goals.get("home")
    return None, None


def _team_name(fixture: dict[str, Any], team_id: int) -> str:
    teams = fixture.get("teams") or {}
    for side in ("home", "away"):
        team = teams.get(side) or {}
        if team.get("id") == team_id:
            return str(team.get("name") or side)
    return "Equipo"


def _result_for(goals_for: int, goals_against: int) -> str:
    return "V" if goals_for > goals_against else "E" if goals_for == goals_against else "D"


def _goal_events(payload: Any) -> list[dict[str, Any]]:
    events = payload if isinstance(payload, list) else []
    return [
        event for event in events
        if (event.get("type") or "").casefold() == "goal"
        and (event.get("detail") or "").casefold() not in {"missed penalty", "penalty missed"}
    ]


def _goal_minute(event: dict[str, Any]) -> int | None:
    """Numeric minute used for comparisons and comeback windows."""
    time = event.get("time") or {}
    elapsed = time.get("elapsed")
    extra = time.get("extra") or 0
    try:
        return int(elapsed) + int(extra)
    except (TypeError, ValueError):
        return None


def _goal_sort_key(event: dict[str, Any]) -> tuple[int, int]:
    """Order events by the API's elapsed and stoppage-time fields."""
    time = event.get("time") or {}
    try:
        elapsed = int(time.get("elapsed") or 0)
    except (TypeError, ValueError):
        elapsed = 0
    try:
        extra = int(time.get("extra") or 0)
    except (TypeError, ValueError):
        extra = 0
    return elapsed, extra


def _goal_minute_label(event: dict[str, Any]) -> str | None:
    """Keep stoppage time exact, e.g. 45+2′ rather than converting it to 47′."""
    time = event.get("time") or {}
    elapsed = time.get("elapsed")
    extra = time.get("extra")
    try:
        elapsed = int(elapsed)
    except (TypeError, ValueError):
        return None
    try:
        extra = int(extra) if extra is not None else 0
    except (TypeError, ValueError):
        extra = 0
    return f"{elapsed}+{extra}′" if extra > 0 else f"{elapsed}′"


def build_deep_goal_context(
    fixture: dict[str, Any],
    *,
    api_get: Callable[..., dict[str, Any]],
    cache: dict[str, Any],
    event_fixture_budget: int = 3,
) -> dict[str, Any]:
    """Summarize league form, H2H, and recent responses after conceding.

    All calls are cached in the supplied session cache. Historical event calls are
    deliberately capped because the free API plan has a daily request limit.
    """
    f = fixture.get("fixture") or {}
    current_id = f.get("id")
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    league = fixture.get("league") or {}
    minute = (f.get("status") or {}).get("elapsed")
    score = fixture.get("goals") or {}
    result: dict[str, Any] = {
        "available": False,
        "home_form": {}, "away_form": {}, "h2h": {},
        "current_goal_minute": None, "current_goal_minute_label": None, "current_goal_team": None,
        "comeback": {}, "notes": [],
    }
    if not current_id or not home.get("id") or not away.get("id"):
        result["notes"].append("Faltan identificadores para consultar historial.")
        return result
    key = f"deep-goal-context:{current_id}"
    if key in cache:
        # Refresh only the current match's events so the latest goal updates on reruns;
        # historical form/H2H stays cached to protect the API request budget.
        cached_result = cache[key]
        try:
            current_events = api_get("fixtures/events", {"fixture": current_id}).get("response") or []
            current_goals = _goal_events(current_events)
            if current_goals:
                latest = max(current_goals, key=_goal_sort_key)
                cached_result["current_goal_minute"] = _goal_minute(latest)
                cached_result["current_goal_minute_label"] = _goal_minute_label(latest)
                cached_result["current_goal_team"] = (latest.get("team") or {}).get("name")
            elif isinstance(minute, int) and isinstance(score.get("home"), int) and isinstance(score.get("away"), int) and score["home"] + score["away"] > 0:
                cached_result["current_goal_minute"] = None
                cached_result["current_goal_minute_label"] = None
                cached_result["current_goal_team"] = None
        except Exception:
            # Preserve the last known event data rather than guessing a scorer/minute.
            pass
        cache[key] = cached_result
        return cached_result

    league_id, season = league.get("id"), league.get("season")

    def get_cached(label: str, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        cache_key = f"deep:{label}"
        if cache_key not in cache:
            try:
                cache[cache_key] = api_get(endpoint, params).get("response") or []
            except Exception as exc:
                cache[cache_key] = []
                cache[f"deep-error:{label}"] = str(exc)
        return cache[cache_key] if isinstance(cache[cache_key], list) else []

    def recent(team: dict[str, Any], venue: str) -> list[dict[str, Any]]:
        team_id = team.get("id")
        if not team_id or not league_id or not season:
            return []
        params = {"team": team_id, "last": 8}
        # API-Football supports league/season filters; if these are absent use all recent matches.
        params.update({"league": league_id, "season": season})
        matches = get_cached(f"form:{team_id}:{league_id}:{season}", "fixtures", params)
        selected = []
        for old in matches:
            status = ((old.get("fixture") or {}).get("status") or {}).get("short")
            if status not in FINISHED:
                continue
            old_teams = old.get("teams") or {}
            is_home = (old_teams.get("home") or {}).get("id") == team_id
            if venue == "home" and not is_home:
                continue
            if venue == "away" and is_home:
                continue
            gf, ga = _team_goals(old, team_id)
            if isinstance(gf, int) and isinstance(ga, int):
                selected.append({**old, "_gf": gf, "_ga": ga})
        return selected[:5]

    home_recent = recent(home, "home")
    away_recent = recent(away, "away")

    def form(matches: list[dict[str, Any]]) -> dict[str, Any]:
        results = [_result_for(item["_gf"], item["_ga"]) for item in matches]
        return {
            "matches": len(matches),
            "record": f'{results.count("V")}V {results.count("E")}E {results.count("D")}D' if results else "N/D",
            "goals_for_avg": round(sum(x["_gf"] for x in matches) / len(matches), 2) if matches else None,
            "goals_against_avg": round(sum(x["_ga"] for x in matches) / len(matches), 2) if matches else None,
            "btts_rate": round(100 * sum(x["_gf"] > 0 and x["_ga"] > 0 for x in matches) / len(matches)) if matches else None,
            "over_2_5_rate": round(100 * sum(x["_gf"] + x["_ga"] >= 3 for x in matches) / len(matches)) if matches else None,
        }

    result["home_form"] = form(home_recent)
    result["away_form"] = form(away_recent)

    h2h_matches = get_cached(
        f"h2h:{home['id']}:{away['id']}:{league_id or 'all'}",
        "fixtures/headtohead",
        {"h2h": f"{home['id']}-{away['id']}", "last": 8, **({"league": league_id} if league_id else {})},
    )
    h2h_done = []
    for old in h2h_matches:
        if ((old.get("fixture") or {}).get("status") or {}).get("short") not in FINISHED:
            continue
        goals = old.get("goals") or {}
        if isinstance(goals.get("home"), int) and isinstance(goals.get("away"), int):
            h2h_done.append(old)
    h2h_done = h2h_done[:5]
    result["h2h"] = {
        "matches": len(h2h_done),
        "avg_goals": round(sum((x["goals"]["home"] + x["goals"]["away"]) for x in h2h_done) / len(h2h_done), 2) if h2h_done else None,
        "btts_rate": round(100 * sum(x["goals"]["home"] > 0 and x["goals"]["away"] > 0 for x in h2h_done) / len(h2h_done)) if h2h_done else None,
        "over_2_5_rate": round(100 * sum(x["goals"]["home"] + x["goals"]["away"] >= 3 for x in h2h_done) / len(h2h_done)) if h2h_done else None,
    }

    # Current match events tell us when/which side scored most recently.
    try:
        # Always query the current fixture's event timeline fresh; cached historical events
        # can miss a goal scored moments ago.
        current_events = api_get("fixtures/events", {"fixture": current_id}).get("response") or []
    except Exception:
        current_events = []
    current_goals = _goal_events(current_events)
    if current_goals:
        latest = max(current_goals, key=_goal_sort_key)
        result["current_goal_minute"] = _goal_minute(latest)
        result["current_goal_minute_label"] = _goal_minute_label(latest)
        result["current_goal_team"] = (latest.get("team") or {}).get("name")
    elif isinstance(minute, int) and isinstance(score.get("home"), int) and isinstance(score.get("away"), int) and score["home"] + score["away"] > 0:
        result["notes"].append("No se pudo determinar el minuto exacto del último gol; no se asumió.")

    # Analyze only a few recent fixtures' event timelines. Count cases where the
    # team conceded first and later equalized or scored again, within a similar match phase.
    unique_old: dict[Any, dict[str, Any]] = {}
    for old in home_recent + away_recent:
        old_id = (old.get("fixture") or {}).get("id")
        if old_id and old_id not in unique_old:
            unique_old[old_id] = old
    selected_old = list(unique_old.values())[:max(0, min(int(event_fixture_budget), 4))]
    target_minute = result.get("current_goal_minute")
    comeback_by_team: dict[int, dict[str, Any]] = {
        home["id"]: {"name": home.get("name"), "behind_cases": 0, "equalized": 0, "scored_after_conceding": 0, "sample": 0},
        away["id"]: {"name": away.get("name"), "behind_cases": 0, "equalized": 0, "scored_after_conceding": 0, "sample": 0},
    }
    for old in selected_old:
        old_id = (old.get("fixture") or {}).get("id")
        events = get_cached(f"events:{old_id}", "fixtures/events", {"fixture": old_id})
        goals_events = sorted(_goal_events(events), key=lambda event: _goal_minute(event) or 0)
        old_teams = old.get("teams") or {}
        home_id = (old_teams.get("home") or {}).get("id")
        away_id = (old_teams.get("away") or {}).get("id")
        if not home_id or not away_id or not goals_events:
            continue
        score_by_team = {home_id: 0, away_id: 0}
        for event in goals_events:
            scoring_id = (event.get("team") or {}).get("id")
            conceded_id = away_id if scoring_id == home_id else home_id if scoring_id == away_id else None
            event_minute = _goal_minute(event)
            if scoring_id not in score_by_team or conceded_id is None:
                continue
            score_by_team[scoring_id] += 1
            # A response sample starts when the team is behind immediately after this goal.
            if score_by_team[scoring_id] > score_by_team[conceded_id]:
                team_state = comeback_by_team.get(conceded_id)
                if team_state is not None:
                    if target_minute is None or event_minute is None or abs(event_minute - target_minute) <= 12:
                        team_state["behind_cases"] += 1
                        later_events = [e for e in goals_events if (_goal_minute(e) or 0) > (event_minute or 0)]
                        if any((e.get("team") or {}).get("id") == conceded_id for e in later_events):
                            team_state["scored_after_conceding"] += 1
                        # Equalized if their later goal brought the running score level.
                        temp_home, temp_away = score_by_team[home_id], score_by_team[away_id]
                        for later in later_events:
                            later_id = (later.get("team") or {}).get("id")
                            if later_id in score_by_team:
                                if later_id == home_id: temp_home += 1
                                else: temp_away += 1
                                if later_id == conceded_id and temp_home == temp_away:
                                    team_state["equalized"] += 1
                                    break
                        team_state["sample"] += 1
    result["comeback"] = comeback_by_team
    result["available"] = bool(home_recent or away_recent or h2h_done)
    if not result["available"]:
        result["notes"].append("No se obtuvo historial reciente suficiente para este análisis.")
    cache[key] = result
    return result
