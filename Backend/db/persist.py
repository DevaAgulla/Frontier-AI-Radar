"""
Database persistence helpers for the Frontier AI Radar pipeline.

Five functions — one per insertion/update point in the pipeline:

  1. start_run()              — called at pipeline start
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

from db.connection import get_session, init_db
from db.models import Extraction, Finding, Run, Resource, Competitor
import structlog

logger = structlog.get_logger()


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
        config: Run configuration dict (stored as JSON metadata)
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
        "research_intel":   "research_findings",
        "competitor_intel":  "competitor_findings",
        "model_intel":       "provider_findings",
        "benchmark_intel":   "hf_findings",
    }

    total = 0
    with get_session() as session:
        for agent_name, state_key in _AGENT_FINDING_MAP.items():
            findings = state.get(state_key, [])
            for f in findings:
                # ── Finding row
                finding_row = Finding(
                    extraction_id=extraction_id,
                    agent_name=agent_name,
                    metadata_=json.dumps({
                        "id": f.get("id"),
                        "title": f.get("title"),
                        "source_url": f.get("source_url", ""),
                        "publisher": f.get("publisher", ""),
                        "date_detected": f.get("date_detected", ""),
                        "what_changed": f.get("what_changed"),
                        "why_it_matters": f.get("why_it_matters"),
                        "confidence": f.get("confidence"),
                        "actionability": f.get("actionability"),
                        "novelty": f.get("novelty"),
                        "credibility": f.get("credibility"),
                        "relevance": f.get("relevance"),
                        "impact_score": f.get("impact_score", 0.0),
                        "entities": f.get("entities", []),
                        "tags": f.get("tags", []),
                        "category": f.get("category"),
                        "needs_verification": f.get("needs_verification", False),
                        "evidence_snippet": f.get("evidence_snippet", ""),
                        "markdown_summary": f.get("markdown_summary", ""),
                    }),
                )
                session.add(finding_row)

                # ── Resource row (one per source URL)
                source_url = f.get("source_url", "")
                if source_url:
                    resource_row = Resource(
                        run_id=run_db_id,
                        agent_name=agent_name,
                        name=f.get("title", "Untitled")[:500],
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
    Update finding metadata with impact_score and rank after the
    Ranking Agent has scored them.

    Matches findings by their JSON 'id' field.

    Returns:
        Number of rows updated.
    """
    if not ranked_findings:
        return 0

    # Build a lookup: finding_id -> (impact_score, rank)
    score_map = {}
    for f in ranked_findings:
        fid = f.get("id")
        if fid:
            score_map[fid] = {
                "impact_score": f.get("impact_score", 0.0),
                "rank": f.get("rank", 0),
            }

    updated = 0
    with get_session() as session:
        db_findings = (
            session.query(Finding)
            .filter(Finding.extraction_id == extraction_id)
            .all()
        )
        for db_f in db_findings:
            try:
                meta = json.loads(db_f.metadata_ or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}

            fid = meta.get("id")
            if fid and fid in score_map:
                meta["impact_score"] = score_map[fid]["impact_score"]
                meta["rank"] = score_map[fid]["rank"]
                db_f.metadata_ = json.dumps(meta)
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

    Also updates extraction metadata with report info and stores
    the full HTML on the first finding row (for UI rendering).
    """
    with get_session() as session:
        # ── Read PDF bytes from disk
        pdf_file = Path(pdf_path) if pdf_path else None
        pdf_bytes = None
        if pdf_file and pdf_file.exists():
            pdf_bytes = pdf_file.read_bytes()

        # ── Store PDF path + bytes on the Run row
        run = session.query(Run).get(run_db_id)
        if run:
            run.pdf_path = pdf_path
            if pdf_bytes:
                run.pdf_content = pdf_bytes

        # ── Update extraction metadata with report info
        extraction = session.query(Extraction).get(extraction_id)
        if extraction:
            try:
                meta = json.loads(extraction.metadata_ or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta["pdf_path"] = pdf_path
            meta["html_length"] = len(html_content) if html_content else 0
            extraction.metadata_ = json.dumps(meta)

        # ── Store full HTML on the first finding row (for UI rendering)
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
        run = session.query(Run).get(run_db_id)
        if run:
            run.status = status
            run.time_taken = elapsed_seconds

            # Also update extraction metadata with summary
            if run.extraction_id and summary:
                extraction = session.query(Extraction).get(run.extraction_id)
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


# ── COMPETITOR SOURCE MANAGEMENT ─────────────────────────────────────────

# Pre-defined competitor sources (seeded on first deploy)
_DEFAULT_COMPETITORS = [
    {
        "name": "OpenAI Blog",
        "url": "https://openai.com/blog/rss.xml",
        "source_type": "rss",
        "selector": None,
    },
    {
        "name": "Anthropic News",
        "url": "https://www.anthropic.com/index.xml",
        "source_type": "rss",
        "selector": None,
    },
    {
        "name": "Google AI Updates",
        "url": "https://ai.google.dev/updates",
        "source_type": "webpage",
        "selector": ".update-item",
    },
]


def seed_default_competitors() -> None:
    """
    Insert the pre-defined competitor sources if the table is empty.

    Idempotent — safe to call on every startup.
    """
    with get_session() as session:
        count = session.query(Competitor).count()
        if count > 0:
            logger.info("DB: competitors table already seeded", count=count)
            return

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

    Args:
        active_only: If True (default), return only rows where is_active=True.
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
