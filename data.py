"""
data.py — Sofascore data layer.

Switched from FBref to Sofascore because FBref's reader in soccerdata
(`BaseSeleniumReader`) drives a real Chrome/ChromeDriver instance, which is
what was failing on the VPS ("Chrome not found!"). Sofascore's reader
(`BaseRequestsReader`) talks to Sofascore's public JSON API over HTTPS using
a TLS-fingerprint-spoofing HTTP client (`tls_requests`) — no browser, no
Selenium, nothing to install beyond the Python package.

soccerdata's high-level `Sofascore.read_schedule()` only covers the handful
of competitions present in its bundled league_dict (the Big 5 + Euros), which
is far short of the 11 competitions this project tracks. To get full
coverage we call Sofascore's underlying REST endpoints directly — by
numeric tournament ID rather than canonical league name — while still
routing every request through the `sd.Sofascore` instance's `.get()` method
so we inherit its session reuse, retry-on-failure, and rate-limit handling.
"""

import os

# Must be set before importing soccerdata — read once at module import time.
os.environ.setdefault("SOCCERDATA_LOGLEVEL", "WARNING")

import json
import time
from datetime import date, datetime, timezone
from difflib import get_close_matches

import soccerdata as sd

from logger import log

SOFASCORE_API = "https://api.sofascore.com/api/v1/"

# Maps our internal competition label -> Sofascore numeric uniqueTournament
# ID(s). IDs were resolved by walking Sofascore's category/unique-tournaments
# endpoints (England=1, Spain=32, Italy=31, Germany=30, France=7, Europe=1465,
# USA=26, Mexico=12, Netherlands=35, Portugal=44) and are verified against
# live data, not guessed from tournament names.
#
# Exact-ID matching is used instead of fuzzy name matching because many
# countries have generically named top divisions ("Premier League",
# "Primeira Liga", "Primera ...") that collide under fuzzy matching — e.g. a
# Canadian Premier League fixture would otherwise be misfiled as the English
# Premier League. Liga MX maps to two IDs because Sofascore splits the
# Mexican season into separate Apertura/Clausura tournaments.
COMPETITIONS = {
    "Premier League":   [17],
    "La Liga":          [8],
    "Serie A":          [23],
    "Bundesliga":       [35],
    "Ligue 1":          [34],
    "Champions League": [7],
    "Europa League":    [679],
    "MLS":              [242],
    "Liga MX":          [11621, 11620],  # Apertura, Clausura
    "Eredivisie":       [37],
    "Primeira Liga":    [238],
}

# Reverse lookup: Sofascore tournament ID (str) -> our competition label
_TOURNAMENT_ID_TO_COMPETITION = {
    str(tid): label for label, ids in COMPETITIONS.items() for tid in ids
}

# In-process cache: (league_id, season_id) -> list of match dicts.
# Avoids re-fetching an entire season's rounds once per match when several
# matches from the same league are analyzed back-to-back in one pipeline run.
_schedule_cache: dict[tuple[str, str], list[dict]] = {}

_sofa_instance: "sd.Sofascore | None" = None


def _get_sofascore() -> sd.Sofascore:
    """Returns a lazily-created, reused Sofascore reader instance."""
    global _sofa_instance
    if _sofa_instance is None:
        _sofa_instance = sd.Sofascore()
    return _sofa_instance


def _sofa_get_json(url: str) -> dict:
    """GETs a Sofascore API endpoint as JSON via soccerdata's session/retry machinery."""
    sofa = _get_sofascore()
    reader = sofa.get(url, filepath=None, no_cache=True)
    return json.load(reader)


def _find_close_match(name: str, candidates: list, cutoff: float = 0.6):
    """Returns the closest fuzzy match for `name` among `candidates`, or None."""
    if not name or not candidates:
        return None
    matches = get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


# ── get_todays_matches ───────────────────────────────────────────────────────

def get_todays_matches() -> list[dict]:
    """
    Fetches every match scheduled for today across all of Sofascore's
    tracked sports/competitions, then filters down to COMPETITIONS.

    Returns a deduplicated list of match dicts. Returns [] if Sofascore is
    unreachable or no tracked matches are found today.
    """
    today_str = date.today().strftime("%Y-%m-%d")
    results = []
    seen = set()

    try:
        data = _sofa_get_json(f"{SOFASCORE_API}sport/football/scheduled-events/{today_str}")
    except Exception as e:
        log.error(f"Sofascore unreachable while fetching today's schedule: {e}")
        return []

    events = data.get("events", [])

    for event in events:
        try:
            tournament = event.get("tournament") or {}
            unique_t = tournament.get("uniqueTournament") or {}
            tournament_id = str(unique_t.get("id") or tournament.get("id") or "")

            competition_name = _TOURNAMENT_ID_TO_COMPETITION.get(tournament_id)
            if not competition_name:
                continue

            home = event["homeTeam"]["name"]
            away = event["awayTeam"]["name"]

            ts = event.get("startTimestamp")
            time_utc = (
                datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")
                if ts else "Por confirmar"
            )

            season_info = event.get("season") or {}
            season = str(season_info.get("year") or season_info.get("name") or "")

            league_id = tournament_id
            match_id = str(event.get("id", ""))

            if not home or not away or not league_id:
                continue

            key = (home, away, competition_name)
            if key in seen:
                continue
            seen.add(key)

            results.append({
                "home": home,
                "away": away,
                "competition": competition_name,
                "time_utc": time_utc,
                "season": season,
                "league_id": league_id,
                "match_id": match_id,
            })

        except Exception as e:
            log.warning(f"Skipping malformed Sofascore event row: {e}")
            continue

    log.info(f"Found {len(results)} tracked matches today via Sofascore")
    return results


# ── get_team_stats ────────────────────────────────────────────────────────────

def _resolve_season_id(league_id: str, season: str) -> str | None:
    """Resolves a Sofascore numeric season_id from the display season string."""
    try:
        data = _sofa_get_json(f"{SOFASCORE_API}unique-tournament/{league_id}/seasons")
    except Exception as e:
        log.warning(f"Could not fetch seasons list for league {league_id}: {e}")
        return None

    seasons = data.get("seasons", [])
    if not seasons:
        return None

    for s in seasons:
        if str(s.get("year")) == season or str(s.get("name")) == season:
            return str(s["id"])

    log.warning(f"Season '{season}' not found for league {league_id}; using most recent season")
    return str(seasons[0]["id"])


def _fetch_tournament_matches(league_id: str, season_id: str) -> list[dict]:
    """Fetches every match (played and scheduled) for a tournament/season, round by round."""
    matches = []

    try:
        rounds_data = _sofa_get_json(
            f"{SOFASCORE_API}unique-tournament/{league_id}/season/{season_id}/rounds"
        )
    except Exception as e:
        log.warning(f"Could not fetch rounds for league {league_id}/{season_id}: {e}")
        return matches
    time.sleep(2)

    for rnd in rounds_data.get("rounds", []):
        round_num = rnd.get("round")
        try:
            round_data = _sofa_get_json(
                f"{SOFASCORE_API}unique-tournament/{league_id}/season/{season_id}/events/round/{round_num}"
            )
        except Exception as e:
            log.warning(f"Could not fetch round {round_num} for league {league_id}: {e}")
            continue
        time.sleep(2)

        for ev in round_data.get("events", []):
            try:
                status_code = (ev.get("status") or {}).get("code")
                is_finished = status_code == 100
                home_score = (ev.get("homeScore") or {}).get("current") if is_finished else None
                away_score = (ev.get("awayScore") or {}).get("current") if is_finished else None

                matches.append({
                    "date": datetime.fromtimestamp(ev["startTimestamp"], tz=timezone.utc),
                    "home_team": ev["homeTeam"]["name"],
                    "away_team": ev["awayTeam"]["name"],
                    "home_score": home_score,
                    "away_score": away_score,
                    "finished": is_finished,
                })
            except Exception as e:
                log.warning(f"Skipping malformed match row in round {round_num}: {e}")
                continue

    return matches


def _completed(matches: list[dict]) -> list[dict]:
    return [m for m in matches if m["finished"] and m["home_score"] is not None]


def _team_last5(matches: list[dict], team_name: str) -> list[dict]:
    finished = _completed(matches)
    all_names = list({m["home_team"] for m in finished} | {m["away_team"] for m in finished})
    resolved = _find_close_match(team_name, all_names) or team_name

    team_matches = sorted(
        (m for m in finished if m["home_team"] == resolved or m["away_team"] == resolved),
        key=lambda m: m["date"],
    )[-5:]

    last5 = []
    for m in team_matches:
        is_home = m["home_team"] == resolved
        gf = m["home_score"] if is_home else m["away_score"]
        ga = m["away_score"] if is_home else m["home_score"]
        opponent = m["away_team"] if is_home else m["home_team"]
        result = "W" if gf > ga else ("D" if gf == ga else "L")
        last5.append({
            "opponent": opponent,
            "result": result,
            "goals_for": gf,
            "goals_against": ga,
        })
    return last5


def _team_h2h(matches: list[dict], home_team: str, away_team: str) -> list[dict]:
    finished = _completed(matches)
    all_names = list({m["home_team"] for m in finished} | {m["away_team"] for m in finished})
    home_r = _find_close_match(home_team, all_names) or home_team
    away_r = _find_close_match(away_team, all_names) or away_team

    h2h_matches = sorted(
        (m for m in finished if {m["home_team"], m["away_team"]} == {home_r, away_r}),
        key=lambda m: m["date"],
    )[-5:]

    return [
        {
            "date": m["date"].strftime("%Y-%m-%d"),
            "home": m["home_team"],
            "away": m["away_team"],
            "score": f"{m['home_score']}-{m['away_score']}",
        }
        for m in h2h_matches
    ]


def _team_goal_averages(matches: list[dict], team_name: str):
    finished = _completed(matches)
    all_names = list({m["home_team"] for m in finished} | {m["away_team"] for m in finished})
    resolved = _find_close_match(team_name, all_names) or team_name

    scored, conceded = [], []
    for m in finished:
        if m["home_team"] == resolved:
            scored.append(m["home_score"])
            conceded.append(m["away_score"])
        elif m["away_team"] == resolved:
            scored.append(m["away_score"])
            conceded.append(m["home_score"])

    if not scored:
        return None, None
    return round(sum(scored) / len(scored), 3), round(sum(conceded) / len(conceded), 3)


def _league_goal_averages(matches: list[dict]):
    finished = _completed(matches)
    if not finished:
        return 1.5, 1.2
    home_avg = sum(m["home_score"] for m in finished) / len(finished)
    away_avg = sum(m["away_score"] for m in finished) / len(finished)
    return round(home_avg, 3), round(away_avg, 3)


def _fetch_standings_positions(league_id: str, season_id: str) -> dict:
    """Returns {team_name: position} for a tournament/season."""
    positions = {}
    try:
        data = _sofa_get_json(
            f"{SOFASCORE_API}unique-tournament/{league_id}/season/{season_id}/standings/total"
        )
        rows = (data.get("standings") or [{}])[0].get("rows", [])
        for idx, row in enumerate(rows, start=1):
            team_name = (row.get("team") or {}).get("name", "")
            if team_name:
                positions[team_name] = row.get("position", idx)
    except Exception as e:
        log.warning(f"Could not fetch standings for league {league_id}/{season_id}: {e}")
    return positions


def get_team_stats(home_team: str, away_team: str, league_id: str, season: str) -> dict:
    """
    Fetches form, H2H, season averages, and league position for both teams
    via Sofascore. Always returns the full stats dict, with fallback
    defaults (1.5 / 1.2 league averages) when data is partially or fully
    unavailable, so model.py and analyzer.py can proceed regardless.
    """
    stats = {
        "home_team": home_team,
        "away_team": away_team,
        "home_goals_scored_avg": None,
        "home_goals_conceded_avg": None,
        "away_goals_scored_avg": None,
        "away_goals_conceded_avg": None,
        "home_last5": [],
        "away_last5": [],
        "h2h": [],
        "home_league_pos": None,
        "away_league_pos": None,
        "league_avg_goals_home": 1.5,
        "league_avg_goals_away": 1.2,
    }

    if not league_id:
        log.warning(f"No league_id provided for {home_team} vs {away_team}; using fallback stats")
        return stats

    try:
        season_id = _resolve_season_id(league_id, season)
        time.sleep(2)
    except Exception as e:
        log.warning(f"Could not resolve season for league {league_id}/{season}: {e}")
        season_id = None

    if season_id is None:
        log.warning(f"No season id resolved for league {league_id}/{season}; using fallback stats")
        return stats

    cache_key = (league_id, season_id)
    try:
        if cache_key in _schedule_cache:
            matches = _schedule_cache[cache_key]
        else:
            matches = _fetch_tournament_matches(league_id, season_id)
            _schedule_cache[cache_key] = matches
    except Exception as e:
        log.warning(f"Could not fetch tournament matches for {league_id}/{season_id}: {e}")
        matches = []

    if matches:
        try:
            stats["home_last5"] = _team_last5(matches, home_team)
            stats["away_last5"] = _team_last5(matches, away_team)
            stats["h2h"] = _team_h2h(matches, home_team, away_team)

            stats["home_goals_scored_avg"], stats["home_goals_conceded_avg"] = (
                _team_goal_averages(matches, home_team)
            )
            stats["away_goals_scored_avg"], stats["away_goals_conceded_avg"] = (
                _team_goal_averages(matches, away_team)
            )

            stats["league_avg_goals_home"], stats["league_avg_goals_away"] = (
                _league_goal_averages(matches)
            )
        except Exception as e:
            log.warning(f"Could not derive form/averages for {home_team} vs {away_team}: {e}")
    else:
        log.warning(f"No match data available for league {league_id}/season {season_id}")

    try:
        time.sleep(2)
        positions = _fetch_standings_positions(league_id, season_id)
        all_names = list(positions.keys())
        home_r = _find_close_match(home_team, all_names)
        away_r = _find_close_match(away_team, all_names)
        stats["home_league_pos"] = positions.get(home_r) if home_r else None
        stats["away_league_pos"] = positions.get(away_r) if away_r else None
    except Exception as e:
        log.warning(f"Could not fetch standings for {home_team} vs {away_team}: {e}")

    return stats


if __name__ == "__main__":
    print("Testing Sofascore API...")
    matches = get_todays_matches()
    print(f"Found {len(matches)} matches today")
    for m in matches[:3]:
        print(f"  {m['home']} vs {m['away']} — {m['competition']}")

    if matches:
        print("\nTesting stats for first match...")
        m = matches[0]
        stats = get_team_stats(m["home"], m["away"], m["league_id"], m["season"])
        print(f"  Home avg goals scored: {stats['home_goals_scored_avg']}")
        print(f"  Away avg goals scored: {stats['away_goals_scored_avg']}")
        print(f"  H2H matches found: {len(stats['h2h'])}")
        print(f"  Home last 5: {stats['home_last5']}")
