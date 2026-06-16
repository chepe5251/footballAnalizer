import time
from datetime import date

import pandas as pd
import soccerdata as sd

from logger import log
from model import calculate_poisson_probabilities
from backtest.strategies import (
    strategy_threshold_fixed,
    strategy_threshold_kelly,
    strategy_valuebets_fixed,
    strategy_valuebets_kelly,
)
from backtest.metrics import compute_calibration, compute_strategy_metrics
from backtest.exporter import export_to_csv


def get_seasons_to_backtest(num_seasons: int) -> list[str]:
    """
    Returns a list of completed soccerdata season strings.
    Example: num_seasons=2, called June 2025 → ["2022-2023", "2023-2024"]
    The current (incomplete) season is always excluded.
    """
    today = date.today()
    current_season_start = today.year if today.month >= 7 else today.year - 1
    seasons = []
    for i in range(num_seasons, 0, -1):
        start = current_season_start - i
        seasons.append(f"{start}-{start + 1}")
    return seasons


def _parse_score(score_str: str):
    """Parse '2–1' or '2-1' → (home_goals, away_goals). Returns (None, None) on failure."""
    try:
        parts = str(score_str).replace("–", "-").replace("−", "-").split("-")
        return int(parts[0].strip()), int(parts[1].strip())
    except Exception:
        return None, None


def fetch_historical_matches(league_id: str, season: str) -> pd.DataFrame:
    """
    Fetches all completed matches for a league/season from FBref.
    Returns a DataFrame with standardised columns ready for the backtest engine.
    """
    try:
        fbref = sd.FBref(leagues=league_id, seasons=season)
        schedule = fbref.read_schedule()
        time.sleep(2)

        completed = schedule[schedule["score"].notna()].copy()

        scores = completed["score"].apply(lambda s: pd.Series(_parse_score(s)))
        scores.columns = ["home_goals", "away_goals"]
        completed = completed.join(scores).dropna(subset=["home_goals", "away_goals"])
        completed["home_goals"] = completed["home_goals"].astype(int)
        completed["away_goals"] = completed["away_goals"].astype(int)

        def get_result(row):
            if row["home_goals"] > row["away_goals"]:
                return "H"
            if row["home_goals"] < row["away_goals"]:
                return "A"
            return "D"

        completed["result"]      = completed.apply(get_result, axis=1)
        completed["total_goals"] = completed["home_goals"] + completed["away_goals"]
        completed["over25"]      = completed["total_goals"] > 2
        completed["over35"]      = completed["total_goals"] > 3
        completed["btts"]        = (completed["home_goals"] > 0) & (completed["away_goals"] > 0)

        log.info(f"Fetched {len(completed)} completed matches — {league_id} {season}")
        return completed[["date", "home_team", "away_team",
                           "home_goals", "away_goals", "result",
                           "total_goals", "over25", "over35", "btts"]].reset_index(drop=True)

    except Exception as e:
        log.warning(f"Could not fetch {league_id} {season}: {e}")
        return pd.DataFrame()


def build_rolling_stats(
    all_matches: pd.DataFrame,
    match_idx: int,
    home_team: str,
    away_team: str,
    league_avg_home: float,
    league_avg_away: float,
    window: int = 20,
) -> dict:
    """
    Build a stats dict for the Poisson model using only matches BEFORE match_idx.
    Prevents data leakage: the model only ever sees past data.
    """
    past = all_matches.iloc[:match_idx]

    def team_averages(team):
        home_games = past[past["home_team"] == team].tail(window)
        away_games = past[past["away_team"] == team].tail(window)

        goals_scored   = list(home_games["home_goals"]) + list(away_games["away_goals"])
        goals_conceded = list(home_games["away_goals"]) + list(away_games["home_goals"])

        if not goals_scored:
            return None, None
        return (
            round(sum(goals_scored)   / len(goals_scored),   3),
            round(sum(goals_conceded) / len(goals_conceded), 3),
        )

    def last5_results(team):
        home = past[past["home_team"] == team][["result"]].copy()
        away = past[past["away_team"] == team].copy()
        away["result"] = away["result"].map({"H": "A", "A": "H", "D": "D"})
        away = away[["result"]]
        combined = pd.concat([home, away]).tail(5)
        # Return list of dicts as expected by assess_model_confidence
        return [{"result": r} for r in combined["result"].tolist()]

    home_scored, home_conceded = team_averages(home_team)
    away_scored, away_conceded = team_averages(away_team)

    return {
        "home_goals_scored_avg":   home_scored,
        "home_goals_conceded_avg": home_conceded,
        "away_goals_scored_avg":   away_scored,
        "away_goals_conceded_avg": away_conceded,
        "league_avg_goals_home":   league_avg_home,
        "league_avg_goals_away":   league_avg_away,
        "home_last5":              last5_results(home_team),
        "away_last5":              last5_results(away_team),
        "h2h":                     [],
        "home_league_pos":         None,
        "away_league_pos":         None,
    }


def run_backtest(
    leagues: set,
    num_seasons: int,
    threshold: float,
    fixed_stake: float,
    initial_bankroll: float,
    kelly_fraction: float,
    output_prefix: str,
):
    log.info(f"Starting backtest: {len(leagues)} league(s), {num_seasons} season(s)")
    seasons = get_seasons_to_backtest(num_seasons)
    log.info(f"Seasons: {seasons}")

    all_rows = []

    for league_id in sorted(leagues):
        for season in seasons:
            log.info(f"Processing {league_id} — {season}")
            matches = fetch_historical_matches(league_id, season)

            if matches.empty:
                log.warning(f"No data for {league_id} {season}, skipping")
                continue

            league_avg_home = matches["home_goals"].mean()
            league_avg_away = matches["away_goals"].mean()

            # Skip first 10 matches — too little history for a meaningful model
            for idx in range(10, len(matches)):
                match = matches.iloc[idx]

                stats = build_rolling_stats(
                    all_matches=matches,
                    match_idx=idx,
                    home_team=match["home_team"],
                    away_team=match["away_team"],
                    league_avg_home=league_avg_home,
                    league_avg_away=league_avg_away,
                )

                try:
                    probs = calculate_poisson_probabilities(stats)
                except Exception as e:
                    log.warning(f"Model error at match {idx} ({league_id} {season}): {e}")
                    continue

                row = {
                    "league":            league_id,
                    "season":            season,
                    "date":              str(match["date"]),
                    "home_team":         match["home_team"],
                    "away_team":         match["away_team"],
                    "home_goals":        int(match["home_goals"]),
                    "away_goals":        int(match["away_goals"]),
                    "actual_result":     match["result"],
                    "actual_over25":     match["over25"],
                    "actual_over35":     match["over35"],
                    "actual_btts":       match["btts"],
                    "prob_home":         probs["prob_home"],
                    "prob_draw":         probs["prob_draw"],
                    "prob_away":         probs["prob_away"],
                    "prob_over25":       probs["prob_over25"],
                    "prob_under25":      probs["prob_under25"],
                    "prob_over35":       probs["prob_over35"],
                    "prob_under35":      probs["prob_under35"],
                    "prob_btts_yes":     probs["prob_btts_yes"],
                    "prob_btts_no":      probs["prob_btts_no"],
                    "implied_home":      probs["implied_home"],
                    "implied_draw":      probs["implied_draw"],
                    "implied_away":      probs["implied_away"],
                    "lambda_home":       probs["lambda_home"],
                    "lambda_away":       probs["lambda_away"],
                    "model_confidence":  probs["model_confidence"],
                    "most_likely_score": probs["most_likely_score"],
                }

                row.update(strategy_threshold_fixed(row, threshold, fixed_stake))
                row.update(strategy_threshold_kelly(row, threshold, kelly_fraction, initial_bankroll))
                row.update(strategy_valuebets_fixed(row, fixed_stake))
                row.update(strategy_valuebets_kelly(row, kelly_fraction, initial_bankroll))

                all_rows.append(row)

    if not all_rows:
        log.error("No rows generated. Check league IDs and data availability.")
        return

    log.info(f"Backtest complete: {len(all_rows)} matches processed")
    df = pd.DataFrame(all_rows)
    calibration = compute_calibration(df)
    strategy_metrics = compute_strategy_metrics(df, initial_bankroll)
    export_to_csv(df, calibration, strategy_metrics, output_prefix)
