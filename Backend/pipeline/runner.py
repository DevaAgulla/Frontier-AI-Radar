"""Pipeline runner — core orchestration for executing radar runs.

Called by api/main.py (deployment) or directly for testing.
DB persistence is wired in: start_run → pipeline → finish_run.
"""

import logging
import sys
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

from pipeline.graph import create_radar_graph
from pipeline.state import RadarState
from config.settings import settings
from db.persist import start_run, finish_run
import structlog

logger = structlog.get_logger()

VALID_AGENTS = {"research", "competitor", "model", "benchmark"}


def _configure_logging(debug: bool = False) -> None:
    """Configure structlog + stdlib logging level."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
        force=True,
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def create_initial_state(
    run_mode: str = "full",
    since_days: int = 1,
    config: Optional[Dict[str, Any]] = None,
    extraction_db_id: int = 0,
    run_db_id: int = 0,
    email_recipients: Optional[List[str]] = None,
    custom_urls: Optional[List[str]] = None,
    url_mode: str = "default",
) -> RadarState:
    """Create initial state for a radar run."""
    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    since_timestamp = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

    return {
        "run_id": run_id,
        "run_mode": run_mode,
        "selected_agents": [],
        "mission_goal": "",
        "strategy_plan": {},
        "since_timestamp": since_timestamp,
        "config": config or {},
        # Custom URL support
        "custom_urls": custom_urls or [],
        "url_mode": url_mode,
        # DB tracking
        "extraction_db_id": extraction_db_id,
        "run_db_id": run_db_id,
        # Discovery outputs
        "discovered_sources": [],
        "trend_signals": [],
        # Intel findings
        "competitor_findings": [],
        "provider_findings": [],
        "research_findings": [],
        "hf_findings": [],
        # Verification
        "verification_tasks": [],
        "verification_verdicts": [],
        # Post-processing
        "merged_findings": [],
        "ranked_findings": [],
        # Email recipients (resolved by API before pipeline starts)
        "email_recipients": email_recipients or [],
        # Final outputs
        "digest_json": {},
        "digest_markdown": "",
        "digest_needs_rewrite": False,
        "pdf_path": "",
        "email_status": "",
        "errors": [],
        "agent_iterations": {},
    }


async def run_radar(
    mode: str = "full",
    since_days: int = 1,
    config: Optional[Dict[str, Any]] = None,
    trigger: str = "job",
    user_id: Optional[int] = None,
    email_recipients: Optional[List[str]] = None,
    custom_urls: Optional[List[str]] = None,
    url_mode: str = "default",
) -> RadarState:
    """
    Run the Frontier AI Radar pipeline.

    Args:
        mode: Run mode — "full" runs all 4 agents, or specify one or more
              agent names comma-separated: "research", "competitor", "model",
              "benchmark", "research,competitor", etc.
        since_days: How many days back to search
        config: Optional configuration overrides
        trigger: 'job' (CLI / scheduled) or 'UI' (API / Streamlit)
        user_id: DB user id of the person who triggered this run (None for cron)
        email_recipients: List of email addresses to send digest to
        custom_urls: User-provided URLs for targeted crawling
        url_mode: "default" | "append" | "custom"

    Returns:
        Final state after pipeline execution
    """
    logger.info("Starting radar run", mode=mode, since_days=since_days,
                user_id=user_id, url_mode=url_mode,
                custom_urls_count=len(custom_urls or []))

    initial_state = prepare_radar_run(
        mode=mode,
        since_days=since_days,
        config=config,
        trigger=trigger,
        user_id=user_id,
        email_recipients=email_recipients,
        custom_urls=custom_urls,
        url_mode=url_mode,
    )
    return await execute_prepared_radar(initial_state)


def prepare_radar_run(
    mode: str = "full",
    since_days: int = 1,
    config: Optional[Dict[str, Any]] = None,
    trigger: str = "job",
    user_id: Optional[int] = None,
    email_recipients: Optional[List[str]] = None,
    custom_urls: Optional[List[str]] = None,
    url_mode: str = "default",
) -> RadarState:
    """
    Prepare a run by creating DB records and initial state, but DO NOT execute graph.
    Useful for fire-and-forget API flows.
    """
    extraction_db_id, run_db_id = start_run(
        mode=trigger, config=config, user_id=user_id,
    )
    return create_initial_state(
        run_mode=mode,
        since_days=since_days,
        config=config,
        extraction_db_id=extraction_db_id,
        run_db_id=run_db_id,
        email_recipients=email_recipients,
        custom_urls=custom_urls,
        url_mode=url_mode,
    )


async def execute_prepared_radar(initial_state: RadarState) -> RadarState:
    """Execute a previously prepared run state and update final DB status."""
    graph = create_radar_graph()
    t0 = time.time()
    run_db_id = initial_state.get("run_db_id", 0)

    try:
        final_state = await graph.ainvoke(initial_state)
        elapsed = int(time.time() - t0)

        # ── DB: mark run as success ──────────────────────────────────
        finish_run(
            run_db_id=run_db_id,
            status="success",
            elapsed_seconds=elapsed,
            summary={
                "findings_count": len(final_state.get("ranked_findings", [])),
                "errors_count": len(final_state.get("errors", [])),
                "email_status": final_state.get("email_status", ""),
                "pdf_path": final_state.get("pdf_path", ""),
            },
        )

        logger.info(
            "Radar run completed",
            run_id=final_state.get("run_id"),
            findings_count=len(final_state.get("ranked_findings", [])),
            errors_count=len(final_state.get("errors", [])),
            elapsed_seconds=elapsed,
        )
        return final_state

    except Exception as e:
        elapsed = int(time.time() - t0)

        # ── DB: mark run as failure ──────────────────────────────────
        finish_run(
            run_db_id=run_db_id,
            status="failure",
            elapsed_seconds=elapsed,
            summary={"error": str(e)},
        )

        logger.exception("Radar run failed", error=str(e))
        raise
