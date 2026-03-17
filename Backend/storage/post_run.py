"""Post-run orchestration: audio script generation + Azure Blob upload.

Called from pipeline/runner.py after the LangGraph pipeline completes.
All steps are gracefully skipped on missing credentials or errors —
the pipeline result is never affected.

New two-phase audio flow (2026-03-17):
──────────────────────────────────────
  Phase 1  (runs here, immediately after pipeline):
    PDF text → LLM audiobook formatter → narration script (.txt)
    → upload script to blob: Frontier-AI-Radar/digest-<date>/audio_script.txt
    → save path in runs.audio_script_blob_path

  Phase 2  (on-demand, triggered by user selecting a voice preset in UI):
    Read script from blob → ElevenLabs TTS (batched) → MP3
    → upload MP3 to blob: Frontier-AI-Radar/digest-<date>/presets/<preset_id>.mp3
    → upsert runs.audio_presets_paths JSON
    → upsert runs.blob_sas_cache["audio"][preset_id]
    (handled by api/main.py:generate_audio_on_demand)

PDF upload flow (unchanged):
    PDF → Azure Blob → runs.blob_pdf_path
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

# Local directory for cached audio scripts (avoids repeated LLM calls)
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "data" / "audio_scripts"


async def post_run_upload(pdf_path_str: str, run_db_id: int) -> None:
    """Run audio script generation + PDF upload after pipeline completes.

    Swallows all exceptions so the pipeline result is never affected.
    """
    if not pdf_path_str:
        logger.info("post_run_upload: no pdf_path, skipping")
        return

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        logger.warning("post_run_upload: PDF not found on disk", path=pdf_path_str)
        return

    # Derive date string for blob path naming ("digest-20260317-170000.pdf" → "20260317-170000")
    m = re.search(r"digest-(\d{8}-\d{6})", pdf_path.stem)
    date_str = m.group(1) if m else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # ── Phase 1: Generate + store audio script ────────────────────────────────
    try:
        await _generate_and_store_audio_script(pdf_path, run_db_id, date_str)
    except Exception as exc:
        logger.warning("post_run_upload: audio script generation failed", error=str(exc))

    # ── Phase 2: Upload PDF to Azure Blob ─────────────────────────────────────
    try:
        await _upload_pdf_to_blob(pdf_path, run_db_id, date_str)
    except Exception as exc:
        logger.warning("post_run_upload: PDF blob upload failed", error=str(exc))


# ── private helpers ───────────────────────────────────────────────────────────

async def _generate_and_store_audio_script(
    pdf_path: Path,
    run_db_id: int,
    date_str: str,
) -> None:
    """Extract PDF text → LLM formatter → save script locally + upload to blob."""

    # 1. Extract text from PDF
    loop = asyncio.get_event_loop()
    raw_text: str = await loop.run_in_executor(None, _extract_pdf_text, pdf_path)
    if not raw_text.strip():
        logger.warning("post_run_upload: PDF produced no text, skipping script generation")
        return

    # 2. Run LLM audiobook formatter (blocking — offload to thread)
    logger.info("post_run_upload: running audiobook formatter", pdf=pdf_path.name)
    narration: str = await loop.run_in_executor(None, _run_audiobook_formatter, raw_text)
    if not narration.strip():
        logger.warning("post_run_upload: audiobook formatter returned empty text")
        return

    # 3. Save locally (fast access for on-demand generation, no blob fetch needed)
    _SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    local_script_path = _SCRIPT_DIR / f"digest-{date_str}_script.txt"
    local_script_path.write_text(narration, encoding="utf-8")
    logger.info("post_run_upload: audio script saved locally", path=str(local_script_path),
                words=len(narration.split()))

    # 4. Upload to blob (if configured) and save path to DB
    from storage.blob import is_configured, blob_path_for_run, upload_text
    if is_configured():
        try:
            blob_path = blob_path_for_run(date_str, "audio_script.txt")
            upload_text(narration, blob_path)
            from db.persist import update_audio_script_path
            update_audio_script_path(run_db_id, blob_path)
            logger.info("post_run_upload: audio script uploaded to blob", blob=blob_path)
        except Exception as exc:
            logger.warning("post_run_upload: blob upload of audio script failed", error=str(exc))
            # Still save local path so on-demand generation can find the script
            from db.persist import update_audio_script_path
            update_audio_script_path(run_db_id, str(local_script_path))
    else:
        # No blob — save the local path so on-demand generation can read it
        from db.persist import update_audio_script_path
        update_audio_script_path(run_db_id, str(local_script_path))


async def _upload_pdf_to_blob(pdf_path: Path, run_db_id: int, date_str: str) -> None:
    """Upload PDF to Azure Blob and persist blob_pdf_path to DB."""
    from storage.blob import is_configured, blob_path_for_run, upload_file

    if not is_configured():
        logger.info("post_run_upload: Azure Blob not configured — skipping PDF upload")
        return

    blob_pdf_path: Optional[str] = None
    try:
        bp = blob_path_for_run(date_str, "digest.pdf")
        upload_file(pdf_path, bp)
        blob_pdf_path = bp
    except Exception as exc:
        logger.error("post_run_upload: PDF upload failed", error=str(exc))

    if blob_pdf_path:
        from db.persist import update_run_blob_paths
        update_run_blob_paths(run_db_id=run_db_id, blob_pdf_path=blob_pdf_path)
        logger.info("post_run_upload: PDF blob path saved", run_id=run_db_id, pdf=blob_pdf_path)


def _extract_pdf_text(pdf_path: Path) -> str:
    """Synchronous PDF text extraction using pdfplumber."""
    import pdfplumber
    import re as _re

    pages_text = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    raw = "\n".join(pages_text)
    # Basic cleanup matching generate_voice_digest._clean_text
    raw = _re.sub(r"\bPage\s+\d+\s+of\s+\d+\b", "", raw, flags=_re.IGNORECASE)
    raw = _re.sub(r"^\s*\d+\s*$", "", raw, flags=_re.MULTILINE)
    raw = _re.sub(r"[-_=]{4,}", " ", raw)
    raw = _re.sub(r"\n{3,}", "\n\n", raw)
    raw = _re.sub(r"[ \t]{2,}", " ", raw)
    raw = _re.sub(r"https?://\S+", "", raw)
    return raw.strip()


def _run_audiobook_formatter(raw_text: str) -> str:
    """Synchronous wrapper around the LLM audiobook formatter."""
    from agents.audiobook_formatter import format_for_audiobook
    return format_for_audiobook(raw_text)


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
