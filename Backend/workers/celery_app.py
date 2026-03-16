"""Celery application — broker, result backend, and queue routing.

Queues
------
digest_q  high-priority  LangGraph pipeline (one run per task)
audio_q   low-priority   ElevenLabs TTS generation
blob_q    low-priority   Azure Blob upload + DB metadata write

Workers
-------
Start digest workers (2 processes, each with asyncio loop):
    celery -A workers.celery_app worker -Q digest_q -c 2 --pool=solo -l info

Start audio+blob workers (1 process is enough — I/O bound):
    celery -A workers.celery_app worker -Q audio_q,blob_q -c 2 -l info

Start beat scheduler (replaces APScheduler):
    celery -A workers.celery_app beat -l info
"""

from __future__ import annotations

import asyncio
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from config.settings import settings

# ── App ───────────────────────────────────────────────────────────────────────

celery_app = Celery(
    "frontier_radar",
    broker=settings.redis_url or "redis://localhost:6379/0",
    backend=settings.redis_url or "redis://localhost:6379/0",
    include=["workers.tasks"],
)

# ── Serialisation ─────────────────────────────────────────────────────────────

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    enable_utc=True,
    # Keep results for 48 h — enough for the UI to poll run status
    result_expires=48 * 3600,
    # Ack only after the task finishes (safe re-delivery on worker crash)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # One pipeline at a time per worker process (LangGraph is already async-parallel inside)
    worker_prefetch_multiplier=1,
)

# ── Queues ────────────────────────────────────────────────────────────────────

default_exchange = Exchange("frontier", type="direct")

celery_app.conf.task_queues = (
    Queue("digest_q", default_exchange, routing_key="digest", queue_arguments={"x-max-priority": 10}),
    Queue("audio_q",  default_exchange, routing_key="audio"),
    Queue("blob_q",   default_exchange, routing_key="blob"),
)
celery_app.conf.task_default_queue    = "digest_q"
celery_app.conf.task_default_exchange = "frontier"
celery_app.conf.task_default_routing_key = "digest"

celery_app.conf.task_routes = {
    "workers.tasks.run_digest_pipeline":  {"queue": "digest_q"},
    "workers.tasks.generate_audio_task":  {"queue": "audio_q"},
    "workers.tasks.upload_blob_task":     {"queue": "blob_q"},
    "workers.tasks.daily_digest_job":     {"queue": "digest_q"},
}

# ── Beat schedule (replaces APScheduler) ─────────────────────────────────────
# Reads daily_run_time from settings (e.g. "17:00" IST).

_hour, _minute = (int(x) for x in settings.daily_run_time.split(":"))

celery_app.conf.beat_schedule = {
    "daily-frontier-digest": {
        "task":     "workers.tasks.daily_digest_job",
        "schedule": crontab(hour=_hour, minute=_minute),
        "options":  {"queue": "digest_q"},
    },
}


# ── Asyncio helper ────────────────────────────────────────────────────────────

def run_async(coro):
    """Run an async coroutine from a sync Celery task.

    Uses a fresh event loop per call — avoids loop-reuse issues across forks.
    On Windows the selector policy is set automatically so psycopg v3 works.
    """
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
