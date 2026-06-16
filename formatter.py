def format_form_string(last5: list) -> str:
    if not last5:
        return "Sin datos"
    icons = {"W": "✅", "D": "🟡", "L": "❌"}
    return " ".join([icons.get(m["result"], "❓") for m in last5])


def format_h2h_short(h2h: list) -> str:
    if not h2h:
        return "Sin datos de H2H"
    return "\n".join([
        f"  {m['date']}: {m['home']} {m['score']} {m['away']}"
        for m in h2h[:5]
    ])


def build_summary_message(match: dict, probabilities: dict, analysis: dict) -> str:
    return (
        f"⚽ *{match['competition'].upper()}*\n"
        f"🏠 *{match['home']}* vs *{match['away']}* ✈️\n"
        f"🕐 {match.get('time_utc', 'Hora por confirmar')} UTC\n\n"
        f"📊 *PROBABILIDADES 1X2*\n"
        f"🔵 Local: {probabilities['prob_home']}% — cuota {probabilities['implied_home']}\n"
        f"⚪ Empate: {probabilities['prob_draw']}% — cuota {probabilities['implied_draw']}\n"
        f"🔴 Visitante: {probabilities['prob_away']}% — cuota {probabilities['implied_away']}\n\n"
        f"⚽ *GOLES*\n"
        f"Over 2.5: {probabilities['prob_over25']}%  |  Under 2.5: {probabilities['prob_under25']}%\n"
        f"Over 3.5: {probabilities['prob_over35']}%  |  Under 3.5: {probabilities['prob_under35']}%\n"
        f"BTTS ✅: {probabilities['prob_btts_yes']}%  |  BTTS ❌: {probabilities['prob_btts_no']}%\n\n"
        f"🎯 Marcador más probable: *{probabilities['most_likely_score']}*\n"
        f"📈 xG esperados: {probabilities['lambda_home']} — {probabilities['lambda_away']}\n\n"
        f"💡 *MEJOR APUESTA:* {analysis['best_bet']}\n"
        f"⚠️ Riesgo: {analysis['risk_level'].upper()} | Confianza modelo: {probabilities['model_confidence'].upper()}"
    )


def build_detailed_message(match: dict, stats: dict, probabilities: dict, analysis: dict) -> str:
    home_form = format_form_string(stats["home_last5"])
    away_form = format_form_string(stats["away_last5"])
    key_factors = "\n".join([f"• {f}" for f in analysis["key_factors"]])

    return (
        f"🔍 *ANÁLISIS COMPLETO — {match['home']} vs {match['away']}*\n\n"
        f"📈 *FORMA RECIENTE (últimos 5)*\n"
        f"🏠 {match['home']}: {home_form}\n"
        f"✈️ {match['away']}: {away_form}\n\n"
        f"🏆 *POSICIÓN EN TABLA*\n"
        f"{match['home']}: #{stats.get('home_league_pos', 'N/D')} | {match['away']}: #{stats.get('away_league_pos', 'N/D')}\n\n"
        f"⚔️ *HISTORIAL H2H*\n"
        f"{format_h2h_short(stats['h2h'])}\n\n"
        f"📉 *ESTADÍSTICAS DE GOLES*\n"
        f"🏠 {match['home']}: {stats.get('home_goals_scored_avg', 'N/D')} anotados / {stats.get('home_goals_conceded_avg', 'N/D')} recibidos por partido\n"
        f"✈️ {match['away']}: {stats.get('away_goals_scored_avg', 'N/D')} anotados / {stats.get('away_goals_conceded_avg', 'N/D')} recibidos por partido\n\n"
        f"🔑 *FACTORES CLAVE*\n"
        f"{key_factors}\n\n"
        f"📝 *ANÁLISIS*\n"
        f"{analysis['detailed_analysis']}\n\n"
        f"💰 *VALUE BET*\n"
        f"{analysis['value_bet']}\n\n"
        f"🤖 Modelo: Poisson + Dixon-Coles | Confianza: {probabilities['model_confidence'].upper()}"
    )
