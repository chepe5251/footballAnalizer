"""
formatter.py — Builds two Telegram messages per match.
"""
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


def build_summary_message(match: dict, probabilities: dict, analysis: dict) -> str:
    time_str = match.get("time_utc", "")
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        time_str = dt.strftime("%H:%M UTC")
    except:
        pass

    value_bets_str = "\n".join(f"  • {vb}" for vb in analysis.get("value_bets", []))
    avoid = analysis.get("avoid", "null")
    avoid_str = f"\n⛔ EVITAR: {avoid}" if avoid and avoid != "null" else ""

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
📈 xG: {probabilities['lambda_home']} — {probabilities['lambda_away']}

💰 *VALUE BETS:*
{value_bets_str}

🏆 *MEJOR APUESTA:*
{analysis['best_bet']}

⚠️ Riesgo: {analysis['risk_level'].upper()} | Confianza modelo: {probabilities['model_confidence'].upper()}{avoid_str}"""


def build_detailed_message(match: dict, stats: dict,
                            probabilities: dict, analysis: dict) -> str:
    return f"""🔍 *ANÁLISIS EXPERTO — {match['home']} vs {match['away']}*

📈 *FORMA RECIENTE*
🏠 {match['home']}: {_form_icons(stats['home_last5'])}
✈️ {match['away']}: {_form_icons(stats['away_last5'])}

📉 *ESTADÍSTICAS*
🏠 {match['home']}: {stats.get('home_goals_scored_avg','N/D')} goles anotados / {stats.get('home_goals_conceded_avg','N/D')} recibidos
✈️ {match['away']}: {stats.get('away_goals_scored_avg','N/D')} goles anotados / {stats.get('away_goals_conceded_avg','N/D')} recibidos

⚔️ *H2H*
{_fmt_h2h(stats['h2h'])}

🧠 *RAZONAMIENTO DEL ANALISTA*
{analysis['reasoning']}

🤖 Modelo: Poisson + Dixon-Coles | Confianza: {probabilities['model_confidence'].upper()}"""
