import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from data import get_todays_matches, get_team_stats
from model import calculate_poisson_probabilities
from analyzer import generate_analysis
from bot import send_match_analysis, send_error_notification, send_daily_header, send_daily_footer
from logger import log

CST = pytz.timezone("America/Costa_Rica")


async def analyze_single_match(match: dict) -> bool:
    try:
        log.info(f"Analyzing: {match['home']} vs {match['away']} ({match['competition']})")

        stats = get_team_stats(
            match["home"],
            match["away"],
            match["league_id"],
            match["season"],
            home_id=match.get("home_id", ""),
            away_id=match.get("away_id", ""),
            espn_id=match.get("espn_id", ""),
            match_data=match
        )

        probabilities = calculate_poisson_probabilities(stats)
        analysis      = generate_analysis(match, stats, probabilities)
        await send_match_analysis(match, stats, probabilities, analysis)

        log.info(f"Done: {match['home']} vs {match['away']}")
        return True

    except Exception as e:
        log.error(f"Failed {match['home']} vs {match['away']}: {e}")
        return False


async def daily_pipeline():
    log.info("=== Daily pipeline started ===")
    success, failed = 0, 0

    try:
        matches = get_todays_matches()
        log.info(f"Found {len(matches)} matches today")

        if not matches:
            await send_error_notification("No se encontraron partidos para hoy.")
            return

        await send_daily_header(len(matches))

        for match in matches:
            result = await analyze_single_match(match)
            if result:
                success += 1
            else:
                failed += 1
            await asyncio.sleep(5)

        await send_daily_footer(success, failed)

    except Exception as e:
        log.error(f"Pipeline error: {e}")
        await send_error_notification(f"Error critico: {e}")

    log.info(f"=== Pipeline done: {success} success, {failed} failed ===")


async def main():
    scheduler = AsyncIOScheduler(timezone=CST)
    scheduler.add_job(
        daily_pipeline,
        CronTrigger(hour=8, minute=0, timezone=CST),
        id="daily_football_analysis",
        replace_existing=True
    )
    scheduler.start()
    log.info("Scheduler running. Next execution at 8:00 AM CST.")
    log.info("Running pipeline immediately for initial test...")
    await daily_pipeline()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        log.info("Agent stopped.")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
