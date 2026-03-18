"""Celery task definitions for Frontier AI Radar.

Task chain per daily run
------------------------

  daily_digest_job          (beat trigger)
       │
       ▼
  run_digest_pipeline       (digest_q — runs LangGraph, writes DB + Redis)
       │  on_success
       ▼
  generate_audio_task       (audio_q — ElevenLabs TTS, returns local audio path)
       │  on_success
       ▼
  upload_blob_task          (blob_q  — Azure Blob upload, updates DB blob paths)

The API never waits for the chain to finish.  It returns run_id immediately
and the frontend polls GET /api/v1/runs/{run_id} for status.
"""

from __future__ import annotations

import logging
from typing import Optional

import structlog
from celery import chain

from workers.celery_app import celery_app, run_async

logger = structlog.get_logger()


# ── Digest pipeline ───────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="workers.tasks.run_digest_pipeline",
    max_retries=2,
    default_retry_delay=60,
    queue="digest_q",
    # Soft limit: warn after 20 min; hard limit: kill after 30 min
    soft_time_limit=1200,
    time_limit=1800,
)
def run_digest_pipeline(
    self,
    run_db_id: int,
    mode: str = "full",
    since_days: int = 1,
    period: str = "daily",
    email_recipients: Optional[list[str]] = None,
    custom_urls: Optional[list[str]] = None,
    url_mode: str = "default",
) -> dict:
    """Run the full LangGraph pipeline for one digest.

    Returns a summary dict that becomes the argument to the audio task
    when chained: ``run_digest_pipeline.s(...) | generate_audio_task.s()``
    """
    try:
        from pipeline.runner import execute_prepared_radar, create_initial_state
        from db.persist import start_run, finish_run

        logger.info("celery_digest_start", run_db_id=run_db_id, mode=mode)

        # Reconstruct initial state from run_db_id (extraction row already created
        # by the API before enqueuing — pass 0 for extraction_db_id; runner will
        # look it up or it is already set on the Run row).
        from db.connection import get_session as db_session
        from db.models import Run
        from sqlalchemy import text

        with db_session() as sess:
            run_row = sess.get(Run, run_db_id)
            extraction_db_id = run_row.extraction_id if run_row else 0

        initial_state = create_initial_state(
            run_mode=mode,
            since_days=since_days,
            report_type=period,
            extraction_db_id=extraction_db_id,
            run_db_id=run_db_id,
            email_recipients=email_recipients or [],
            custom_urls=custom_urls or [],
            url_mode=url_mode,
        )

        final_state = run_async(execute_prepared_radar(initial_state))

        pdf_path = final_state.get("pdf_path", "")
        logger.info(
            "celery_digest_done",
            run_db_id=run_db_id,
            findings=len(final_state.get("ranked_findings", [])),
            pdf_path=pdf_path,
        )

        # Cache the digest JSON and markdown in Redis so the API serves it instantly
        _cache_digest(run_db_id, final_state)

        # Return context for the downstream audio task
        return {"run_db_id": run_db_id, "pdf_path": pdf_path}

    except Exception as exc:
        logger.error("celery_digest_failed", run_db_id=run_db_id, error=str(exc))
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            from db.persist import finish_run
            finish_run(run_db_id=run_db_id, status="failure",
                       elapsed_seconds=0, summary={"error": str(exc)})
            raise


# ── Audio generation ──────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="workers.tasks.generate_audio_task",
    max_retries=2,
    default_retry_delay=30,
    queue="audio_q",
    soft_time_limit=300,   # ElevenLabs calls can be slow for long digests
    time_limit=360,
)
def generate_audio_task(self, digest_result: dict) -> dict:
    """Generate ElevenLabs audio from the PDF produced by the digest pipeline.

    ``digest_result`` is the dict returned by ``run_digest_pipeline``:
        {"run_db_id": int, "pdf_path": str}

    Returns a dict passed to ``upload_blob_task``.
    Skipped entirely when ENABLE_ELEVENLABS=0.
    """
    run_db_id = digest_result.get("run_db_id", 0)
    pdf_path  = digest_result.get("pdf_path", "")

    # Check feature flag
    try:
        from config.settings import settings
        if not settings.enable_elevenlabs:
            logger.info("celery_audio_skip", reason="elevenlabs_disabled", run_db_id=run_db_id)
            return {"run_db_id": run_db_id, "pdf_path": pdf_path, "audio_path": ""}
    except Exception:
        pass

    if not pdf_path:
        logger.info("celery_audio_skip", reason="no_pdf_path", run_db_id=run_db_id)
        return {"run_db_id": run_db_id, "pdf_path": pdf_path, "audio_path": ""}

    try:
        from pathlib import Path
        audio_path = run_async(_generate_audio_async(Path(pdf_path)))
        audio_path_str = str(audio_path) if audio_path else ""
        logger.info("celery_audio_done", run_db_id=run_db_id, audio_path=audio_path_str)
        return {"run_db_id": run_db_id, "pdf_path": pdf_path, "audio_path": audio_path_str}

    except Exception as exc:
        logger.warning("celery_audio_failed", run_db_id=run_db_id, error=str(exc))
        # Audio failure must never fail the chain — return without audio path
        return {"run_db_id": run_db_id, "pdf_path": pdf_path, "audio_path": ""}


async def _generate_audio_async(pdf_path):
    """Thin async wrapper around the existing post_run audio generation."""
    try:
        from storage.post_run import _generate_audio
        return await _generate_audio(pdf_path)
    except Exception as exc:
        logger.warning("audio_generation_failed", error=str(exc))
        return None


# ── Blob upload ───────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="workers.tasks.upload_blob_task",
    max_retries=3,
    default_retry_delay=30,
    queue="blob_q",
    soft_time_limit=120,
    time_limit=180,
)
def upload_blob_task(self, audio_result: dict) -> dict:
    """Upload PDF and audio to Azure Blob Storage, then update DB paths.

    ``audio_result`` is the dict returned by ``generate_audio_task``.
    """
    run_db_id  = audio_result.get("run_db_id", 0)
    pdf_path   = audio_result.get("pdf_path", "")
    audio_path = audio_result.get("audio_path", "")

    try:
        from pathlib import Path
        run_async(_upload_async(
            pdf_path   = Path(pdf_path)   if pdf_path   else None,
            audio_path = Path(audio_path) if audio_path else None,
            run_db_id  = run_db_id,
        ))
        logger.info("celery_blob_done", run_db_id=run_db_id)
        return {"run_db_id": run_db_id, "status": "uploaded"}

    except Exception as exc:
        logger.warning("celery_blob_failed", run_db_id=run_db_id, error=str(exc))
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error("celery_blob_max_retries", run_db_id=run_db_id)
            return {"run_db_id": run_db_id, "status": "blob_failed"}


async def _upload_async(pdf_path, audio_path, run_db_id: int):
    """Thin async wrapper around existing blob upload logic."""
    try:
        from storage.post_run import _upload_to_blob
        await _upload_to_blob(pdf_path, audio_path, run_db_id)
    except Exception as exc:
        logger.warning("blob_upload_failed", error=str(exc))


# ── Daily cron job (Celery beat entry point) ──────────────────────────────────

@celery_app.task(
    name="workers.tasks.daily_digest_job",
    queue="digest_q",
)
def daily_digest_job() -> str:
    """Triggered by Celery beat at the configured daily_run_time.

    1. Resolves all subscriber emails from DB + .env
    2. Creates a DB run row
    3. Chains: digest → audio → blob
    4. Returns the run_db_id immediately (non-blocking)
    """
    from db.persist import start_run
    from db.connection import get_session as db_session
    from db.models import User
    from config.settings import settings

    # Collect subscribers
    email_set: set[str] = set(
        e.strip() for e in settings.email_recipients.split(",") if e.strip()
    )
    with db_session() as sess:
        for user in sess.query(User).filter(User.email.isnot(None)).all():
            if user.email:
                email_set.add(user.email.strip())

    extraction_db_id, run_db_id = start_run(mode="job", user_id=None)

    logger.info("celery_daily_job_enqueued", run_db_id=run_db_id,
                recipients=len(email_set))

    # Chain: digest → (audio →) blob  [audio skipped when ENABLE_ELEVENLABS=0]
    digest_step = run_digest_pipeline.s(
        run_db_id=run_db_id,
        mode="full",
        since_days=1,
        email_recipients=list(email_set),
    )
    if settings.enable_elevenlabs:
        task_chain = digest_step | generate_audio_task.s() | upload_blob_task.s()
    else:
        task_chain = digest_step | upload_blob_task.s()
    task_chain.apply_async()

    return f"run_{run_db_id}_enqueued"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_digest(run_db_id: int, final_state: dict) -> None:
    """Cache the digest result in Redis so API pods serve it at ~0ms."""
    try:
        from cache.redis_client import rset
        import json

        digest_payload = {
            "run_db_id":       run_db_id,
            "digest_json":     final_state.get("digest_json", {}),
            "digest_markdown": final_state.get("digest_markdown", ""),
            "ranked_findings": [
                {k: v for k, v in f.items() if k != "evidence_snippet"}
                for f in final_state.get("ranked_findings", [])[:30]
            ],
            "errors_count":    len(final_state.get("errors", [])),
        }
        # TTL: 25 h — covers the next daily run with margin
        rset(f"digest:run:{run_db_id}", digest_payload, ttl=25 * 3600)
        # Also write to the "latest" key so the frontend can always get today's digest
        rset("digest:latest", digest_payload, ttl=25 * 3600)
        logger.info("digest_cached", run_db_id=run_db_id)
    except Exception as exc:
        logger.warning("digest_cache_failed", error=str(exc))
