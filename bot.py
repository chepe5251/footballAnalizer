import asyncio
import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from logger import log

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def send_message(text: str) -> bool:
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(f"{BASE_URL}/sendMessage", json=payload, timeout=30)
            if r.status_code == 200:
                return True
            log.error(f"Telegram error {r.status_code}: {r.text}")
        except Exception as e:
            log.error(f"Telegram request failed: {e}")

    await asyncio.sleep(10)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(f"{BASE_URL}/sendMessage", json=payload, timeout=30)
            if r.status_code == 200:
                return True
            log.error(f"Telegram retry failed {r.status_code}: {r.text}")
        except Exception as e:
            log.error(f"Telegram retry failed: {e}")
    return False


async def send_match_analysis(match: dict, stats: dict,
                               probabilities: dict, analysis: dict):
    from formatter import build_summary_message, build_detailed_message
    summary = build_summary_message(match, probabilities, analysis, stats=stats)
    detail  = build_detailed_message(match, stats, probabilities, analysis)
    await send_message(summary)
    await asyncio.sleep(3)
    await send_message(detail)


async def send_error_notification(error_msg: str):
    await send_message(f"🚨 *Football Agent Error*\n{error_msg}")


async def send_daily_header(match_count: int):
    from datetime import date
    await send_message(
        f"🌅 *Análisis del día — {date.today().strftime('%d/%m/%Y')}*\n"
        f"📋 Partidos encontrados: *{match_count}*\n"
        f"⏳ Enviando análisis...\n"
        f"{'─' * 30}"
    )


async def send_daily_footer(success: int, failed: int):
    await send_message(
        f"✅ *Análisis completado*\n"
        f"Enviados: {success} | Fallidos: {failed}\n"
        f"{'─' * 30}"
    )
