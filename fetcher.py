"""
football_bot/fetcher.py
========================
100% FREE data sources:
  1. football-data.org  → live fixtures, standings, team form (free API key)
  2. football-data.co.uk → historical CSV stats (corners, goals, shots) - no key needed
  3. OpenFootball (GitHub JSON) → H2H historical results - no key needed
"""

import requests
import csv
import io
import time
import logging
from datetime import datetime, timezone ,timedelta
from config import FOOTBALL_DATA_ORG_KEY, TRACKED_LEAGUE_CODES

logger = logging.getLogger(__name__)

# ─── Base URLs ────────────────────────────────────────────────────────────────
FDO_BASE          = "https://api.football-data.org/v4"
FDO_HEADERS       = {"X-Auth-Token": FOOTBALL_DATA_ORG_KEY}
FDCOUK_BASE       = "https://www.football-data.co.uk/mmz4281"
OPENFOOTBALL_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master"

# ─── Session caches (loaded once, reused for all fixtures) ───────────────────
_csv_cache:          dict = {}
_standings_cache:    dict = {}
_openfootball_cache: dict = {}

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1: football-data.org  (fixtures, form, standings)
# ══════════════════════════════════════════════════════════════════════════════

def _fdo_get(path: str, params: dict = {}) -> dict:
    try:
        r = requests.get(
            f"{FDO_BASE}/{path}",
            headers=FDO_HEADERS,
            params=params,
            timeout=20,
        )
        time.sleep(6)  # 6 seconds between calls — free tier allows 10/min

        if r.status_code == 429:
            logger.warning("Rate limit hit — waiting 60s...")
            time.sleep(60)
            r = requests.get(f"{FDO_BASE}/{path}", headers=FDO_HEADERS, params=params, timeout=20)
            time.sleep(6)

        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"football-data.org error [{path}]: {e}")
        return {}
 
 
def get_todays_fixtures() -> list[dict]:
    """Fetch today's scheduled matches. One request per league."""
    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    all_fixtures = []
 
    for i, league_code in enumerate(TRACKED_LEAGUE_CODES):
        logger.info(f"Fetching fixtures [{i+1}/{len(TRACKED_LEAGUE_CODES)}]: {league_code}")
        data = _fdo_get(f"competitions/{league_code}/matches", {
            "dateFrom": today,
            "dateTo":   tomorrow,
            "status":   "SCHEDULED",
        })
        matches = data.get("matches", [])
        logger.info(f"  → {len(matches)} fixtures")
        for m in matches:
            all_fixtures.append(_normalise_match(m, league_code))
 
    all_fixtures.sort(key=lambda f: f["kickoff_utc"])
    return all_fixtures
 
 
def _normalise_match(m: dict, league_code: str) -> dict:
    home = m.get("homeTeam", {})
    away = m.get("awayTeam", {})
    comp = m.get("competition", {})
    return {
        "fixture_id":  m.get("id"),
        "kickoff_utc": m.get("utcDate", ""),
        "venue":       home.get("venue", "Home Ground"),
        "league_name": comp.get("name", league_code),
        "league_code": league_code,
        "season":      str(m.get("season", {}).get("startDate", ""))[:4],
        "home": {
            "id":    home.get("id"),
            "name":  home.get("name", "Home"),
            "short": home.get("shortName", home.get("name", "")),
        },
        "away": {
            "id":    away.get("id"),
            "name":  away.get("name", "Away"),
            "short": away.get("shortName", away.get("name", "")),
        },
        "raw": m,
    }
 
 
def get_team_recent_matches(team_id: int, last: int = 5) -> list[dict]:
    """One API call — rate limited."""
    logger.info(f"  Fetching recent matches for team {team_id}...")
    data = _fdo_get(f"teams/{team_id}/matches", {"status": "FINISHED", "limit": last})
    return data.get("matches", [])
 
 
def get_standings(league_code: str) -> list[dict]:
    """Cached standings — only fetches once per league per session."""
    if league_code in _standings_cache:
        return _standings_cache[league_code]
 
    logger.info(f"  Fetching standings for {league_code}...")
    data = _fdo_get(f"competitions/{league_code}/standings")
    try:
        table = data["standings"][0]["table"]
    except Exception:
        table = []
 
    _standings_cache[league_code] = table
    return table

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2: football-data.co.uk  (historical CSV – goals, corners, shots)
# ══════════════════════════════════════════════════════════════════════════════

# Season CSV paths — update season folder (2425 = 2024/25) each year
FDCOUK_PATHS = {
    "PL":  "2425/E0.csv",   # Premier League
    "BL1": "2425/D1.csv",   # Bundesliga
    "SA":  "2425/I1.csv",   # Serie A
    "PD":  "2425/SP1.csv",  # La Liga
    "FL1": "2425/F1.csv",   # Ligue 1
    "DED": "2425/N1.csv",   # Eredivisie
    "PPL": "2425/P1.csv",   # Primeira Liga
    "ELC": "2425/E1.csv",   # Championship
}


def _load_csv(league_code: str) -> list[dict]:
    path = FDCOUK_PATHS.get(league_code)
    if not path:
        return []
    url = f"{FDCOUK_BASE}/{path}"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
        return [row for row in reader if row.get("HomeTeam")]
    except Exception as e:
        logger.error(f"football-data.co.uk error [{league_code}]: {e}")
        return []


def compute_team_averages(team_name: str, league_code: str, last: int = 15) -> dict:
    """
    Returns average goals, corners, shots on target for a team
    using football-data.co.uk CSV data.
    """
    all_rows = _load_csv(league_code)
    # Match team name loosely
    # Clean and shorten name for fuzzy matching against CSV
    name = team_name.lower()
    name = name.replace(" fc", "").replace(" cf", "").replace(" bc", "")
    name = name.replace(" milano", "").replace(" madrid", "").replace(" munich", "")
    name = name.replace("münchen", "munich").replace("internazionale", "inter")
    name = name.replace("atletico", "atl").replace("athletic club", "ath bilbao")
    name = name.replace("athletic", "ath").replace("manchester", "man")
    name = name.replace("paris saint-germain", "psg").replace("paris sg", "psg")
    name = name.strip()
    # Use only first word if still no match — last resort
    short = name.split()[0] if name else name
    rows = [
        r for r in all_rows
        if name  in r.get("HomeTeam", "").lower()
        or name  in r.get("AwayTeam", "").lower()
        or short in r.get("HomeTeam", "").lower()
        or short in r.get("AwayTeam", "").lower()
    ][-last:]

    if not rows:
        logger.warning(f"No CSV data found for '{team_name}' in {league_code}")
        return _default_avgs()
    team_rows = rows
    gs = gc = cf = ca = sot = 0
    n = 0
    for r in team_rows:
        try:
            is_home = name in r.get("HomeTeam", "").lower()
            gs  += int(r["FTHG"] if is_home else r["FTAG"] or 0)
            gc  += int(r["FTAG"] if is_home else r["FTHG"] or 0)
            cf  += int(r.get("HC" if is_home else "AC", 0) or 0)
            ca  += int(r.get("AC" if is_home else "HC", 0) or 0)
            sot += int(r.get("HST" if is_home else "AST", 0) or 0)
            n   += 1
        except Exception:
            continue

    if n == 0:
        return _default_avgs()

    return {
        "avg_goals_scored":    round(gs  / n, 2),
        "avg_goals_conceded":  round(gc  / n, 2),
        "avg_corners_for":     round(cf  / n, 2),
        "avg_corners_against": round(ca  / n, 2),
        "avg_shots_on_target": round(sot / n, 2),
        "matches_analysed":    n,
    }


def _default_avgs() -> dict:
    return {
        "avg_goals_scored":    1.3,
        "avg_goals_conceded":  1.2,
        "avg_corners_for":     5.0,
        "avg_corners_against": 5.0,
        "avg_shots_on_target": 4.0,
        "matches_analysed":    0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3: OpenFootball GitHub JSON  (H2H results)
# ══════════════════════════════════════════════════════════════════════════════

OPENFOOTBALL_FILES = {
    "PL":  "2024-25/en.1.json",
    "BL1": "2024-25/de.1.json",
    "SA":  "2024-25/it.1.json",
    "PD":  "2024-25/es.1.json",
    "FL1": "2024-25/fr.1.json",
}


def get_h2h(home_name: str, away_name: str, league_code: str, last: int = 8) -> list[dict]:
    """Fetch head-to-head results from OpenFootball GitHub JSON."""
    path = OPENFOOTBALL_FILES.get(league_code)
    if not path:
        return []
    url = f"{OPENFOOTBALL_BASE}/{path}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"OpenFootball error: {e}")
        return []

    h2h = []
    h = home_name.lower().replace(" fc", "").strip()
    a = away_name.lower().replace(" fc", "").strip()

    for rnd in data.get("rounds", []):
        for match in rnd.get("matches", []):
            t1 = match.get("team1", "").lower()
            t2 = match.get("team2", "").lower()
            if (h in t1 and a in t2) or (h in t2 and a in t1):
                h2h.append(match)

    return h2h[-last:]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Enrich fixture  (combines all three sources)
# ══════════════════════════════════════════════════════════════════════════════

def enrich_fixture(fixture: dict) -> dict:
    """Attach all stats to a fixture dict. Ready for the analyser."""
    lc   = fixture["league_code"]
    home = fixture["home"]
    away = fixture["away"]

    logger.info(f"Enriching: {home['name']} vs {away['name']} [{lc}]")

    home_recent   = get_team_recent_matches(home["id"], last=5)
    away_recent   = get_team_recent_matches(away["id"], last=5)
    home_avgs     = compute_team_averages(home["short"] or home["name"], lc)
    away_avgs     = compute_team_averages(away["short"] or away["name"], lc)
    h2h           = get_h2h(home["name"], away["name"], lc)
    standings     = get_standings(lc)
    home_standing = next((t for t in standings if t.get("team", {}).get("id") == home["id"]), {})
    away_standing = next((t for t in standings if t.get("team", {}).get("id") == away["id"]), {})

    return {
        **fixture,
        "home_recent":    home_recent,
        "away_recent":    away_recent,
        "home_avgs":      home_avgs,
        "away_avgs":      away_avgs,
        "h2h":            h2h,
        "home_standing":  home_standing,
        "away_standing":  away_standing,
    }