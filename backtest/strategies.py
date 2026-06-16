"""
Betting strategies for backtesting.

Market odds simulation:
  implied_odd = 1 / prob  (fair odds, no margin)
  market_odd  = implied / 1.05  (bookie takes 5% margin — they offer LESS than fair)

Value bet exists when: model_prob > 1 / market_odd
i.e. we think it's more likely than what the bookie's price implies.
"""


def _get_best_outcome(row):
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
    Value bet: model probability > implied probability of market odds.
    Market odds = implied_odd / 1.05 (bookie takes 5% margin, so offers less).
    EV = (model_prob * market_odds) - 1
    Only bet if EV > 0.
    """
    outcomes = {
        "H": (row["prob_home"] / 100, row["implied_home"]),
        "D": (row["prob_draw"] / 100, row["implied_draw"]),
        "A": (row["prob_away"] / 100, row["implied_away"]),
    }

    best_ev      = -999.0
    best_outcome = None
    best_prob    = None
    best_odds    = None

    for outcome, (prob, implied) in outcomes.items():
        # Bookie offers LESS than fair — they keep the margin
        market_odds = implied / 1.05
        ev = (prob * market_odds) - 1
        if ev > best_ev:
            best_ev      = ev
            best_outcome = outcome
            best_prob    = prob
            best_odds    = market_odds

    if best_ev > 0:
        return best_outcome, best_prob, best_odds, best_ev
    return None, None, None, best_ev


def _kelly_stake(prob: float, odds: float, bankroll: float, fraction: float) -> float:
    if odds <= 1:
        return 0.0
    kelly_pct = ((prob * odds) - 1) / (odds - 1)
    kelly_pct = max(0.0, kelly_pct) * fraction
    stake = bankroll * kelly_pct
    return round(min(stake, bankroll * 0.20), 2)


def _profit(stake: float, odds: float, correct: bool) -> float:
    if stake == 0:
        return 0.0
    return round(stake * (odds - 1), 2) if correct else round(-stake, 2)


# ── Strategy 1: Threshold + Fixed stake ──────────────────────────────────────

def strategy_threshold_fixed(row: dict, threshold: float, fixed_stake: float) -> dict:
    outcome, prob, odds = _get_best_outcome(row)
    bet   = outcome if prob >= threshold else "NO_BET"
    stake = fixed_stake if bet != "NO_BET" else 0.0
    correct = (bet == row["actual_result"]) if bet != "NO_BET" else False
    return {
        "th_fixed_bet":     bet,
        "th_fixed_stake":   stake,
        "th_fixed_odds":    round(odds, 2) if bet != "NO_BET" else 0.0,
        "th_fixed_profit":  _profit(stake, odds, correct),
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
    stake   = _kelly_stake(prob, odds, bankroll, kelly_fraction)
    correct = outcome == row["actual_result"]
    return {
        "th_kelly_bet":     outcome,
        "th_kelly_stake":   stake,
        "th_kelly_odds":    round(odds, 2),
        "th_kelly_profit":  _profit(stake, odds, correct),
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
            "vb_fixed_ev":      0.0,  # fixed: no variable fantasma
        }
    correct = outcome == row["actual_result"]
    return {
        "vb_fixed_bet":     outcome,
        "vb_fixed_stake":   fixed_stake,
        "vb_fixed_odds":    round(odds, 2),
        "vb_fixed_profit":  _profit(fixed_stake, odds, correct),
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
            "vb_kelly_ev":      0.0,  # fixed: no variable fantasma
        }
    stake   = _kelly_stake(prob, odds, bankroll, kelly_fraction)
    correct = outcome == row["actual_result"]
    return {
        "vb_kelly_bet":     outcome,
        "vb_kelly_stake":   stake,
        "vb_kelly_odds":    round(odds, 2),
        "vb_kelly_profit":  _profit(stake, odds, correct),
        "vb_kelly_correct": correct,
        "vb_kelly_ev":      round(ev, 4),
    }
