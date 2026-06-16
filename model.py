import numpy as np
from scipy.stats import poisson

FALLBACK_HOME_AVG = 1.5
FALLBACK_AWAY_AVG = 1.2
HOME_ADVANTAGE = 1.15
RHO = 0.1  # Dixon-Coles low-score correction


def _dixon_coles_correction(home_goals, away_goals, lambda_h, lambda_a, rho):
    """Low-score correction factor for 0-0, 1-0, 0-1, 1-1."""
    if home_goals == 0 and away_goals == 0:
        return 1 - lambda_h * lambda_a * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + lambda_a * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + lambda_h * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def _attack_defense_strengths(stats: dict):
    league_home = stats.get("league_avg_goals_home") or FALLBACK_HOME_AVG
    league_away = stats.get("league_avg_goals_away") or FALLBACK_AWAY_AVG

    h_scored  = stats.get("home_goals_scored_avg")
    h_conceded = stats.get("home_goals_conceded_avg")
    a_scored  = stats.get("away_goals_scored_avg")
    a_conceded = stats.get("away_goals_conceded_avg")

    if all(v is not None for v in [h_scored, h_conceded, a_scored, a_conceded]):
        home_attack  = h_scored  / league_home
        home_defense = h_conceded / league_away
        away_attack  = a_scored  / league_away
        away_defense = a_conceded / league_home
    else:
        home_attack  = league_home / league_home
        home_defense = league_away / league_away
        away_attack  = league_away / league_away
        away_defense = league_home / league_home

    lambda_home = home_attack * away_defense * league_home * HOME_ADVANTAGE
    lambda_away = away_attack * home_defense * league_away

    lambda_home = max(0.1, lambda_home)
    lambda_away = max(0.1, lambda_away)

    return lambda_home, lambda_away


def _build_score_matrix(lambda_home: float, lambda_away: float, max_goals: int = 8) -> np.ndarray:
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            raw = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)
            correction = _dixon_coles_correction(i, j, lambda_home, lambda_away, RHO)
            matrix[i][j] = raw * correction
    # Renormalize after correction
    matrix /= matrix.sum()
    return matrix


def find_most_likely_score(matrix: np.ndarray) -> str:
    idx = np.unravel_index(np.argmax(matrix), matrix.shape)
    return f"{idx[0]}-{idx[1]}"


def assess_model_confidence(stats: dict) -> str:
    key_fields = [
        stats.get("home_goals_scored_avg"),
        stats.get("away_goals_scored_avg"),
        stats.get("home_goals_conceded_avg"),
        stats.get("away_goals_conceded_avg"),
    ]
    missing = sum(1 for v in key_fields if v is None)

    home_games = len(stats.get("home_last5", []))
    away_games = len(stats.get("away_last5", []))
    if home_games < 5 or away_games < 5:
        missing += 1

    if missing == 0:
        return "alta"
    if missing <= 2:
        return "media"
    return "baja"


def calculate_poisson_probabilities(stats: dict) -> dict:
    lambda_home, lambda_away = _attack_defense_strengths(stats)
    matrix = _build_score_matrix(lambda_home, lambda_away)

    prob_home_win = float(np.sum(np.tril(matrix, -1)))
    prob_draw     = float(np.sum(np.diag(matrix)))
    prob_away_win = float(np.sum(np.triu(matrix, 1)))

    total = prob_home_win + prob_draw + prob_away_win
    prob_home_win /= total
    prob_draw     /= total
    prob_away_win /= total

    prob_over25 = float(sum(
        matrix[i][j] for i in range(9) for j in range(9) if i + j > 2
    ))
    prob_over35 = float(sum(
        matrix[i][j] for i in range(9) for j in range(9) if i + j > 3
    ))
    prob_under25 = 1.0 - prob_over25
    prob_under35 = 1.0 - prob_over35

    prob_btts_yes = float(sum(
        matrix[i][j] for i in range(1, 9) for j in range(1, 9)
    ))
    prob_btts_no = 1.0 - prob_btts_yes

    margin = 0.05

    def implied_odd(prob):
        if prob <= 0:
            return 999.0
        return round(1 / (prob * (1 + margin)), 2)

    confidence = assess_model_confidence(stats)

    return {
        "lambda_home":   round(lambda_home, 3),
        "lambda_away":   round(lambda_away, 3),
        "prob_home":     round(prob_home_win * 100),
        "prob_draw":     round(prob_draw     * 100),
        "prob_away":     round(prob_away_win * 100),
        "prob_over25":   round(prob_over25   * 100),
        "prob_under25":  round(prob_under25  * 100),
        "prob_over35":   round(prob_over35   * 100),
        "prob_under35":  round(prob_under35  * 100),
        "prob_btts_yes": round(prob_btts_yes * 100),
        "prob_btts_no":  round(prob_btts_no  * 100),
        "implied_home":  implied_odd(prob_home_win),
        "implied_draw":  implied_odd(prob_draw),
        "implied_away":  implied_odd(prob_away_win),
        "most_likely_score": find_most_likely_score(matrix),
        "model_confidence":  confidence,
    }
