"""
Each strategy function receives a match row dict and returns a dict
with columns to add to that row for that strategy.

Strategies simulate betting on 1X2 only (home / draw / away).
The model picks the outcome with highest probability as the suggested bet.

Columns added per strategy:
  {prefix}_bet:        "H", "D", "A", or "NO_BET"
  {prefix}_stake:      amount wagered (0 if no bet)
  {prefix}_odds:       implied odds used
  {prefix}_profit:     net profit/loss for this match
  {prefix}_correct:    True/False if bet was correct
"""


def _get_best_outcome(row):
    """Returns the outcome the model is most confident about."""
    probs = {
        "H": row["prob_home"] / 100,
        "D": row["prob_draw"] / 100,
        "A": row["prob_away"] / 100,
    }
    odds = {
        "H": row["implied_home"],
        "D": row["implied_draw"],
        "A": row["implied_away"],
    }
    best = max(probs, key=probs.get)
    return best, probs[best], odds[best]


def _get_value_outcome(row):
    """
    Returns the outcome with the highest positive expected value.
    Simulates market odds by adding a 10% bookmaker margin on top of our implied odds.
    Value = (model_prob * market_odds) - 1 > 0
    """
    outcomes = {
        "H": (row["prob_home"] / 100, row["implied_home"]),
        "D": (row["prob_draw"] / 100, row["implied_draw"]),
        "A": (row["prob_away"] / 100, row["implied_away"]),
    }

    best_value = -999.0
    best_outcome = None
    best_prob = None
    best_odds = None

    for outcome, (prob, implied) in outcomes.items():
        market_odds = implied * 1.10
        ev = (prob * market_odds) - 1
        if ev > best_value:
            best_value = ev
            best_outcome = outcome
            best_prob = prob
            best_odds = market_odds

    if best_value > 0:
        return best_outcome, best_prob, best_odds, best_value
    return None, None, None, best_value


def _kelly_stake(prob: float, odds: float, bankroll: float, fraction: float) -> float:
    """
    Fractional Kelly Criterion stake, capped at 20% of bankroll.
    kelly_pct = (prob * odds - 1) / (odds - 1)
    """
    if odds <= 1:
        return 0.0
    kelly_pct = ((prob * odds) - 1) / (odds - 1)
    kelly_pct = max(0.0, kelly_pct) * fraction
    stake = bankroll * kelly_pct
    stake = min(stake, bankroll * 0.20)
    return round(stake, 2)


def _profit(stake: float, odds: float, correct: bool) -> float:
    if stake == 0:
        return 0.0
    if correct:
        return round(stake * (odds - 1), 2)
    return round(-stake, 2)


# ── Strategy 1: Threshold + Fixed stake ──────────────────────────────────────

def strategy_threshold_fixed(row: dict, threshold: float, fixed_stake: float) -> dict:
    outcome, prob, odds = _get_best_outcome(row)
    bet = outcome if prob >= threshold else "NO_BET"
    stake = fixed_stake if bet != "NO_BET" else 0.0
    correct = (bet == row["actual_result"]) if bet != "NO_BET" else False
    profit = _profit(stake, odds, correct)
    return {
        "th_fixed_bet":     bet,
        "th_fixed_stake":   stake,
        "th_fixed_odds":    round(odds, 2) if bet != "NO_BET" else 0.0,
        "th_fixed_profit":  profit,
        "th_fixed_correct": correct,
    }


# ── Strategy 2: Threshold + Kelly ────────────────────────────────────────────

def strategy_threshold_kelly(row: dict, threshold: float, kelly_fraction: float,
                              bankroll: float = 1000.0) -> dict:
    outcome, prob, odds = _get_best_outcome(row)
    if prob < threshold:
        return {
            "th_kelly_bet":     "NO_BET",
            "th_kelly_stake":   0.0,
            "th_kelly_odds":    0.0,
            "th_kelly_profit":  0.0,
            "th_kelly_correct": False,
        }
    stake = _kelly_stake(prob, odds, bankroll, kelly_fraction)
    correct = outcome == row["actual_result"]
    profit = _profit(stake, odds, correct)
    return {
        "th_kelly_bet":     outcome,
        "th_kelly_stake":   stake,
        "th_kelly_odds":    round(odds, 2),
        "th_kelly_profit":  profit,
        "th_kelly_correct": correct,
    }


# ── Strategy 3: Value bet + Fixed stake ──────────────────────────────────────

def strategy_valuebets_fixed(row: dict, fixed_stake: float) -> dict:
    outcome, prob, odds, ev = _get_value_outcome(row)
    if outcome is None:
        return {
            "vb_fixed_bet":     "NO_BET",
            "vb_fixed_stake":   0.0,
            "vb_fixed_odds":    0.0,
            "vb_fixed_profit":  0.0,
            "vb_fixed_correct": False,
            "vb_fixed_ev":      round(ev, 4) if ev is not None else 0.0,
        }
    correct = outcome == row["actual_result"]
    profit = _profit(fixed_stake, odds, correct)
    return {
        "vb_fixed_bet":     outcome,
        "vb_fixed_stake":   fixed_stake,
        "vb_fixed_odds":    round(odds, 2),
        "vb_fixed_profit":  profit,
        "vb_fixed_correct": correct,
        "vb_fixed_ev":      round(ev, 4),
    }


# ── Strategy 4: Value bet + Kelly ────────────────────────────────────────────

def strategy_valuebets_kelly(row: dict, kelly_fraction: float,
                              bankroll: float = 1000.0) -> dict:
    outcome, prob, odds, ev = _get_value_outcome(row)
    if outcome is None:
        return {
            "vb_kelly_bet":     "NO_BET",
            "vb_kelly_stake":   0.0,
            "vb_kelly_odds":    0.0,
            "vb_kelly_profit":  0.0,
            "vb_kelly_correct": False,
            "vb_kelly_ev":      round(ev, 4) if ev is not None else 0.0,
        }
    stake = _kelly_stake(prob, odds, bankroll, kelly_fraction)
    correct = outcome == row["actual_result"]
    profit = _profit(stake, odds, correct)
    return {
        "vb_kelly_bet":     outcome,
        "vb_kelly_stake":   stake,
        "vb_kelly_odds":    round(odds, 2),
        "vb_kelly_profit":  profit,
        "vb_kelly_correct": correct,
        "vb_kelly_ev":      round(ev, 4),
    }
