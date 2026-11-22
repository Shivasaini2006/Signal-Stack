import sys
import logging
import argparse
import signal
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core import db
from scripts.run_weekly import execute_weekly_pipeline
from scripts.run_monthly_audit import execute_monthly_audit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Scheduler] %(name)s: %(message)s",
)
logger = logging.getLogger("signal_stack.scheduler")


def parse_schedule_string(schedule_str: str, default_hour: int = 6, default_minute: int = 0):
    """
    Parses human/cron strings like:
    - 'mon 06:00' -> day_of_week='mon', hour=6, minute=0
    - '1 06:00' -> day=1, hour=6, minute=0
    - '0 6 * * 1' -> standard 5-part cron
    """
    parts = schedule_str.strip().split()
    if len(parts) == 2:
        day_part, time_part = parts[0], parts[1]
        time_tokens = time_part.split(":")
        hour = int(time_tokens[0])
        minute = int(time_tokens[1]) if len(time_tokens) > 1 else 0

        if day_part.isdigit():
            # Monthly day e.g. 1
            return {"day": int(day_part), "hour": hour, "minute": minute}
        else:
            # Day of week e.g. mon
            return {"day_of_week": day_part.lower(), "hour": hour, "minute": minute}
    elif len(parts) == 5:
        # Standard cron: minute hour day month day_of_week
        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
    return {"hour": default_hour, "minute": default_minute}


def create_scheduler(is_background: bool = False):
    """
    Creates and configures an APScheduler instance reading configuration
    from system_settings table with fallback to app.core.config.settings.
    """
    # 1. Read timezone from settings table
    tz_name = db.get_setting("timezone", settings.SCHEDULER_TIMEZONE) or "UTC"
    try:
        tz = pytz.timezone(tz_name)
    except Exception as e:
        logger.warning(f"Invalid timezone '{tz_name}', defaulting to UTC: {e}")
        tz = pytz.UTC

    # 2. Read weekly & monthly schedule configs from settings table
    weekly_str = db.get_setting("weekly_schedule", settings.WEEKLY_SCHEDULE_CRON) or "mon 06:00"
    monthly_str = db.get_setting("monthly_schedule", settings.MONTHLY_SCHEDULE_CRON) or "1 06:00"

    weekly_trigger_kwargs = parse_schedule_string(weekly_str, default_hour=6, default_minute=0)
    monthly_trigger_kwargs = parse_schedule_string(monthly_str, default_hour=6, default_minute=0)

    SchedulerClass = BackgroundScheduler if is_background else BlockingScheduler
    scheduler = SchedulerClass(timezone=tz)

    # Add Weekly Pipeline job
    scheduler.add_job(
        func=execute_weekly_pipeline,
        trigger=CronTrigger(**weekly_trigger_kwargs, timezone=tz),
        id="weekly_intelligence_pipeline",
        name="Weekly Autonomous Crawl, Rank & Briefing Pipeline",
        replace_existing=True,
    )
    logger.info(f"Scheduled Weekly Pipeline: {weekly_trigger_kwargs} ({tz_name})")

    # Add Monthly Audit job
    scheduler.add_job(
        func=execute_monthly_audit,
        trigger=CronTrigger(**monthly_trigger_kwargs, timezone=tz),
        id="monthly_source_audit",
        name="Monthly Source Portfolio Health & Relevance Audit",
        replace_existing=True,
    )
    logger.info(f"Scheduled Monthly Audit: {monthly_trigger_kwargs} ({tz_name})")

    return scheduler


def start_scheduler():
    """Runs local scheduler in foreground."""
    scheduler = create_scheduler(is_background=False)
    logger.info("Signal Stack local scheduler running. Press Ctrl+C to terminate.")

    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received. Stopping scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signal Stack Local APScheduler Runner")
    parser.add_argument("--set-timezone", type=str, help="Update timezone in settings table")
    parser.add_argument("--set-weekly", type=str, help="Update weekly schedule e.g. 'mon 06:00'")
    parser.add_argument("--set-monthly", type=str, help="Update monthly schedule e.g. '1 06:00'")
    args = parser.parse_args()

    if args.set_timezone:
        db.set_setting("timezone", args.set_timezone, "Scheduler execution timezone")
        print(f"Updated scheduler timezone: {args.set_timezone}")

    if args.set_weekly:
        db.set_setting("weekly_schedule", args.set_weekly, "Weekly pipeline schedule")
        print(f"Updated weekly schedule: {args.set_weekly}")

    if args.set_monthly:
        db.set_setting("monthly_schedule", args.set_monthly, "Monthly audit schedule")
        print(f"Updated monthly schedule: {args.set_monthly}")

    start_scheduler()
