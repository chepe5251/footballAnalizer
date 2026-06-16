"""
analyzer.py — LLM narrative generation via local Ollama instance.

One synchronous HTTP call per match. Receives pre-computed statistical data
and returns a structured dict with human-readable analysis in Spanish.
Falls back gracefully when Ollama is unavailable or returns malformed output.
"""

import json

import httpx

from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from logger import log

# Keys the LLM must return; used to validate the response structure
_REQUIRED_KEYS = {"key_factors", "detailed_analysis", "best_bet", "value_bet", "risk_level"}
_VALID_RISK    = {"bajo", "medio", "alto"}


# ── Prompt helpers ────────────────────────────────────────────────────────────

def _fmt_last5(last5: list) -> str:
    if not last5:
        return "Sin datos"
    return " | ".join(
        f"{m['result']} vs {m['opponent']} ({m['goals_for']}-{m['goals_against']})"
        for m in last5
    )


def _fmt_h2h(h2h: list) -> str:
    if not h2h:
        return "Sin datos de H2H"
    return "\n".join(
        f"  {m['date']}: {m['home']} vs {m['away']} → {m['score']}"
        for m in h2h
    )


def _build_prompt(match: dict, stats: dict, probabilities: dict) -> str:
    return f"""Eres un analista experto de fútbol y apuestas deportivas.
Se te proporcionan datos estadísticos ya calculados sobre el siguiente partido.
Tu trabajo es interpretar esos datos y escribir un análisis profesional en español.

PARTIDO: {match['home']} vs {match['away']}
COMPETICIÓN: {match['competition']}
HORA: {match.get('time_utc', 'Por confirmar')} UTC

PROBABILIDADES CALCULADAS (modelo Poisson + Dixon-Coles):
- Victoria local:    {probabilities['prob_home']}%  (cuota implícita: {probabilities['implied_home']})
- Empate:            {probabilities['prob_draw']}%  (cuota implícita: {probabilities['implied_draw']})
- Victoria visitante:{probabilities['prob_away']}%  (cuota implícita: {probabilities['implied_away']})
- Over 2.5: {probabilities['prob_over25']}%  | Under 2.5: {probabilities['prob_under25']}%
- Over 3.5: {probabilities['prob_over35']}%  | Under 3.5: {probabilities['prob_under35']}%
- BTTS Sí:  {probabilities['prob_btts_yes']}% | BTTS No:   {probabilities['prob_btts_no']}%
- Marcador más probable: {probabilities['most_likely_score']}
- Goles esperados: {match['home']} {probabilities['lambda_home']} — {match['away']} {probabilities['lambda_away']}

FORMA RECIENTE:
{match['home']} (últimos 5): {_fmt_last5(stats['home_last5'])}
{match['away']} (últimos 5): {_fmt_last5(stats['away_last5'])}

POSICIÓN EN TABLA:
{match['home']}: #{stats.get('home_league_pos', 'N/D')}
{match['away']}: #{stats.get('away_league_pos', 'N/D')}

HISTORIAL H2H (últimos 5 encuentros):
{_fmt_h2h(stats['h2h'])}

ESTADÍSTICAS DE GOLES (promedio por partido esta temporada):
{match['home']}: {stats.get('home_goals_scored_avg', 'N/D')} anotados / {stats.get('home_goals_conceded_avg', 'N/D')} recibidos
{match['away']}: {stats.get('away_goals_scored_avg', 'N/D')} anotados / {stats.get('away_goals_conceded_avg', 'N/D')} recibidos

CONFIANZA DEL MODELO: {probabilities['model_confidence']}

Responde ÚNICAMENTE con el siguiente JSON válido. Sin markdown, sin texto extra.
El campo "risk_level" debe ser exactamente una de estas tres cadenas: "bajo", "medio", "alto".
{{
  "key_factors": ["factor 1", "factor 2", "factor 3", "factor 4", "factor 5"],
  "detailed_analysis": "análisis detallado de 5-7 oraciones explicando forma, H2H, estadísticas y qué esperar",
  "best_bet": "la apuesta con mejor valor según los datos, con razonamiento breve",
  "value_bet": "si las cuotas implícitas sugieren valor respecto a cuotas de mercado típicas, explicar",
  "risk_level": "bajo"
}}"""


# ── Ollama HTTP call ──────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> str:
    """
    Sends a chat request to the local Ollama instance.
    Uses format='json' to force the model to emit valid JSON.
    Timeout is generous (120 s) since local inference can be slow on CPU.
    """
    payload = {
        "model":   OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream":  False,
        "format":  "json",
        "options": {
            "temperature": 0.1,   # low temp for deterministic structured output
            "num_predict": 1024,
        },
    }
    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


# ── Response validation ───────────────────────────────────────────────────────

def _validate(result: dict) -> dict:
    """Coerce the LLM response into the expected shape, fixing common issues."""
    missing = _REQUIRED_KEYS - set(result.keys())
    if missing:
        raise ValueError(f"LLM response missing keys: {missing}")

    # Ensure key_factors is a list
    if not isinstance(result["key_factors"], list):
        result["key_factors"] = [str(result["key_factors"])]
    result["key_factors"] = [str(f) for f in result["key_factors"][:5]]

    # Clamp risk_level to known values
    if result.get("risk_level") not in _VALID_RISK:
        result["risk_level"] = "medio"

    return result


# ── Public API ────────────────────────────────────────────────────────────────

def generate_analysis(match: dict, stats: dict, probabilities: dict) -> dict:
    """
    Calls the local Ollama LLM and returns a structured analysis dict.
    On any failure, returns a stats-only fallback so Telegram messages still go out.
    """
    prompt = _build_prompt(match, stats, probabilities)
    label  = f"{match['home']} vs {match['away']}"

    try:
        raw = _call_ollama(prompt)
        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        return _validate(result)

    except httpx.ConnectError:
        log.error(f"Ollama unreachable at {OLLAMA_BASE_URL} — is it running?")
    except httpx.HTTPStatusError as e:
        log.error(f"Ollama HTTP error for {label}: {e.response.status_code} {e.response.text[:200]}")
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Ollama returned invalid/incomplete JSON for {label}: {e}")
    except Exception as e:
        log.error(f"Unexpected error calling Ollama for {label}: {e}")

    return _fallback_analysis(match, probabilities)


def _fallback_analysis(match: dict, probabilities: dict) -> dict:
    """Returns a minimal stats-only analysis when the LLM is unavailable."""
    if probabilities["prob_home"] >= probabilities["prob_away"]:
        best = f"Victoria local — {probabilities['prob_home']}% de probabilidad (cuota {probabilities['implied_home']})"
    else:
        best = f"Victoria visitante — {probabilities['prob_away']}% de probabilidad (cuota {probabilities['implied_away']})"

    return {
        "key_factors": [
            f"Probabilidad local: {probabilities['prob_home']}%",
            f"Probabilidad empate: {probabilities['prob_draw']}%",
            f"Probabilidad visitante: {probabilities['prob_away']}%",
            f"Over 2.5: {probabilities['prob_over25']}%",
            f"BTTS Sí: {probabilities['prob_btts_yes']}%",
        ],
        "detailed_analysis": (
            "Análisis narrativo no disponible (Ollama inaccesible o error de formato). "
            "Se muestran las probabilidades calculadas por el modelo estadístico."
        ),
        "best_bet": best,
        "value_bet": "Análisis de valor no disponible.",
        "risk_level": "medio",
    }
