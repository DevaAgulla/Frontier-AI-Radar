"""
Database persistence helpers for the Frontier AI Radar pipeline.

Five functions — one per insertion/update point in the pipeline:

  1. start_run()               — called at pipeline start
  2. persist_intel_findings()  — called after intel agents complete
  3. update_scores()           — called after ranking
  4. save_report()             — called after PDF generation
  5. finish_run()              — called at pipeline end
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCORE_MAP = {"high": 0.9, "medium": 0.5, "low": 0.2}

def _to_float(val, default: float = 0.0) -> float:
    """Convert a score value to float. Handles numeric strings and 'high'/'medium'/'low' labels."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    if s in _SCORE_MAP:
        return _SCORE_MAP[s]
    try:
        return float(s)
    except (ValueError, TypeError):
        return default

from db.connection import get_session, init_db
from db.models import Extraction, Finding, Run, Resource, Competitor, RunAudioPreset, RunAssetCache
import structlog

logger = structlog.get_logger()


# ── Score normaliser ──────────────────────────────────────────────────────
# LLMs sometimes return qualitative labels ("high", "low", "medium") instead
# of numeric scores.  Map these to sensible floats so DB writes never crash.

_LABEL_TO_SCORE: dict[str, float] = {
    "very high": 0.9, "high": 0.75,
    "medium": 0.5,    "moderate": 0.5,
    "low": 0.25,      "very low": 0.1,
    "none": 0.0,      "n/a": 0.0,
}

def _to_float(val: Any, default: float = 0.0) -> float:
    """Convert val to float, handling string labels gracefully."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    if s in _LABEL_TO_SCORE:
        return _LABEL_TO_SCORE[s]
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


# ── 1. START RUN ─────────────────────────────────────────────────────────

def start_run(
    mode: str,
    config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Insert an Extraction and a Run at the start of the pipeline.

    Args:
        mode: 'job' (CLI / scheduled) or 'UI' (API / Streamlit)
        config: Run configuration dict (stored as JSONB in runs.config)
        user_id: DB user id of the person who triggered this run (None for cron)

    Returns:
        (extraction_id, run_db_id) — store these in RadarState for
        downstream agents.
    """
    init_db()  # no-op if already initialised

    with get_session() as session:
        extraction = Extraction(
            publication_date=datetime.now(timezone.utc),
            mode=mode,
            metadata_=json.dumps(config or {}),
        )
        session.add(extraction)
        session.flush()  # get extraction.id before commit

        run = Run(
            extraction_id=extraction.id,
            user_id=user_id,
            status="running",
            config=config or {},
        )
        session.add(run)
        session.commit()

        logger.info(
            "DB: run started",
            extraction_id=extraction.id,
            run_db_id=run.id,
            user_id=user_id,
        )
        return extraction.id, run.id


# ── 2. PERSIST INTEL FINDINGS ────────────────────────────────────────────

def persist_intel_findings(
    state: Dict[str, Any],
    extraction_id: int,
    run_db_id: int,
) -> int:
    """
    Insert findings + resources after all intel agents have completed.

    Reads the four finding lists from state, inserts one Finding row and
    one Resource row (for source_url) per finding.

    Returns:
        Number of findings persisted.
    """
    _AGENT_FINDING_MAP = {
        "research_intel":  "research_findings",
        "competitor_intel": "competitor_findings",
        "model_intel":     "provider_findings",
        "benchmark_intel": "hf_findings",
    }

    total = 0
    with get_session() as session:
        for agent_name, state_key in _AGENT_FINDING_MAP.items():
            findings = state.get(state_key, [])
            for f in findings:
                # Map agent finding dict → Finding row (individual columns)
                finding_row = Finding(
                    extraction_id=extraction_id,
                    run_id=run_db_id,
                    agent_name=agent_name,
                    title=f.get("title", "")[:500] if f.get("title") else None,
                    source_url=f.get("source_url"),
                    publisher=f.get("publisher"),
                    what_changed=f.get("what_changed"),
                    why_it_matters=f.get("why_it_matters"),
                    evidence=f.get("evidence_snippet"),
                    confidence=f.get("confidence", "MEDIUM"),
                    impact_score=_to_float(f.get("impact_score")),
                    relevance=_to_float(f.get("relevance")),
                    novelty=_to_float(f.get("novelty")),
                    credibility=_to_float(f.get("credibility")),
                    actionability=_to_float(f.get("actionability")),
                    rank=f.get("rank"),
                    topic_cluster=f.get("category"),
                    needs_verification=bool(f.get("needs_verification", False)),
                    tags=f.get("tags") or [],
                    # Overflow: id + markdown_summary → metadata JSONB
                    metadata_={
                        "id": f.get("id"),
                        "date_detected": f.get("date_detected", ""),
                        "markdown_summary": f.get("markdown_summary", ""),
                        "entities": f.get("entities", []),
                    },
                )
                session.add(finding_row)

                # Resource row (one per source URL)
                source_url = f.get("source_url", "")
                if source_url:
                    resource_row = Resource(
                        run_id=run_db_id,
                        agent_name=agent_name,
                        name=(f.get("title") or "Untitled")[:500],
                        url=source_url,
                        resource_type=f.get("category", "unknown"),
                    )
                    session.add(resource_row)

                total += 1

        session.commit()

    logger.info("DB: intel findings persisted", count=total)
    return total


# ── 3. UPDATE SCORES (after Ranking) ────────────────────────────────────

def update_scores(
    ranked_findings: List[Dict[str, Any]],
    extraction_id: int,
) -> int:
    """
    Update finding rows with impact_score and rank after the Ranking Agent.

    Matches findings by the 'id' stored in findings.metadata->>'id'.

    Returns:
        Number of rows updated.
    """
    if not ranked_findings:
        return 0

    # Build lookup: finding_id -> {impact_score, rank}
    score_map: Dict[str, Dict] = {}
    for f in ranked_findings:
        fid = f.get("id")
        if fid:
            score_map[fid] = {
                "impact_score": _to_float(f.get("impact_score")),
                "rank": int(f.get("rank") or 0),
            }

    updated = 0
    with get_session() as session:
        db_findings = (
            session.query(Finding)
            .filter(Finding.extraction_id == extraction_id)
            .all()
        )
        for db_f in db_findings:
            # The finding's original id is stored in metadata JSONB
            meta = db_f.metadata_ or {}
            fid = meta.get("id")
            if fid and fid in score_map:
                db_f.impact_score = score_map[fid]["impact_score"]
                db_f.rank = score_map[fid]["rank"]
                updated += 1

        session.commit()

    logger.info("DB: scores updated", updated=updated)
    return updated


# ── 4. SAVE REPORT (after PDF generation) ───────────────────────────────

def save_report(
    html_content: str,
    pdf_path: str,
    extraction_id: int,
    run_db_id: int,
) -> None:
    """
    Store the generated PDF directly on the Run row so it can be
    exported later via ``GET /runs/{run_id}/pdf``.

    Also stores HTML on the first finding row for UI rendering.
    """
    with get_session() as session:
        # Read PDF bytes from disk
        pdf_file = Path(pdf_path) if pdf_path else None
        pdf_bytes = None
        if pdf_file and pdf_file.exists():
            pdf_bytes = pdf_file.read_bytes()

        # Store PDF path + bytes + completed_at on the Run row
        run = session.get(Run, run_db_id)
        if run:
            run.pdf_path = pdf_path
            run.completed_at = datetime.now(timezone.utc)
            if pdf_bytes:
                run.pdf_content = pdf_bytes

        # Update extraction metadata with report info
        extraction = session.get(Extraction, extraction_id)
        if extraction:
            try:
                meta = json.loads(extraction.metadata_ or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta["pdf_path"] = pdf_path
            meta["html_length"] = len(html_content) if html_content else 0
            extraction.metadata_ = json.dumps(meta)

        # Store full HTML on the first finding row (for UI rendering)
        first_finding = (
            session.query(Finding)
            .filter(Finding.extraction_id == extraction_id)
            .first()
        )
        if first_finding:
            first_finding.html_content = html_content

        session.commit()

    logger.info("DB: report saved on Run row", run_db_id=run_db_id, pdf_path=pdf_path)


# ── 5. FINISH RUN ───────────────────────────────────────────────────────

def finish_run(
    run_db_id: int,
    status: str,
    elapsed_seconds: int,
    summary: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Update the Run row with final status and elapsed time.

    Args:
        run_db_id: The DB primary key of the Run row.
        status: 'success' | 'failure' | 'partial_failure'
        elapsed_seconds: Total wall-clock time in seconds.
        summary: Optional dict with findings_count, errors, email_status, etc.
    """
    with get_session() as session:
        run = session.get(Run, run_db_id)
        if run:
            run.status = status
            run.time_taken = elapsed_seconds
            run.completed_at = datetime.now(timezone.utc)

            # Merge summary into extraction metadata
            if run.extraction_id and summary:
                extraction = session.get(Extraction, run.extraction_id)
                if extraction:
                    try:
                        meta = json.loads(extraction.metadata_ or "{}")
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                    meta.update(summary)
                    extraction.metadata_ = json.dumps(meta)

            session.commit()

    logger.info(
        "DB: run finished",
        run_db_id=run_db_id,
        status=status,
        elapsed=elapsed_seconds,
    )


# ── 6. UPDATE BLOB PATHS (after Azure Blob upload) ──────────────────────

def update_run_blob_paths(
    run_db_id: int,
    blob_pdf_path: Optional[str] = None,
    blob_audio_path: Optional[str] = None,
) -> None:
    """Store Azure Blob paths on the Run row after upload completes."""
    with get_session() as session:
        run = session.get(Run, run_db_id)
        if not run:
            logger.warning("update_run_blob_paths: run not found", run_id=run_db_id)
            return
        if blob_pdf_path:
            run.blob_pdf_path = blob_pdf_path
        if blob_audio_path:
            run.blob_audio_path = blob_audio_path
        session.commit()

    logger.info(
        "DB: blob paths updated",
        run_db_id=run_db_id,
        pdf=blob_pdf_path,
        audio=blob_audio_path,
    )


# ── 7. AUDIO SCRIPT PATH (after LLM pre-processing step) ─────────────────

def update_audio_script_path(run_db_id: int, blob_path: str) -> None:
    """Store the blob path of the LLM-generated narration .txt file."""
    with get_session() as session:
        run = session.get(Run, run_db_id)
        if not run:
            logger.warning("update_audio_script_path: run not found", run_id=run_db_id)
            return
        run.audio_script_blob_path = blob_path
        session.commit()
    logger.info("DB: audio_script_blob_path saved", run_id=run_db_id, path=blob_path)


# ── 8. AUDIO PRESET PATH (after per-preset ElevenLabs generation) ─────────

def update_audio_preset_path(run_db_id: int, preset_id: str, blob_path: str) -> None:
    """Upsert one row in run_audio_presets for the given (run_id, preset_id).

    Creates the row if it doesn't exist; updates blob_path and marks is_ready=True.
    """
    from datetime import datetime, timezone
    with get_session() as session:
        existing = (
            session.query(RunAudioPreset)
            .filter_by(run_id=run_db_id, preset_id=preset_id)
            .first()
        )
        if existing:
            existing.blob_path    = blob_path
            existing.is_ready     = True
            existing.generated_at = datetime.now(timezone.utc)
        else:
            session.add(RunAudioPreset(
                run_id       = run_db_id,
                preset_id    = preset_id,
                blob_path    = blob_path,
                is_ready     = True,
                generated_at = datetime.now(timezone.utc),
            ))
        session.commit()
    logger.info("DB: run_audio_presets upserted", run_id=run_db_id, preset=preset_id)


def update_audio_preset_sas(run_db_id: int, preset_id: str, sas_entry: dict) -> None:
    """Upsert one row in run_asset_cache for audio/{preset_id}.

    sas_entry must contain {"url": "...", "expires_at": "ISO string"}.
    """
    from datetime import datetime, timezone
    expires_at_str: str = sas_entry.get("expires_at", "")
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
    except Exception:
        expires_at = datetime.now(timezone.utc)

    with get_session() as session:
        existing = (
            session.query(RunAssetCache)
            .filter_by(run_id=run_db_id, asset_type="audio", preset_id=preset_id)
            .first()
        )
        if existing:
            existing.sas_url    = sas_entry["url"]
            existing.expires_at = expires_at
        else:
            session.add(RunAssetCache(
                run_id     = run_db_id,
                asset_type = "audio",
                preset_id  = preset_id,
                sas_url    = sas_entry["url"],
                expires_at = expires_at,
            ))
        session.commit()
    logger.info("DB: run_asset_cache upserted", run_id=run_db_id, preset=preset_id)


def update_pdf_sas(run_db_id: int, sas_entry: dict) -> None:
    """Upsert the PDF SAS URL in run_asset_cache (asset_type='pdf', preset_id=None)."""
    from datetime import datetime, timezone
    expires_at_str: str = sas_entry.get("expires_at", "")
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
    except Exception:
        expires_at = datetime.now(timezone.utc)

    with get_session() as session:
        existing = (
            session.query(RunAssetCache)
            .filter_by(run_id=run_db_id, asset_type="pdf", preset_id=None)
            .first()
        )
        if existing:
            existing.sas_url    = sas_entry["url"]
            existing.expires_at = expires_at
        else:
            session.add(RunAssetCache(
                run_id     = run_db_id,
                asset_type = "pdf",
                preset_id  = None,
                sas_url    = sas_entry["url"],
                expires_at = expires_at,
            ))
        session.commit()
    logger.info("DB: run_asset_cache PDF upserted", run_id=run_db_id)


# ── COMPETITOR SOURCE MANAGEMENT ─────────────────────────────────────────

def seed_default_competitors() -> None:
    """
    Insert the pre-defined competitor sources if the table is empty.

    Idempotent — safe to call on every startup.
    Note: setup_db.py already seeds these on first deploy.
    """
    with get_session() as session:
        count = session.query(Competitor).count()
        if count > 0:
            logger.info("DB: competitors table already seeded", count=count)
            return

        _DEFAULT_COMPETITORS = [
            {"name": "OpenAI Blog",       "url": "https://openai.com/blog/rss.xml",      "source_type": "rss",     "selector": None},
            {"name": "Anthropic News",    "url": "https://www.anthropic.com/index.xml",  "source_type": "rss",     "selector": None},
        ]
        for src in _DEFAULT_COMPETITORS:
            session.add(Competitor(
                name=src["name"],
                url=src["url"],
                source_type=src["source_type"],
                selector=src.get("selector"),
                is_default=True,
                is_active=True,
                added_by=None,
            ))
        session.commit()
        logger.info("DB: seeded default competitors", count=len(_DEFAULT_COMPETITORS))


def get_competitors(active_only: bool = True) -> List[Dict[str, Any]]:
    """
    Return competitor sources from the database.

    Each dict has: url, type, selector (matching the format
    the competitor_intel agent already expects).
    """
    with get_session() as session:
        query = session.query(Competitor)
        if active_only:
            query = query.filter(Competitor.is_active == True)  # noqa: E712
        rows = query.order_by(Competitor.id).all()

        return [
            {
                "type": row.source_type,
                "url": row.url,
                "selector": row.selector,
            }
            for row in rows
        ]
