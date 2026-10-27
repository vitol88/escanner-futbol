"""Empirical remaining-corner frequencies from minute-level historical data."""
from __future__ import annotations

from typing import Any


def estimate_remaining_corners(
    rows: list[dict[str, Any]],
    *,
    league: str,
    team: str,
    venue: str,
    minute: int,
    corners_for: int,
    corners_against: int,
    minimum_matches: int = 8,
) -> dict[str, Any]:
    """Estimate additional-corner frequencies from rows at the same cutoff.

    Required row fields: league, team, venue (home/away), minute, corners_for,
    corners_against, corners_for_after, corners_against_after. Rows represent a
    completed historical fixture from one team's perspective. This estimator
    reports empirical frequencies, not calibrated probabilities.
    """
    def norm(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    valid = []
    target_league, target_team = norm(league), norm(team)
    target_venue = norm(venue)
    for row in rows:
        try:
            row_minute = int(row.get("minute"))
            cf = int(row.get("corners_for"))
            ca = int(row.get("corners_against"))
            after_for = int(row.get("corners_for_after"))
            after_against = int(row.get("corners_against_after"))
        except (TypeError, ValueError):
            continue
        if min(row_minute, cf, ca, after_for, after_against) < 0:
            continue
        if norm(row.get("league")) != target_league or norm(row.get("team")) != target_team:
            continue
        if row_minute != minute:
            continue
        row_venue = norm(row.get("venue"))
        if row_venue not in ("home", "away", "local", "visitante"):
            continue
        valid.append({
            "venue": row_venue,
            "corners_for": cf,
            "corners_against": ca,
            "corners_for_after": after_for,
            "corners_against_after": after_against,
        })

    venue_rows = [r for r in valid if r["venue"] == target_venue or
                  (target_venue == "home" and r["venue"] == "local") or
                  (target_venue == "away" and r["venue"] == "visitante")]
    exact = [r for r in venue_rows if r["corners_for"] == corners_for and r["corners_against"] == corners_against]
    exact_used = len(exact) >= minimum_matches
    sample = exact if exact_used else venue_rows
    if len(sample) < minimum_matches:
        return {
            "available": False,
            "sample_size": len(sample),
            "reason": f"Muestra insuficiente: {len(sample)} partidos; se requieren {minimum_matches}.",
        }

    total_after = [r["corners_for_after"] + r["corners_against_after"] for r in sample]
    team_after = [r["corners_for_after"] for r in sample]
    return {
        "available": True,
        "sample_size": len(sample),
        "matched_exact_state": exact_used,
        "prob_at_least_1_corner": sum(n >= 1 for n in total_after) / len(sample),
        "prob_at_least_2_corners": sum(n >= 2 for n in total_after) / len(sample),
        "prob_team_gets_corner": sum(n >= 1 for n in team_after) / len(sample),
        "mean_corners_after": sum(total_after) / len(sample),
        "reason": None if exact_used else "Muestra por córners al corte insuficiente; se usa la muestra del equipo y sede en esa liga y minuto.",
    }
