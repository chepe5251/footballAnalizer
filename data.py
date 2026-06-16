import time
import difflib
import pandas as pd
import soccerdata as sd

from logger import log

COMPETITIONS = {
    "Premier League":  "ENG-Premier League",
    "La Liga":         "ESP-La Liga",
    "Serie A":         "ITA-Serie A",
    "Bundesliga":      "GER-Bundesliga",
    "Ligue 1":         "FRA-Ligue 1",
    "Champions League":"UEFA-Champions League",
    "Europa League":   "UEFA-Europa League",
    "MLS":             "USA-Major League Soccer",
    "Liga MX":         "MEX-Liga MX",
    "Eredivisie":      "NED-Eredivisie",
    "Primeira Liga":   "POR-Primeira Liga",
}


def _current_season() -> str:
    today = pd.Timestamp.today()
    year = today.year
    if today.month >= 7:
        return f"{year}-{year + 1}"
    return f"{year - 1}-{year}"


def _parse_score(score_str, team_name, home_team):
    """Parse 'X–Y' score string; returns (goals_for, goals_against, result) for team_name."""
    try:
        parts = str(score_str).replace("–", "-").replace("−", "-").split("-")
        home_g, away_g = int(parts[0].strip()), int(parts[1].strip())
        if team_name == home_team:
            gf, ga = home_g, away_g
        else:
            gf, ga = away_g, home_g
        if gf > ga:
            result = "W"
        elif gf == ga:
            result = "D"
        else:
            result = "L"
        return gf, ga, result
    except Exception:
        return None, None, None


def _fuzzy_find(name: str, candidates, cutoff=0.6):
    """Return best fuzzy match from candidates list, or None."""
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def get_todays_matches() -> list[dict]:
    today = pd.Timestamp.today().date()
    season = _current_season()
    results = []
    seen = set()

    for comp_name, league_id in COMPETITIONS.items():
        try:
            fbref = sd.FBref(leagues=league_id, seasons=season)
            schedule = fbref.read_schedule()
            time.sleep(2)

            if "date" not in schedule.columns:
                log.warning(f"{comp_name}: no 'date' column in schedule")
                continue

            schedule["_date"] = pd.to_datetime(schedule["date"], errors="coerce").dt.date
            todays = schedule[schedule["_date"] == today]

            for _, row in todays.iterrows():
                home = str(row.get("home_team", "")).strip()
                away = str(row.get("away_team", "")).strip()
                if not home or not away:
                    continue
                key = (home, away, comp_name)
                if key in seen:
                    continue
                seen.add(key)

                raw_time = row.get("time", None)
                time_utc = str(raw_time) if pd.notna(raw_time) else "Por confirmar"

                results.append({
                    "home": home,
                    "away": away,
                    "competition": comp_name,
                    "time_utc": time_utc,
                    "season": season,
                    "league_id": league_id,
                })

        except Exception as e:
            log.warning(f"Could not fetch schedule for {comp_name}: {e}")

    log.info(f"Found {len(results)} matches today")
    return results


def get_team_stats(home_team: str, away_team: str, league_id: str, season: str) -> dict:
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
        "league_avg_goals_home": None,
        "league_avg_goals_away": None,
    }

    try:
        fbref = sd.FBref(leagues=league_id, seasons=season)

        try:
            schedule = fbref.read_schedule()
            time.sleep(2)

            completed = schedule[
                schedule["score"].notna() &
                (pd.to_datetime(schedule["date"], errors="coerce") < pd.Timestamp.today())
            ].copy()

            all_teams = list(set(
                schedule["home_team"].dropna().tolist() +
                schedule["away_team"].dropna().tolist()
            ))
            home_resolved = _fuzzy_find(home_team, all_teams) or home_team
            away_resolved = _fuzzy_find(away_team, all_teams) or away_team

            # Last 5 for home team
            home_matches = completed[
                (completed["home_team"] == home_resolved) |
                (completed["away_team"] == home_resolved)
            ].tail(5)

            for _, row in home_matches.iterrows():
                ht = row["home_team"]
                gf, ga, res = _parse_score(row["score"], home_resolved, ht)
                if res is None:
                    continue
                opponent = row["away_team"] if ht == home_resolved else row["home_team"]
                stats["home_last5"].append({
                    "opponent": opponent,
                    "result": res,
                    "goals_for": gf,
                    "goals_against": ga,
                })

            # Last 5 for away team
            away_matches = completed[
                (completed["home_team"] == away_resolved) |
                (completed["away_team"] == away_resolved)
            ].tail(5)

            for _, row in away_matches.iterrows():
                ht = row["home_team"]
                gf, ga, res = _parse_score(row["score"], away_resolved, ht)
                if res is None:
                    continue
                opponent = row["away_team"] if ht == away_resolved else row["home_team"]
                stats["away_last5"].append({
                    "opponent": opponent,
                    "result": res,
                    "goals_for": gf,
                    "goals_against": ga,
                })

            # H2H
            h2h_rows = completed[
                ((completed["home_team"] == home_resolved) & (completed["away_team"] == away_resolved)) |
                ((completed["home_team"] == away_resolved) & (completed["away_team"] == home_resolved))
            ].tail(5)

            for _, row in h2h_rows.iterrows():
                ht = row["home_team"]
                _, _, res = _parse_score(row["score"], home_resolved, ht)
                date_val = str(row.get("date", ""))[:10]
                stats["h2h"].append({
                    "date": date_val,
                    "home": ht,
                    "away": row["away_team"],
                    "score": str(row["score"]).replace("–", "-").replace("−", "-"),
                    "result": res or "?",
                })

            # League averages
            home_g = []
            away_g = []
            for _, row in completed.iterrows():
                try:
                    parts = str(row["score"]).replace("–", "-").replace("−", "-").split("-")
                    home_g.append(int(parts[0].strip()))
                    away_g.append(int(parts[1].strip()))
                except Exception:
                    pass
            if home_g:
                stats["league_avg_goals_home"] = round(sum(home_g) / len(home_g), 3)
            if away_g:
                stats["league_avg_goals_away"] = round(sum(away_g) / len(away_g), 3)

        except Exception as e:
            log.warning(f"Could not fetch schedule data for {home_team} vs {away_team}: {e}")

        try:
            team_stats_df = fbref.read_team_season_stats(stat_type="standard")
            time.sleep(2)

            if isinstance(team_stats_df.columns, pd.MultiIndex):
                team_stats_df.columns = [
                    "_".join(str(c) for c in col).strip("_") if isinstance(col, tuple) else col
                    for col in team_stats_df.columns
                ]

            all_teams_ts = team_stats_df.index.get_level_values("team").tolist() if "team" in team_stats_df.index.names else team_stats_df.get("team", pd.Series()).tolist()

            def _extract_team_stats(team_name_raw):
                resolved = _fuzzy_find(team_name_raw, all_teams_ts) or team_name_raw
                try:
                    row = team_stats_df.xs(resolved, level="team") if "team" in team_stats_df.index.names else team_stats_df[team_stats_df["team"] == resolved]
                    if hasattr(row, "iloc"):
                        row = row.iloc[0]

                    # Try common column names for goals and games
                    gf_col = next((c for c in row.index if "Gls" in str(c) or "goals_for" in str(c).lower() or "GF" in str(c)), None)
                    ga_col = next((c for c in row.index if "GA" in str(c) or "goals_against" in str(c).lower() or "Gls_against" in str(c)), None)
                    mp_col = next((c for c in row.index if "MP" in str(c) or "matches" in str(c).lower() or "Pld" in str(c)), None)

                    gf = float(row[gf_col]) if gf_col and pd.notna(row[gf_col]) else None
                    ga = float(row[ga_col]) if ga_col and pd.notna(row[ga_col]) else None
                    mp = float(row[mp_col]) if mp_col and pd.notna(row[mp_col]) else None

                    scored_avg = round(gf / mp, 3) if gf and mp else None
                    conceded_avg = round(ga / mp, 3) if ga and mp else None
                    return scored_avg, conceded_avg
                except Exception:
                    return None, None

            stats["home_goals_scored_avg"], stats["home_goals_conceded_avg"] = _extract_team_stats(home_team)
            stats["away_goals_scored_avg"], stats["away_goals_conceded_avg"] = _extract_team_stats(away_team)

        except Exception as e:
            log.warning(f"Could not fetch team season stats for {home_team} vs {away_team}: {e}")

        try:
            standings_df = fbref.read_standings()
            time.sleep(2)

            if isinstance(standings_df.columns, pd.MultiIndex):
                standings_df.columns = [
                    "_".join(str(c) for c in col).strip("_") if isinstance(col, tuple) else col
                    for col in standings_df.columns
                ]

            standings_df = standings_df.reset_index()
            team_col = next((c for c in standings_df.columns if "team" in str(c).lower() or "Squad" in str(c)), None)
            rank_col = next((c for c in standings_df.columns if "Rk" in str(c) or "rank" in str(c).lower() or "Pos" in str(c)), None)

            if team_col and rank_col:
                team_list = standings_df[team_col].tolist()
                home_r = _fuzzy_find(home_team, team_list)
                away_r = _fuzzy_find(away_team, team_list)
                if home_r:
                    h_row = standings_df[standings_df[team_col] == home_r]
                    stats["home_league_pos"] = int(h_row[rank_col].iloc[0]) if not h_row.empty else None
                if away_r:
                    a_row = standings_df[standings_df[team_col] == away_r]
                    stats["away_league_pos"] = int(a_row[rank_col].iloc[0]) if not a_row.empty else None

        except Exception as e:
            log.warning(f"Could not fetch standings for {home_team} vs {away_team}: {e}")

    except Exception as e:
        log.warning(f"FBref init failed for {league_id}/{season}: {e}")

    return stats
