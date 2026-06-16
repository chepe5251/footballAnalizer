"""
analyzer.py — Ollama local LLM para análisis de apuestas.
"""

import json
import httpx
from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from logger import log

_REQUIRED_KEYS = {"value_bets", "best_bet", "risk_level", "reasoning", "avoid"}
_VALID_RISK = {"bajo", "medio", "alto"}


def _fmt_last5(last5: list) -> str:
    if not last5:
        return "Sin datos"
    return " | ".join(
        f"{m['result']} vs {m.get('opponent','?')} ({m.get('goals_for',0)}-{m.get('goals_against',0)})"
        for m in last5
    )


def _fmt_h2h(h2h: list) -> str:
    if not h2h:
        return "Sin datos H2H"
    return " | ".join(
        f"{m.get('home','?')} {m.get('score','?')} {m.get('away','?')} ({m.get('date','')})"
        for m in h2h
    )


def _build_prompt(match: dict, stats: dict, probabilities: dict) -> str:
    return f"""Eres un apostador profesional con 15 años de experiencia. Analizas datos estadísticos y encuentras value bets rentables. Responde SOLO con JSON, sin texto extra.

PARTIDO: {match['home']} vs {match['away']}
COMPETICION: {match['competition']}

PROBABILIDADES DEL MODELO POISSON:
- Local: {probabilities['prob_home']}% (cuota justa: {probabilities['implied_home']})
- Empate: {probabilities['prob_draw']}% (cuota justa: {probabilities['implied_draw']})
- Visitante: {probabilities['prob_away']}% (cuota justa: {probabilities['implied_away']})
- Over 2.5: {probabilities['prob_over25']}% | Under 2.5: {probabilities['prob_under25']}%
- Over 3.5: {probabilities['prob_over35']}% | Under 3.5: {probabilities['prob_under35']}%
- BTTS Si: {probabilities['prob_btts_yes']}% | No: {probabilities['prob_btts_no']}%
- Marcador mas probable: {probabilities['most_likely_score']}
- xG local: {probabilities['lambda_home']} | xG visitante: {probabilities['lambda_away']}

FORMA RECIENTE:
{match['home']}: {_fmt_last5(stats['home_last5'])}
{match['away']}: {_fmt_last5(stats['away_last5'])}

ESTADISTICAS:
{match['home']}: {stats.get('home_goals_scored_avg','N/D')} goles anotados / {stats.get('home_goals_conceded_avg','N/D')} recibidos por partido
{match['away']}: {stats.get('away_goals_scored_avg','N/D')} goles anotados / {stats.get('away_goals_conceded_avg','N/D')} recibidos por partido

H2H: {_fmt_h2h(stats['h2h'])}

POSICION EN TABLA: {match['home']} #{stats.get('home_league_pos','N/D')} | {match['away']} #{stats.get('away_league_pos','N/D')}

CONFIANZA DEL MODELO: {probabilities['model_confidence']}

Como apostador experto debes:
1. Identificar si hay VALUE BET (cuando la cuota de mercado es mayor a la cuota justa del modelo)
2. Detectar patrones en la forma reciente
3. Recomendar la apuesta con mayor valor esperado
4. Indicar si hay que evitar este partido

Responde UNICAMENTE con este JSON valido:
{{
  "value_bets": ["apuesta 1 con razon", "apuesta 2 con razon"],
  "best_bet": "LA mejor apuesta concreta: mercado + razonamiento en 2 lineas",
  "risk_level": "bajo",
  "reasoning": "analisis experto en 3-4 oraciones: forma, stats, valor de la cuota",
  "avoid": "null o razon concreta para evitar apostar este partido"
}}"""


def _call_ollama(prompt: str) -> str:
    payload = {
        "model":    OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
        "format":   "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 800,
        },
    }
    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def _validate(result: dict) -> dict:
    missing = _REQUIRED_KEYS - set(result.keys())
    if missing:
        raise ValueError(f"Missing keys: {missing}")
    if not isinstance(result["value_bets"], list):
        result["value_bets"] = [str(result["value_bets"])]
    if result.get("risk_level") not in _VALID_RISK:
        result["risk_level"] = "medio"
    return result


def generate_analysis(match: dict, stats: dict, probabilities: dict) -> dict:
    prompt = _build_prompt(match, stats, probabilities)
    label  = f"{match['home']} vs {match['away']}"

    try:
        raw    = _call_ollama(prompt).strip()
        raw    = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        return _validate(result)
    except httpx.ConnectError:
        log.error(f"Ollama unreachable — is it running?")
    except httpx.HTTPStatusError as e:
        log.error(f"Ollama HTTP error for {label}: {e.response.status_code}")
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Ollama bad JSON for {label}: {e}")
    except Exception as e:
        log.error(f"Unexpected error for {label}: {e}")

    return _fallback_analysis(probabilities)


def _fallback_analysis(probabilities: dict) -> dict:
    if probabilities["prob_home"] >= probabilities["prob_away"]:
        best = f"Local — {probabilities['prob_home']}% prob (cuota justa {probabilities['implied_home']})"
    else:
        best = f"Visitante — {probabilities['prob_away']}% prob (cuota justa {probabilities['implied_away']})"
    return {
        "value_bets": [best],
        "best_bet":   best,
        "risk_level": "medio",
        "reasoning":  "Analisis narrativo no disponible. Se muestran probabilidades del modelo Poisson.",
        "avoid":      "null",
    }
