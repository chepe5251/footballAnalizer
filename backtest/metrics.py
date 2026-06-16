import numpy as np
import pandas as pd


def compute_calibration(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calibration check: does prob_home=60% mean the home team wins 60% of the time?
    Bins predictions into 10% ranges and compares predicted vs actual frequency.
    """
    rows = []
    bins = [(i / 10, (i + 1) / 10) for i in range(10)]

    for outcome_label, prob_col, result_code in [
        ("Home Win", "prob_home", "H"),
        ("Draw",     "prob_draw", "D"),
        ("Away Win", "prob_away", "A"),
    ]:
        for low, high in bins:
            mask = (df[prob_col] / 100 >= low) & (df[prob_col] / 100 < high)
            sub = df[mask]
            if sub.empty:
                continue
            actual_rate = (sub["actual_result"] == result_code).mean()
            avg_pred = (sub[prob_col] / 100).mean()
            rows.append({
                "outcome":            outcome_label,
                "bin_low":            round(low, 1),
                "bin_high":           round(high, 1),
                "n_predictions":      len(sub),
                "avg_predicted_prob": round(avg_pred, 3),
                "actual_win_rate":    round(actual_rate, 3),
                "calibration_error":  round(abs(avg_pred - actual_rate), 3),
            })

    return pd.DataFrame(rows)


def _max_drawdown(profit_series: pd.Series) -> float:
    cumulative = profit_series.cumsum()
    peak = cumulative.cummax()
    drawdown = cumulative - peak
    return round(drawdown.min(), 2)


def _profit_factor(profit_series: pd.Series) -> float:
    gross_wins = profit_series[profit_series > 0].sum()
    gross_losses = abs(profit_series[profit_series < 0].sum())
    if gross_losses == 0:
        return float("inf")
    return round(gross_wins / gross_losses, 3)


def _brier_score(df: pd.DataFrame) -> float:
    return round(float(np.mean(
        (df["prob_home"] / 100 - (df["actual_result"] == "H").astype(float)) ** 2 +
        (df["prob_draw"] / 100 - (df["actual_result"] == "D").astype(float)) ** 2 +
        (df["prob_away"] / 100 - (df["actual_result"] == "A").astype(float)) ** 2
    )), 4)


def compute_strategy_metrics(df: pd.DataFrame, initial_bankroll: float) -> pd.DataFrame:
    """
    For each of the 4 strategies, compute performance metrics over all analyzed matches.
    """
    strategies = {
        "Threshold + Fixed Stake": ("th_fixed_bet",  "th_fixed_stake",  "th_fixed_profit",  "th_fixed_correct",  "th_fixed_odds"),
        "Threshold + Kelly":       ("th_kelly_bet",  "th_kelly_stake",  "th_kelly_profit",  "th_kelly_correct",  "th_kelly_odds"),
        "Value Bet + Fixed Stake": ("vb_fixed_bet",  "vb_fixed_stake",  "vb_fixed_profit",  "vb_fixed_correct",  "vb_fixed_odds"),
        "Value Bet + Kelly":       ("vb_kelly_bet",  "vb_kelly_stake",  "vb_kelly_profit",  "vb_kelly_correct",  "vb_kelly_odds"),
    }

    brier = _brier_score(df)
    rows = []

    for name, (bet_col, stake_col, profit_col, correct_col, odds_col) in strategies.items():
        bets = df[df[bet_col] != "NO_BET"]
        if bets.empty:
            rows.append({"strategy": name, "note": "No bets placed"})
            continue

        total_bets   = len(bets)
        wins         = int(bets[correct_col].sum())
        win_rate     = round(wins / total_bets * 100, 2)
        total_staked = bets[stake_col].sum()
        total_profit = round(bets[profit_col].sum(), 2)
        roi          = round(total_profit / total_staked * 100, 2) if total_staked > 0 else 0.0
        avg_odds     = round(bets[odds_col].mean(), 2) if odds_col in bets.columns else 0.0

        rows.append({
            "strategy":       name,
            "total_bets":     total_bets,
            "wins":           wins,
            "win_rate_%":     win_rate,
            "total_staked_$": round(total_staked, 2),
            "total_profit_$": total_profit,
            "roi_%":          roi,
            "max_drawdown_$": _max_drawdown(bets[profit_col]),
            "profit_factor":  _profit_factor(bets[profit_col]),
            "avg_odds":       avg_odds,
            "brier_score":    brier,
        })

    return pd.DataFrame(rows)
