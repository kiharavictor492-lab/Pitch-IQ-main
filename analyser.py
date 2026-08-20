"""
football_bot/analyser.py
=========================
Statistical prediction engine using data from the three free sources.
Uses a Poisson goal model for outcome probabilities.
"""

from __future__ import annotations
import math
import logging

logger = logging.getLogger(__name__)


# ─── Utilities ────────────────────────────────────────────────────────────────

def _s(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _poisson(lam: float, k: int) -> float:
    lam = max(0.01, lam)
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


# ─── Form parsing from football-data.org match objects ───────────────────────

def _parse_form_fdo(matches: list[dict], team_id: int) -> list[str]:
    """Extract W/D/L from football-data.org recent match objects."""
    form = []
    for m in matches:
        home_id = m.get("homeTeam", {}).get("id")
        score   = m.get("score", {}).get("fullTime", {})
        hg = _s(score.get("home"))
        ag = _s(score.get("away"))
        if home_id == team_id:
            form.append("W" if hg > ag else ("D" if hg == ag else "L"))
        else:
            form.append("W" if ag > hg else ("D" if hg == ag else "L"))
    return form[-5:]


def _form_score(results: list[str]) -> float:
    pts = {"W": 3, "D": 1, "L": 0}
    total = sum(pts.get(r, 0) for r in results)
    return total / 15.0


# ─── Poisson model ────────────────────────────────────────────────────────────

def _expected_goals(home_avgs: dict, away_avgs: dict) -> tuple[float, float]:
    """Dixon-Coles style attack/defence strength."""
    league_home = 1.45
    league_away = 1.15

    h_att = _s(home_avgs.get("avg_goals_scored"),   league_home) / league_home
    h_def = _s(home_avgs.get("avg_goals_conceded"),  league_away) / league_away
    a_att = _s(away_avgs.get("avg_goals_scored"),   league_away) / league_away
    a_def = _s(away_avgs.get("avg_goals_conceded"),  league_home) / league_home

    home_xg = h_att * a_def * league_home
    away_xg = a_att * h_def * league_away
    return round(max(0.3, home_xg), 2), round(max(0.3, away_xg), 2)


def _outcome_probs(home_xg: float, away_xg: float, max_g: int = 7):
    hw = draw = aw = 0.0
    for i in range(max_g):
        for j in range(max_g):
            p = _poisson(home_xg, i) * _poisson(away_xg, j)
            if   i > j: hw   += p
            elif i == j: draw += p
            else:        aw   += p
    total = hw + draw + aw
    return hw/total, draw/total, aw/total


def _over_under(home_xg: float, away_xg: float, line: float = 2.5, max_g: int = 10):
    over = sum(
        _poisson(home_xg, i) * _poisson(away_xg, j)
        for i in range(max_g) for j in range(max_g)
        if (i + j) > line
    )
    return round(over, 3), round(1 - over, 3)


def _btts(home_xg: float, away_xg: float) -> float:
    return round((1 - _poisson(home_xg, 0)) * (1 - _poisson(away_xg, 0)), 3)


# ─── Corners ─────────────────────────────────────────────────────────────────

def _corners(home_avgs: dict, away_avgs: dict) -> dict:
    hcf = _s(home_avgs.get("avg_corners_for"),     5.0)
    aca = _s(away_avgs.get("avg_corners_against"),  5.0)
    acf = _s(away_avgs.get("avg_corners_for"),      5.0)
    hca = _s(home_avgs.get("avg_corners_against"),  5.0)
    expected = ((hcf + aca) / 2) + ((acf + hca) / 2)
    line = 9.5
    over_prob = min(0.92, max(0.08, (expected - line + 6) / 12))
    return {
        "expected_total": round(expected, 1),
        "over_line":      line,
        "over_prob":      round(over_prob, 2),
        "under_prob":     round(1 - over_prob, 2),
    }


# ─── Penalty ─────────────────────────────────────────────────────────────────

def _penalty_prob(home_avgs: dict, away_avgs: dict) -> float:
    # Rough estimate: ~0.22 base, boosted by high shots on target
    h_sot = _s(home_avgs.get("avg_shots_on_target"), 4.0)
    a_sot = _s(away_avgs.get("avg_shots_on_target"), 4.0)
    prob = 0.12 + ((h_sot + a_sot) / 100)
    return round(min(0.55, max(0.10, prob)), 2)


# ─── H2H from OpenFootball ────────────────────────────────────────────────────

def _h2h_summary(h2h: list[dict], home_name: str, away_name: str) -> dict:
    hw = draws = aw = goals = 0
    h = home_name.lower().replace(" fc", "").strip()

    for m in h2h:
        t1   = m.get("team1", "").lower()
        sc   = m.get("score", {})
        ft   = sc.get("ft", [0, 0]) if isinstance(sc, dict) else [0, 0]
        try:
            g1, g2 = int(ft[0]), int(ft[1])
        except Exception:
            continue
        goals += g1 + g2
        if h in t1:
            if g1 > g2: hw    += 1
            elif g1 == g2: draws += 1
            else:          aw    += 1
        else:
            if g2 > g1: hw    += 1
            elif g1 == g2: draws += 1
            else:          aw    += 1

    n = max(len(h2h), 1)
    return {
        "matches":    len(h2h),
        "home_wins":  hw,
        "draws":      draws,
        "away_wins":  aw,
        "avg_goals":  round(goals / n, 2),
    }


# ─── Standing helpers ─────────────────────────────────────────────────────────

def _standing_info(standing: dict) -> dict:
    if not standing:
        return {"position": "?", "points": 0, "gd": 0}
    return {
        "position": standing.get("position", "?"),
        "points":   standing.get("points", 0),
        "gd":       standing.get("goalDifference", 0),
    }


# ─── Confidence ──────────────────────────────────────────────────────────────

def _confidence(hw: float, aw: float, d: float,
                hfs: float, afs: float, h2h: dict) -> int:
    top    = max(hw, aw, d)
    second = sorted([hw, aw, d])[-2]
    spread = top - second
    form   = abs(hfs - afs)
    h2h_c  = abs(h2h["home_wins"] - h2h["away_wins"]) / max(h2h["matches"], 1)
    score  = (top * 40) + (spread * 30) + (form * 20) + (h2h_c * 10)
    return min(95, max(30, round(score * 100)))


# ─── Main ─────────────────────────────────────────────────────────────────────

def analyse(enriched: dict) -> dict:
    home_avgs = enriched.get("home_avgs", {})
    away_avgs = enriched.get("away_avgs", {})
    home_id   = enriched["home"]["id"]
    away_id   = enriched["away"]["id"]

    home_form = _parse_form_fdo(enriched.get("home_recent", []), home_id)
    away_form = _parse_form_fdo(enriched.get("away_recent", []), away_id)
    hfs       = _form_score(home_form)
    afs       = _form_score(away_form)

    home_xg, away_xg = _expected_goals(home_avgs, away_avgs)
    hw, d, aw        = _outcome_probs(home_xg, away_xg)
    go, gu           = _over_under(home_xg, away_xg)
    btts_p           = _btts(home_xg, away_xg)
    corners          = _corners(home_avgs, away_avgs)
    pen_p            = _penalty_prob(home_avgs, away_avgs)

    h2h_sum = _h2h_summary(
        enriched.get("h2h", []),
        enriched["home"]["name"],
        enriched["away"]["name"],
    )
    conf = _confidence(hw, aw, d, hfs, afs, h2h_sum)

    outcomes = [("Home Win", hw), ("Draw", d), ("Away Win", aw)]
    top_outcome, top_prob = max(outcomes, key=lambda x: x[1])

    return {
        # Identity
        "fixture_id":    enriched["fixture_id"],
        "kickoff_utc":   enriched["kickoff_utc"],
        "venue":         enriched["venue"],
        "league":        enriched["league_name"],
        "home_team":     enriched["home"]["name"],
        "away_team":     enriched["away"]["name"],

        # Outcome probs
        "home_win_prob": round(hw, 3),
        "draw_prob":     round(d,  3),
        "away_win_prob": round(aw, 3),
        "top_outcome":   top_outcome,
        "top_prob":      round(top_prob, 3),

        # Goals
        "home_xg":       home_xg,
        "away_xg":       away_xg,
        "goals_over_25": go,
        "goals_under_25": gu,
        "btts_prob":     btts_p,

        # Corners & Penalties
        "corners":       corners,
        "penalty_prob":  pen_p,

        # Form
        "home_form":      home_form,
        "away_form":      away_form,
        "home_form_score": hfs,
        "away_form_score": afs,

        # H2H
        "h2h": h2h_sum,

        # VIP extras
        "confidence":  conf,
        "injuries":    [],   # Not available in free tier
        "api_advice":  "",

        # Standings
        "home_standing": _standing_info(enriched.get("home_standing", {})),
        "away_standing": _standing_info(enriched.get("away_standing", {})),

        # Raw averages for AI narrator
        "home_avgs": home_avgs,
        "away_avgs": away_avgs,
    }