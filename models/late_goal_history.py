"""Empirical late-goal rates from a match-by-team historical event dataset."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def estimate_late_goals_from_history(
    rows: list[dict[str, Any]],
    *,
    league: str,
    team: str,
    minute: int,
    score_for: int,
    score_against: int,
    minimum_matches: int = 8,
) -> dict[str, Any]:
    """Estimate post-minute goal frequencies for similar team/score states.

    Each row represents one team's perspective in one completed match at a cutoff:
    league, team, minute, score_for, score_against, goals_for_after, goals_against_after.
    Exact minute and score state are matched first; a league/team/minute fallback is
    returned only when the exact state has too few matches. These are frequencies,
    not calibrated probabilities.
    """
    def norm(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    target_league, target_team = norm(league), norm(team)
    valid = []
    for row in rows:
        try:
            row_minute = int(row.get("minute"))
            row_for = int(row.get("score_for"))
            row_against = int(row.get("score_against"))
            after_for = int(row.get("goals_for_after"))
            after_against = int(row.get("goals_against_after"))
        except (TypeError, ValueError):
            continue
        if min(row_minute, row_for, row_against, after_for, after_against) < 0:
            continue
        if norm(row.get("league")) != target_league or norm(row.get("team")) != target_team:
            continue
        if row_minute != minute:
            continue
        valid.append({
            "score_for": row_for, "score_against": row_against,
            "goals_for_after": after_for, "goals_against_after": after_against,
        })

    exact = [r for r in valid if r["score_for"] == score_for and r["score_against"] == score_against]
    used_exact_state = len(exact) >= minimum_matches
    sample = exact if used_exact_state else valid
    if len(sample) < minimum_matches:
        return {
            "available": False,
            "reason": f"Muestra insuficiente: {len(sample)} partidos; se requieren {minimum_matches}.",
            "sample_size": len(sample),
        }

    total_after = [r["goals_for_after"] + r["goals_against_after"] for r in sample]
    team_after = [r["goals_for_after"] for r in sample]
    return {
        "available": True,
        "sample_size": len(sample),
        "matched_exact_score": used_exact_state,
        "prob_at_least_1_goal": sum(n >= 1 for n in total_after) / len(sample),
        "prob_at_least_2_goals": sum(n >= 2 for n in total_after) / len(sample),
        "prob_team_scores_again": sum(n >= 1 for n in team_after) / len(sample),
        "mean_goals_after": sum(total_after) / len(sample),
        "reason": None if used_exact_state else "Muestra por marcador insuficiente; se usa la frecuencia del equipo en esa liga y minuto.",
    }
