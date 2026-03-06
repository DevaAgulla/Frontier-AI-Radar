"""APScheduler-based daily cron job for Frontier AI Radar.

Runs the full pipeline once a day at the configured time,
fetching ALL subscribed user emails and emailing them the digest.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from db.connection import get_session, init_db
from db.models import User
import structlog

logger = structlog.get_logger()

_scheduler: AsyncIOScheduler | None = None


async def _daily_full_run() -> None:
    """Job function: run full pipeline and email all subscribers."""
    # Import here to avoid circular imports at module level
    from pipeline.runner import run_radar

    logger.info("Scheduler: daily full run triggered")

    # Fetch all subscribed / registered users from DB
    init_db()  # no-op if already initialised
    with get_session() as session:
        users = session.query(User).all()
        db_emails = [u.email.strip().lower() for u in users if u.email]

    # Also include .env EMAIL_RECIPIENTS
    env_emails = [
        e.strip().lower()
        for e in settings.email_recipients.split(",")
        if e.strip()
    ]

    # Merge & deduplicate
    seen: set = set()
    email_recipients: list = []
    for email in db_emails + env_emails:
        if email and email not in seen:
            seen.add(email)
            email_recipients.append(email)

    if not email_recipients:
        logger.warning("Scheduler: no subscribed users — skipping run")
        return

    logger.info("Scheduler: sending to %d recipients", len(email_recipients), emails=email_recipients)

    try:
        state = await run_radar(
            mode="full",
            since_days=1,
            trigger="job",
            user_id=None,
            email_recipients=email_recipients,
        )
        logger.info(
            "Scheduler: daily run completed",
            run_id=state.get("run_id"),
            findings=len(state.get("ranked_findings", [])),
            email_status=state.get("email_status", ""),
        )
    except Exception as e:
        logger.exception("Scheduler: daily run failed", error=str(e))


def start_scheduler() -> None:
    """Start the APScheduler cron job.  Call once at app startup."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler: already running — skipping start")
        return

    # Parse configured time  (e.g. "09:00" → hour=9, minute=0)
    parts = settings.daily_run_time.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    _scheduler = AsyncIOScheduler(timezone=settings.timezone)
    _scheduler.add_job(
        _daily_full_run,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_full_run",
        name="Daily full pipeline run",
        replace_existing=True,
    )
    _scheduler.start()

    logger.info(
        "Scheduler: started",
        run_time=settings.daily_run_time,
        timezone=settings.timezone,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler.  Call at app shutdown."""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler: stopped")
