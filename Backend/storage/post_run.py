"""Post-run orchestration: audio generation + Azure Blob upload.

Called from pipeline/runner.py after the LangGraph pipeline completes.
All steps are gracefully skipped on missing credentials or errors —
the pipeline result is never affected.

Flow:
  1.  PDF is already on disk (pdf_path from final_state)
  2.  Generate audio from PDF via ElevenLabs  (skipped if no API key)
  3.  Upload PDF  → Frontier-AI-Radar/digest-<date>/digest.pdf
  4.  Upload audio → Frontier-AI-Radar/digest-<date>/digest_audio.mp3
  5.  Store blob paths on the Run DB row
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


async def post_run_upload(pdf_path_str: str, run_db_id: int) -> None:
    """Generate audio and upload PDF + audio to Azure Blob.

    Fully non-blocking in terms of exceptions — any failure is logged and
    swallowed so it never propagates back to the pipeline caller.
    """
    if not pdf_path_str:
        logger.info("post_run_upload: no pdf_path, skipping")
        return

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        logger.warning("post_run_upload: PDF not found on disk", path=pdf_path_str)
        return

    # ── Step 1: Generate audio (if ElevenLabs key is available) ──────────────
    audio_path: Optional[Path] = None
    try:
        audio_path = await _generate_audio(pdf_path)
    except Exception as exc:
        logger.warning("post_run_upload: audio generation failed", error=str(exc))

    # ── Step 2: Upload to Azure Blob ─────────────────────────────────────────
    try:
        await _upload_to_blob(pdf_path, audio_path, run_db_id)
    except Exception as exc:
        logger.warning("post_run_upload: blob upload failed", error=str(exc))


# ── private helpers ───────────────────────────────────────────────────────────

async def _generate_audio(pdf_path: Path) -> Optional[Path]:
    """Attempt to generate an audio MP3 from *pdf_path* using ElevenLabs.

    Returns the Path to the saved MP3, or None if skipped / unavailable.
    """
    # Resolve API key: voice/config.env takes priority over .env
    api_key = _resolve_elevenlabs_key()
    if not api_key:
        logger.info("post_run_upload: ElevenLabs key not configured — skipping audio")
        return None

    from voice.generate_voice_digest import run as tts_run, VOICE_PRESETS  # noqa: F401
    from voice.generate_voice_digest import _load_config_env, CONFIG_ENV

    cfg = _load_config_env(CONFIG_ENV)
    voice_name   = cfg.get("VOICE_PRESET",  "rachel")
    audio_format = cfg.get("AUDIO_FORMAT",  "mp3_44100_128")
    chunk_size   = int(cfg.get("CHUNK_SIZE", 4500))

    logger.info("post_run_upload: generating audio", voice=voice_name, pdf=pdf_path.name)

    # tts_run is synchronous (blocking HTTP) — offload to thread pool
    loop = asyncio.get_event_loop()
    audio_path: Path = await loop.run_in_executor(
        None,
        lambda: tts_run(pdf_path, voice_name, api_key, audio_format, chunk_size),
    )
    logger.info("post_run_upload: audio ready", audio=str(audio_path))
    return audio_path


def _resolve_elevenlabs_key() -> str:
    """Return the ElevenLabs API key from voice/config.env or settings."""
    try:
        from voice.generate_voice_digest import _load_config_env, CONFIG_ENV
        cfg = _load_config_env(CONFIG_ENV)
        key = cfg.get("ELEVENLABS_API_KEY", "")
        if key and key not in ("", "your_api_key_here"):
            return key
    except Exception:
        pass
    try:
        from config.settings import settings
        key = settings.elevenlabs_api_key or ""
        if key and key not in ("", "your_api_key_here"):
            return key
    except Exception:
        pass
    return ""


async def _upload_to_blob(
    pdf_path: Path,
    audio_path: Optional[Path],
    run_db_id: int,
) -> None:
    """Upload PDF (and optionally audio) to Azure Blob, then persist paths to DB."""
    from storage.blob import is_configured, blob_path_for_run, upload_file

    if not is_configured():
        logger.info("post_run_upload: Azure Blob not configured — skipping upload")
        return

    # Derive date string from PDF filename ("digest-20260315-170000.pdf" → "20260315-170000")
    m = re.search(r"digest-(\d{8}-\d{6})", pdf_path.stem)
    date_str = m.group(1) if m else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    blob_pdf_path: Optional[str] = None
    blob_audio_path: Optional[str] = None

    # Upload PDF
    try:
        bp = blob_path_for_run(date_str, "digest.pdf")
        upload_file(pdf_path, bp)
        blob_pdf_path = bp
    except Exception as exc:
        logger.error("post_run_upload: PDF upload failed", error=str(exc))

    # Upload audio
    if audio_path and audio_path.exists():
        try:
            ba = blob_path_for_run(date_str, "digest_audio.mp3")
            upload_file(audio_path, ba)
            blob_audio_path = ba
        except Exception as exc:
            logger.error("post_run_upload: audio upload failed", error=str(exc))

    # Persist blob paths to DB
    if blob_pdf_path or blob_audio_path:
        from db.persist import update_run_blob_paths
        update_run_blob_paths(
            run_db_id=run_db_id,
            blob_pdf_path=blob_pdf_path,
            blob_audio_path=blob_audio_path,
        )
        logger.info(
            "post_run_upload: blob paths saved",
            run_id=run_db_id,
            pdf=blob_pdf_path,
            audio=blob_audio_path,
        )
