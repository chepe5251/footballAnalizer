"""
data.py — ESPN public API only.
Sin football-data, sin soccerdata, sin Chrome.
"""

import requests
from datetime import date
from logger import log

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def _stat(statistics: list, name: str):
    for s in statistics:
        if s.get("name") == name:
            try:
                return float(s.get("displayValue", "0").replace("%", ""))
            except:
                return None
    return None


def _parse_score(score_obj) -> int:
    """ESPN score can be int, str, or dict with 'value' key."""
    if isinstance(score_obj, dict):
        return int(float(score_obj.get("value", 0)))
    try:
        return int(float(score_obj))
    except:
        return 0


def _parse_form(form_str: str) -> list[dict]:
    return [
        {"opponent": "?", "result": ch, "goals_for": 0, "goals_against": 0}
        for ch in form_str[-5:]
    ]


def get_todays_matches() -> list[dict]:
    url = f"{ESPN_BASE}/all/scoreboard"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        log.error(f"ESPN API error: {e}")
        return []

    matches = []
    for event in data.get("events", []):
        try:
            comp = event.get("competitions", [{}])[0]
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
                "home":             home_team,
                "away":             away_team,
                "home_id":          home_id,
                "away_id":          away_id,
                "competition":      competition,
                "time_utc":         event.get("date", "TBD"),
                "season":           str(event.get("season", {}).get("year", date.today().year)),
                "league_id":        league_id,
                "espn_id":          event.get("id", ""),
                "state":            state,
                "home_score":       _parse_score(home_data.get("score", 0)),
                "away_score":       _parse_score(away_data.get("score", 0)),
                "home_form":        home_data.get("form", ""),
                "away_form":        away_data.get("form", ""),
                "home_record":      next((r.get("summary","") for r in home_data.get("records",[]) if r.get("type")=="total"), ""),
                "away_record":      next((r.get("summary","") for r in away_data.get("records",[]) if r.get("type")=="total"), ""),
                "home_possession":  _stat(home_data.get("statistics", []), "possessionPct"),
                "away_possession":  _stat(away_data.get("statistics", []), "possessionPct"),
                "home_shots":       _stat(home_data.get("statistics", []), "totalShots"),
                "away_shots":       _stat(away_data.get("statistics", []), "totalShots"),
                "home_shots_on":    _stat(home_data.get("statistics", []), "shotsOnTarget"),
                "away_shots_on":    _stat(away_data.get("statistics", []), "shotsOnTarget"),
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


def _fetch_team_history(team_id: str) -> list[dict]:
    """Fetch historical results for a team using ESPN all/teams schedule."""
    url = f"{ESPN_BASE}/all/teams/{team_id}/schedule"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning(f"Could not fetch history for team {team_id}: {e}")
        return []

    results = []
    for ev in data.get("events", []):
        try:
            comp = ev.get("competitions", [{}])[0]
            state = comp.get("status", {}).get("type", {}).get("state", "pre")
            if state != "post":
                continue

            competitors = comp.get("competitors", [])
            team_comp = next((c for c in competitors if c.get("team", {}).get("id") == team_id), None)
            opp_comp  = next((c for c in competitors if c.get("team", {}).get("id") != team_id), None)
            if not team_comp or not opp_comp:
                continue

            gf = _parse_score(team_comp.get("score", 0))
            ga = _parse_score(opp_comp.get("score", 0))
            opp_name = opp_comp.get("team", {}).get("displayName", "?")
            opp_id   = opp_comp.get("team", {}).get("id", "")
            result   = "W" if gf > ga else ("D" if gf == ga else "L")

            results.append({
                "opponent":      opp_name,
                "opponent_id":   opp_id,
                "result":        result,
                "goals_for":     gf,
                "goals_against": ga,
                "date":          ev.get("date", "")[:10],
            })
        except Exception:
            continue

    return results


def get_team_stats(home_team: str, away_team: str,
                   league_id: str, season: str,
                   home_id: str = "", away_id: str = "",
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
    }

    # Form fallback from match_data
    if match_data:
        if match_data.get("home_form"):
            stats["home_last5"] = _parse_form(match_data["home_form"])
        if match_data.get("away_form"):
            stats["away_last5"] = _parse_form(match_data["away_form"])

    # Home team history
    if home_id:
        history = _fetch_team_history(home_id)
        if history:
            gf_list = [m["goals_for"]     for m in history]
            ga_list = [m["goals_against"] for m in history]
            stats["home_goals_scored_avg"]   = round(sum(gf_list) / len(gf_list), 2)
            stats["home_goals_conceded_avg"] = round(sum(ga_list) / len(ga_list), 2)
            stats["home_last5"] = history[-5:]

            # H2H from home team perspective
            h2h = [m for m in history if m["opponent_id"] == away_id]
            if h2h:
                stats["h2h"] = [
                    {
                        "date":  m["date"],
                        "home":  home_team,
                        "away":  away_team,
                        "score": f"{m['goals_for']}-{m['goals_against']}",
                    }
                    for m in h2h[-5:]
                ]

    # Away team history
    if away_id:
        history = _fetch_team_history(away_id)
        if history:
            gf_list = [m["goals_for"]     for m in history]
            ga_list = [m["goals_against"] for m in history]
            stats["away_goals_scored_avg"]   = round(sum(gf_list) / len(gf_list), 2)
            stats["away_goals_conceded_avg"] = round(sum(ga_list) / len(ga_list), 2)
            stats["away_last5"] = history[-5:]

    # League averages from both histories combined
    all_gf = []
    all_ga = []
    if stats["home_goals_scored_avg"]:
        all_gf.append(stats["home_goals_scored_avg"])
    if stats["away_goals_scored_avg"]:
        all_gf.append(stats["away_goals_scored_avg"])
    if all_gf:
        stats["league_avg_goals_home"] = round(sum(all_gf) / len(all_gf), 2)
        stats["league_avg_goals_away"] = round(sum(all_gf) / len(all_gf) * 0.85, 2)

    return stats


if __name__ == "__main__":
    print("Testing ESPN API...")
    matches = get_todays_matches()
    print(f"Found {len(matches)} upcoming matches today")
    for m in matches[:5]:
        print(f"  {m['home']} vs {m['away']} — {m['competition']} [{m['state']}]")
        print(f"    Form: {m['home_form']} | {m['away_form']}")

    if matches:
        print("\nTesting stats for first match...")
        m = matches[0]
        s = get_team_stats(
            m["home"], m["away"],
            m["league_id"], m["season"],
            m.get("home_id", ""), m.get("away_id", ""),
            match_data=m
        )
        print(f"  Home avg goals scored:   {s['home_goals_scored_avg']}")
        print(f"  Away avg goals scored:   {s['away_goals_scored_avg']}")
        print(f"  Home last 5: {s['home_last5']}")
        print(f"  Away last 5: {s['away_last5']}")
        print(f"  H2H: {s['h2h']}")
