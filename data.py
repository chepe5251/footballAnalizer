"""
data.py — ESPN public API only.
Usa /scoreboard para partidos del dia y /summary para stats completas.
Sin football-data, sin soccerdata, sin Chrome.
"""

import requests
from datetime import date
from logger import log

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def _parse_score(score_obj) -> int:
    if isinstance(score_obj, dict):
        return int(float(score_obj.get("value", 0)))
    try:
        return int(float(score_obj))
    except:
        return 0


def _stat(statistics: list, name: str):
    for s in statistics:
        if s.get("name") == name:
            try:
                return float(s.get("displayValue", "0").replace("%", ""))
            except:
                return None
    return None


def _moneyline_to_decimal(ml) -> float | None:
    """Convert American moneyline odds to decimal odds."""
    try:
        ml = float(ml)
        if ml > 0:
            return round(ml / 100 + 1, 2)
        else:
            return round(100 / abs(ml) + 1, 2)
    except:
        return None


def get_todays_matches() -> list[dict]:
    url = f"{ESPN_BASE}/all/scoreboard"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        log.error(f"ESPN scoreboard error: {e}")
        return []

    matches = []
    for event in data.get("events", []):
        try:
            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])

            home_data = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_data = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home_data or not away_data:
                continue

            home_team = home_data.get("team", {}).get("displayName", "Unknown")
            away_team = away_data.get("team", {}).get("displayName", "Unknown")
            home_id   = home_data.get("team", {}).get("id", "")
            away_id   = away_data.get("team", {}).get("id", "")

            uid = event.get("uid", "")
            league_id = "all"
            for part in uid.split("~"):
                if part.startswith("l:"):
                    league_id = part[2:]

            competition = comp.get("altGameNote", "") or event.get("name", "Unknown")
            state       = comp.get("status", {}).get("type", {}).get("state", "pre")

            matches.append({
                "home":            home_team,
                "away":            away_team,
                "home_id":         home_id,
                "away_id":         away_id,
                "competition":     competition,
                "time_utc":        event.get("date", "TBD"),
                "season":          str(event.get("season", {}).get("year", date.today().year)),
                "league_id":       league_id,
                "espn_id":         event.get("id", ""),
                "state":           state,
                "home_score":      _parse_score(home_data.get("score", 0)),
                "away_score":      _parse_score(away_data.get("score", 0)),
                "home_form":       home_data.get("form", ""),
                "away_form":       away_data.get("form", ""),
                "home_possession": _stat(home_data.get("statistics", []), "possessionPct"),
                "away_possession": _stat(away_data.get("statistics", []), "possessionPct"),
                "home_shots":      _stat(home_data.get("statistics", []), "totalShots"),
                "away_shots":      _stat(away_data.get("statistics", []), "totalShots"),
            })
        except Exception as e:
            log.warning(f"Error parsing ESPN event: {e}")
            continue

    upcoming = [m for m in matches if m["state"] in ("pre", "in")]
    seen = set()
    unique = []
    for m in upcoming:
        key = f"{m['home']}_{m['away']}"
        if key not in seen:
            seen.add(key)
            unique.append(m)

    log.info(f"Found {len(unique)} upcoming/live matches today from ESPN")
    return unique


def _fetch_summary(espn_id: str, league_id: str) -> dict:
    """
    Fetch match summary from ESPN.
    Returns lastFiveGames, headToHeadGames and odds for both teams.
    Tries multiple league slugs until one works.
    """
    league_slugs = [
        f"l{league_id}",   # e.g. l606 -> fifa.world
        "fifa.world",
        "fifa.friendly",
        "all",
    ]

    # Map known league IDs to ESPN slugs
    league_map = {
        "606": "fifa.world",
        "605": "fifa.worldq",
        "602": "uefa.nations",
        "601": "uefa.euro",
        "600": "fifa.friendly",
    }
    slug = league_map.get(str(league_id), "all")

    urls = [
        f"{ESPN_BASE}/{slug}/summary?event={espn_id}",
        f"{ESPN_BASE}/all/summary?event={espn_id}",
    ]

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.warning(f"Summary fetch failed {url}: {e}")
            continue

    return {}


def _parse_last5(events: list, team_id: str) -> list[dict]:
    """Parse lastFiveGames events into last5 format."""
    last5 = []
    for ev in events:
        try:
            home_id    = str(ev.get("homeTeamId", ""))
            away_id    = str(ev.get("awayTeamId", ""))
            home_score = int(ev.get("homeTeamScore", 0))
            away_score = int(ev.get("awayTeamScore", 0))
            result     = ev.get("gameResult", "")
            opponent   = ev.get("opponent", {}).get("displayName", "?")

            if str(team_id) == home_id:
                gf, ga = home_score, away_score
            else:
                gf, ga = away_score, home_score
                result = {"W": "L", "L": "W", "D": "D"}.get(result, result)

            last5.append({
                "opponent":      opponent,
                "result":        result,
                "goals_for":     gf,
                "goals_against": ga,
                "date":          ev.get("gameDate", "")[:10],
                "competition":   ev.get("competitionName", ""),
            })
        except Exception:
            continue
    return last5


def get_team_stats(home_team: str, away_team: str,
                   league_id: str, season: str,
                   home_id: str = "", away_id: str = "",
                   espn_id: str = "",
                   match_data: dict = None) -> dict:

    stats = {
        "home_team":               home_team,
        "away_team":               away_team,
        "home_goals_scored_avg":   None,
        "home_goals_conceded_avg": None,
        "away_goals_scored_avg":   None,
        "away_goals_conceded_avg": None,
        "home_last5":              [],
        "away_last5":              [],
        "h2h":                     [],
        "home_league_pos":         None,
        "away_league_pos":         None,
        "league_avg_goals_home":   1.35,
        "league_avg_goals_away":   1.10,
        "odds_home":               None,
        "odds_draw":               None,
        "odds_away":               None,
    }

    # Form fallback from scoreboard data
    if match_data:
        if match_data.get("home_form"):
            stats["home_last5"] = [
                {"opponent": "?", "result": ch, "goals_for": 0, "goals_against": 0}
                for ch in match_data["home_form"][-5:]
            ]
        if match_data.get("away_form"):
            stats["away_last5"] = [
                {"opponent": "?", "result": ch, "goals_for": 0, "goals_against": 0}
                for ch in match_data["away_form"][-5:]
            ]

    if not espn_id:
        return stats

    summary = _fetch_summary(espn_id, league_id)
    if not summary:
        log.warning(f"No summary data for event {espn_id}")
        return stats

    # Parse lastFiveGames
    try:
        last5_data = summary.get("lastFiveGames", [])
        for team_entry in last5_data:
            tid    = str(team_entry.get("team", {}).get("id", ""))
            events = team_entry.get("events", [])
            if tid == str(home_id):
                parsed = _parse_last5(events, tid)
                if parsed:
                    stats["home_last5"] = parsed
                    gf = [m["goals_for"]     for m in parsed]
                    ga = [m["goals_against"] for m in parsed]
                    if gf:
                        stats["home_goals_scored_avg"]   = round(sum(gf) / len(gf), 2)
                        stats["home_goals_conceded_avg"] = round(sum(ga) / len(ga), 2)
            elif tid == str(away_id):
                parsed = _parse_last5(events, tid)
                if parsed:
                    stats["away_last5"] = parsed
                    gf = [m["goals_for"]     for m in parsed]
                    ga = [m["goals_against"] for m in parsed]
                    if gf:
                        stats["away_goals_scored_avg"]   = round(sum(gf) / len(gf), 2)
                        stats["away_goals_conceded_avg"] = round(sum(ga) / len(ga), 2)
    except Exception as e:
        log.warning(f"Error parsing lastFiveGames: {e}")

    # Parse headToHeadGames
    try:
        h2h_data = summary.get("headToHeadGames", [])
        for team_entry in h2h_data:
            events = team_entry.get("events", [])
            if events:
                for ev in events[-5:]:
                    stats["h2h"].append({
                        "date":  ev.get("gameDate", "")[:10],
                        "home":  home_team if str(ev.get("homeTeamId")) == str(home_id) else away_team,
                        "away":  away_team if str(ev.get("homeTeamId")) == str(home_id) else home_team,
                        "score": ev.get("score", "?"),
                    })
                break
    except Exception as e:
        log.warning(f"Error parsing H2H: {e}")

    # Parse real odds from ESPN (DraftKings moneyline)
    try:
        odds_list = summary.get("odds", [])
        if odds_list and odds_list[0]:
            odds_data = odds_list[0]
            home_ml = odds_data.get("homeTeamOdds", {}).get("moneyLine")
            away_ml = odds_data.get("awayTeamOdds", {}).get("moneyLine")
            stats["odds_home"] = _moneyline_to_decimal(home_ml)
            stats["odds_away"] = _moneyline_to_decimal(away_ml)
    except Exception as e:
        log.warning(f"Error parsing odds: {e}")

    # League averages from last5 data
    all_gf = []
    if stats["home_goals_scored_avg"]:
        all_gf.append(stats["home_goals_scored_avg"])
    if stats["away_goals_scored_avg"]:
        all_gf.append(stats["away_goals_scored_avg"])
    if all_gf:
        avg = sum(all_gf) / len(all_gf)
        stats["league_avg_goals_home"] = round(avg, 2)
        stats["league_avg_goals_away"] = round(avg * 0.85, 2)

    return stats


if __name__ == "__main__":
    print("Testing ESPN API...")
    matches = get_todays_matches()
    print(f"Found {len(matches)} upcoming matches today")
    for m in matches[:5]:
        print(f"  {m['home']} vs {m['away']} — {m['competition']} [{m['state']}]")

    if matches:
        print("\nTesting stats for first match...")
        m = matches[0]
        s = get_team_stats(
            m["home"], m["away"],
            m["league_id"], m["season"],
            m.get("home_id", ""), m.get("away_id", ""),
            espn_id=m.get("espn_id", ""),
            match_data=m
        )
        print(f"  Home avg goals: {s['home_goals_scored_avg']}")
        print(f"  Away avg goals: {s['away_goals_scored_avg']}")
        print(f"  Home last 5:    {s['home_last5']}")
        print(f"  H2H:            {s['h2h']}")
        print(f"  Odds home:      {s['odds_home']}")
        print(f"  Odds away:      {s['odds_away']}")
