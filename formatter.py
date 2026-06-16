from datetime import datetime


def _form_icons(last5: list) -> str:
    if not last5:
        return "Sin datos"
    icons = {"W": "✅", "D": "🟡", "L": "❌"}
    return " ".join(icons.get(m.get("result", "?"), "❓") for m in last5)


def _fmt_h2h(h2h: list) -> str:
    if not h2h:
        return "Sin datos"
    return "\n".join(
        f"  {m.get('date','')} {m.get('home','?')} {m.get('score','?')} {m.get('away','?')}"
        for m in h2h[-5:]
    )


def _fmt_odds_comparison(label: str, model_odd: float, market_odd) -> str:
    if not market_odd:
        return f"{label}: modelo {model_odd}"
    diff = round(market_odd - model_odd, 2)
    arrow = "✅ value" if diff > 0.05 else ("⚠️ sin value" if diff < -0.05 else "≈ justo")
    return f"{label}: modelo {model_odd} | mercado {market_odd} {arrow}"


def build_summary_message(match: dict, probabilities: dict, analysis: dict,
                           stats: dict = None) -> str:
    time_str = match.get("time_utc", "")
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        time_str = dt.strftime("%H:%M UTC")
    except:
        pass

    value_bets_str = "\n".join(f"  • {vb}" for vb in analysis.get("value_bets", []))
    avoid = analysis.get("avoid", "null")
    avoid_str = f"\n⛔ EVITAR: {avoid}" if avoid and avoid != "null" else ""

    # Odds comparison if available
    odds_str = ""
    if stats and (stats.get("odds_home") or stats.get("odds_away")):
        odds_str = f"""
🏦 *CUOTAS MERCADO vs MODELO*
{_fmt_odds_comparison("Local", probabilities['implied_home'], stats.get('odds_home'))}
{_fmt_odds_comparison("Visita", probabilities['implied_away'], stats.get('odds_away'))}"""

    return f"""⚽ *{match['competition'].upper()}*
🏠 *{match['home']}* vs *{match['away']}* ✈️
🕐 {time_str}

📊 *PROBABILIDADES 1X2*
🔵 Local: {probabilities['prob_home']}% — cuota justa {probabilities['implied_home']}
⚪ Empate: {probabilities['prob_draw']}% — cuota justa {probabilities['implied_draw']}
🔴 Visitante: {probabilities['prob_away']}% — cuota justa {probabilities['implied_away']}

⚽ *GOLES*
Over 2.5: {probabilities['prob_over25']}%  |  Under 2.5: {probabilities['prob_under25']}%
Over 3.5: {probabilities['prob_over35']}%  |  Under 3.5: {probabilities['prob_under35']}%
BTTS ✅: {probabilities['prob_btts_yes']}%  |  BTTS ❌: {probabilities['prob_btts_no']}%

🎯 Marcador probable: *{probabilities['most_likely_score']}*
📈 xG: {probabilities['lambda_home']} — {probabilities['lambda_away']}{odds_str}

💰 *VALUE BETS:*
{value_bets_str}

🏆 *MEJOR APUESTA:*
{analysis['best_bet']}

⚠️ Riesgo: {analysis['risk_level'].upper()} | Confianza: {probabilities['model_confidence'].upper()}{avoid_str}"""


def build_detailed_message(match: dict, stats: dict,
                            probabilities: dict, analysis: dict) -> str:
    return f"""🔍 *ESTADÍSTICAS — {match['home']} vs {match['away']}*

📈 *FORMA RECIENTE*
🏠 {match['home']}: {_form_icons(stats['home_last5'])}
✈️ {match['away']}: {_form_icons(stats['away_last5'])}

📉 *PROMEDIOS POR PARTIDO*
🏠 {match['home']}: {stats.get('home_goals_scored_avg','N/D')} anotados / {stats.get('home_goals_conceded_avg','N/D')} recibidos
✈️ {match['away']}: {stats.get('away_goals_scored_avg','N/D')} anotados / {stats.get('away_goals_conceded_avg','N/D')} recibidos

⚔️ *H2H*
{_fmt_h2h(stats['h2h'])}

🤖 Modelo: Poisson + Dixon-Coles | Confianza: {probabilities['model_confidence'].upper()}"""
