"""Frontier AI Radar — Simple FastAPI entry point."""

import sys
import asyncio

# psycopg v3 (used by LangGraph checkpointer) is incompatible with Windows
# ProactorEventLoop.  Force SelectorEventLoop on Windows before anything else loads.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import re
import json
import hashlib
import secrets
import uvicorn
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, field_validator
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta, date
from langchain_core.messages import HumanMessage

try:
    import jwt as pyjwt  # PyJWT
except ImportError:
    pyjwt = None  # type: ignore

from pipeline.runner import (
    run_radar,
    prepare_radar_run,
    execute_prepared_radar,
    create_chat_initial_state,
    VALID_AGENTS,
)
# APScheduler replaced by Celery beat — import kept for backwards-compat fallback
try:
    from pipeline.scheduler import start_scheduler, stop_scheduler
    _apscheduler_available = True
except ImportError:
    _apscheduler_available = False
    def start_scheduler(): pass
    def stop_scheduler():  pass
from db.connection import init_db, get_session
from db.models import Run, Extraction, Finding, Resource, User, Competitor
from config.settings import settings
from agents.base_agent import _build_llm, parse_json_object

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB, run schema migrations.

    Scheduling is handled by Celery beat (external process).
    APScheduler is started only when Celery is not available (dev / single-server).
    """
    init_db()
    from db.chat import ensure_chat_schema
    ensure_chat_schema()

    # Start APScheduler only when Celery beat is not running this deployment
    celery_beat_running = False
    try:
        from workers.celery_app import celery_app as _ca
        # Quick broker ping — if it succeeds, beat handles scheduling
        _ca.control.ping(timeout=1)
        celery_beat_running = True
    except Exception:
        pass

    if not celery_beat_running and _apscheduler_available:
        start_scheduler()

    yield

    if not celery_beat_running and _apscheduler_available:
        stop_scheduler()


app = FastAPI(title="Frontier AI Radar API", lifespan=lifespan)

# ── CORS — allow all origins (safe for hackathon; tighten for production) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_background_runs: Dict[int, asyncio.Task] = {}

AGENT_ORDER = ["research", "competitor", "model", "benchmark"]
AGENT_LABELS = {
    "research": "Research",
    "competitor": "Competitor",
    "model": "Foundation Model",
    "benchmark": "Benchmark",
}


def _normalize_run_status(status: Optional[str]) -> str:
    if status in ("success", "completed"):
        return "completed"
    if status in ("failure", "failed"):
        return "failed"
    if status == "running":
        return "running"
    return "pending"


def _mode_to_agents(mode: str) -> List[str]:
    if mode == "full":
        return AGENT_ORDER
    parts = [p.strip() for p in mode.split(",") if p.strip()]
    return [p for p in AGENT_ORDER if p in parts]


def _finished_at_iso(run: Run) -> Optional[str]:
    if not run.started_at or not run.time_taken:
        return None
    return (run.started_at + timedelta(seconds=run.time_taken)).isoformat()


def _serialize_agent_statuses(selected_agents: List[str], findings_by_agent: Dict[str, int], normalized_status: str) -> List[Dict[str, Any]]:
    statuses: List[Dict[str, Any]] = []
    for agent in AGENT_ORDER:
        if agent not in selected_agents:
            statuses.append({
                "agent": agent,
                "label": AGENT_LABELS.get(agent, agent.title()),
                "status": "skipped",
                "findings_count": 0,
            })
            continue

        findings_count = findings_by_agent.get(agent, 0)
        if normalized_status == "running":
            status = "running"
        elif normalized_status == "failed" and findings_count == 0:
            status = "failed"
        else:
            status = "completed"

        statuses.append({
            "agent": agent,
            "label": AGENT_LABELS.get(agent, agent.title()),
            "status": status,
            "findings_count": findings_count,
        })
    return statuses


def _agent_db_to_ui(agent_name: str) -> str:
    name = agent_name.replace("_intel", "")
    if name == "provider":
        return "model"
    if name == "hf":
        return "benchmark"
    return name


def _parse_iso_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date '{raw}'. Use YYYY-MM-DD.") from exc


def _find_run_by_date_user_mode(session, target_date: date, user_id: Optional[int], mode: Optional[str]) -> Optional[Run]:
    runs = session.query(Run).order_by(Run.started_at.desc()).all()
    for run in runs:
        if not run.started_at:
            continue
        if run.started_at.date() != target_date:
            continue
        if user_id is not None and run.user_id != user_id:
            continue
        if _normalize_run_status(run.status) not in ("completed", "running"):
            continue

        extraction = (
            session.query(Extraction).filter(Extraction.id == run.extraction_id).first()
            if run.extraction_id else None
        )
        extraction_meta = _parse_json(extraction.metadata_) if extraction else {}
        run_mode = extraction_meta.get("requested_mode", "full")
        if mode and run_mode != mode:
            continue
        return run
    return None


def _collect_run_findings(session, run: Run) -> List[Dict[str, Any]]:
    if not run.extraction_id:
        return []
    rows = session.query(Finding).filter(Finding.extraction_id == run.extraction_id).all()
    out: List[Dict[str, Any]] = []
    for row in rows:
        meta = _parse_json(row.metadata_)
        out.append({
            "id": str(meta.get("id") or row.id),
            "title": meta.get("title", "Untitled"),
            "impact_score": float(meta.get("impact_score", 0) or 0),
            "agent": _agent_db_to_ui(row.agent_name),
            "source_url": meta.get("source_url", ""),
            "category": meta.get("category", "unknown"),
            "summary": meta.get("what_changed", ""),
        })
    return out


def _compute_compare_payload(
    run_a: Run,
    run_b: Run,
    findings_a: List[Dict[str, Any]],
    findings_b: List[Dict[str, Any]],
) -> Dict[str, Any]:
    map_a = {f["title"].strip().lower(): f for f in findings_a if f.get("title")}
    map_b = {f["title"].strip().lower(): f for f in findings_b if f.get("title")}

    keys_a = set(map_a.keys())
    keys_b = set(map_b.keys())
    added_keys = sorted(keys_b - keys_a)
    removed_keys = sorted(keys_a - keys_b)
    common_keys = sorted(keys_a & keys_b)

    added = sorted([map_b[k] for k in added_keys], key=lambda x: x.get("impact_score", 0), reverse=True)
    removed = sorted([map_a[k] for k in removed_keys], key=lambda x: x.get("impact_score", 0), reverse=True)

    changed_impact = []
    for k in common_keys:
        fa = map_a[k]
        fb = map_b[k]
        delta = float((fb.get("impact_score", 0) or 0) - (fa.get("impact_score", 0) or 0))
        if abs(delta) >= 0.1:
            changed_impact.append({
                "title": fb.get("title"),
                "agent": fb.get("agent"),
                "impact_before": fa.get("impact_score", 0),
                "impact_after": fb.get("impact_score", 0),
                "delta": delta,
            })
    changed_impact.sort(key=lambda x: abs(x["delta"]), reverse=True)

    def _counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
        c = {a: 0 for a in AGENT_ORDER}
        for r in rows:
            a = r.get("agent")
            if a in c:
                c[a] += 1
        return c

    counts_a = _counts(findings_a)
    counts_b = _counts(findings_b)
    agent_deltas = []
    for a in AGENT_ORDER:
        agent_deltas.append({
            "agent": a,
            "label": AGENT_LABELS.get(a, a.title()),
            "before": counts_a[a],
            "after": counts_b[a],
            "delta": counts_b[a] - counts_a[a],
        })

    major_highlights = []
    if added:
        major_highlights.append(f"{len(added)} new high-signal finding(s) in the newer snapshot.")
    if removed:
        major_highlights.append(f"{len(removed)} finding(s) no longer present vs older snapshot.")
    if changed_impact:
        top_change = changed_impact[0]
        major_highlights.append(
            f"Largest impact shift: '{top_change['title']}' ({top_change['delta']:+.2f})."
        )

    return {
        "status": "completed",
        "baseline_run_id": run_a.id,
        "candidate_run_id": run_b.id,
        "summary": {
            "baseline_findings": len(findings_a),
            "candidate_findings": len(findings_b),
            "added_count": len(added),
            "removed_count": len(removed),
            "impact_changes_count": len(changed_impact),
            "major_highlights": major_highlights[:5],
        },
        "agent_deltas": agent_deltas,
        "added_findings": added[:15],
        "removed_findings": removed[:15],
        "impact_changed_findings": changed_impact[:15],
    }


def _section_label_for_agent(agent: str) -> str:
    mapping = {
        "competitor": "Competitor",
        "model": "Foundational Models",
        "research": "Research Papers",
        "benchmark": "Hugging Face Benchmarks",
    }
    return mapping.get(agent, agent.title())


def _build_section_context(findings: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "Competitor": [],
        "Foundational Models": [],
        "Research Papers": [],
        "Hugging Face Benchmarks": [],
    }
    for f in findings:
        label = _section_label_for_agent(str(f.get("agent", "")))
        if label in grouped:
            grouped[label].append(f)

    for key in grouped:
        grouped[key] = sorted(grouped[key], key=lambda x: x.get("impact_score", 0), reverse=True)[:8]
    return grouped


async def _generate_llm_section_comparison(
    date_a: str,
    date_b: str,
    findings_a: List[Dict[str, Any]],
    findings_b: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    grouped_a = _build_section_context(findings_a)
    grouped_b = _build_section_context(findings_b)

    def _compact_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for r in rows[:6]:
            out.append({
                "title": r.get("title", "Untitled"),
                "impact": round(float(r.get("impact_score", 0) or 0), 2),
                "category": r.get("category", "unknown"),
                "summary": (r.get("summary", "") or "")[:180],
            })
        return out

    context_payload = {
        "date_a": date_a,
        "date_b": date_b,
        "sections": {
            "Competitor": {"date_a_items": _compact_rows(grouped_a["Competitor"]), "date_b_items": _compact_rows(grouped_b["Competitor"])},
            "Foundational Models": {"date_a_items": _compact_rows(grouped_a["Foundational Models"]), "date_b_items": _compact_rows(grouped_b["Foundational Models"])},
            "Research Papers": {"date_a_items": _compact_rows(grouped_a["Research Papers"]), "date_b_items": _compact_rows(grouped_b["Research Papers"])},
            "Hugging Face Benchmarks": {"date_a_items": _compact_rows(grouped_a["Hugging Face Benchmarks"]), "date_b_items": _compact_rows(grouped_b["Hugging Face Benchmarks"])},
        },
    }

    prompt = (
        "You are an AI analyst. Compare two daily AI intelligence reports section-wise.\n"
        "Generate concise, executive-friendly differences.\n\n"
        "Return ONLY valid JSON with this exact shape:\n"
        "{\n"
        "  \"sections\": [\n"
        "    {\n"
        "      \"section\": \"Competitor|Foundational Models|Research Papers|Hugging Face Benchmarks\",\n"
        f"      \"date_a_summary\": \"short summary for {date_a}\",\n"
        f"      \"date_b_summary\": \"short summary for {date_b}\",\n"
        "      \"compared_result\": \"clear difference statement\",\n"
        "      \"major_updates\": [\"bullet 1\", \"bullet 2\"]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Always include all 4 sections in this order: Competitor, Foundational Models, Research Papers, Hugging Face Benchmarks.\n"
        "- Keep each field under 2 sentences.\n"
        "- If no change, explicitly say 'No major change'.\n"
        "- Focus on meaningful changes, not wording differences.\n\n"
        f"Input JSON:\n{json.dumps(context_payload, ensure_ascii=False)}"
    )

    try:
        llm = _build_llm()
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        content = getattr(result, "content", "")
        if isinstance(content, list):
            content = "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
        parsed = parse_json_object(str(content))
        sections = parsed.get("sections", []) if isinstance(parsed, dict) else []
        if isinstance(sections, list) and sections:
            normalized = []
            for section_name in ["Competitor", "Foundational Models", "Research Papers", "Hugging Face Benchmarks"]:
                hit = next((s for s in sections if str(s.get("section", "")).strip().lower() == section_name.lower()), None)
                if hit:
                    normalized.append({
                        "section": section_name,
                        "date_a_summary": str(hit.get("date_a_summary", "No major change")),
                        "date_b_summary": str(hit.get("date_b_summary", "No major change")),
                        "compared_result": str(hit.get("compared_result", "No major change")),
                        "major_updates": hit.get("major_updates", []) if isinstance(hit.get("major_updates", []), list) else [],
                    })
                else:
                    normalized.append({
                        "section": section_name,
                        "date_a_summary": "No major change",
                        "date_b_summary": "No major change",
                        "compared_result": "No major change",
                        "major_updates": [],
                    })
            return normalized
    except Exception:
        pass

    # Deterministic fallback (if LLM parse fails)
    fallback = []
    for section_name in ["Competitor", "Foundational Models", "Research Papers", "Hugging Face Benchmarks"]:
        a_rows = grouped_a[section_name]
        b_rows = grouped_b[section_name]
        a_titles = {r.get("title", "") for r in a_rows}
        b_titles = {r.get("title", "") for r in b_rows}
        added = [t for t in b_titles if t and t not in a_titles]
        removed = [t for t in a_titles if t and t not in b_titles]
        compared = "No major change"
        if added or removed:
            compared = f"Added {len(added)} and removed {len(removed)} items."
        fallback.append({
            "section": section_name,
            "date_a_summary": f"{len(a_rows)} key items identified.",
            "date_b_summary": f"{len(b_rows)} key items identified.",
            "compared_result": compared,
            "major_updates": ([f"New: {added[0]}"] if added else []) + ([f"Removed: {removed[0]}"] if removed else []),
        })
    return fallback


# ── Request / Response Models ────────────────────────────────────────────

class RunRequest(BaseModel):
    mode: str = "full"
    since_days: int = 1
    user_id: Optional[int] = None          # subscribed user id (UI trigger)
    email: Optional[str] = None            # ad-hoc email (UI trigger, no subscription needed)
    extra_recipients: List[str] = []       # additional emails to CC alongside user_id/email
    urls: List[str] = []                   # custom URLs for targeted crawling
    url_mode: str = "default"              # "default" | "append" | "custom"

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v == "full":
            return v
        parts = [p.strip() for p in v.split(",")]
        bad = [p for p in parts if p not in VALID_AGENTS]
        if bad:
            raise ValueError(f"Unknown agent(s): {bad}. Valid: {sorted(VALID_AGENTS)} or 'full'.")
        return v

    @field_validator("url_mode")
    @classmethod
    def check_url_mode(cls, v: str) -> str:
        if v not in ("default", "append", "custom"):
            raise ValueError("url_mode must be 'default', 'append', or 'custom'.")
        return v


class RunResponse(BaseModel):
    run_db_id: Optional[int] = None
    run_id: str
    status: str
    mode: str
    started_at: str
    finished_at: Optional[str] = None
    findings_count: int = 0
    errors: List[Dict[str, Any]] = []
    email_status: str = ""
    pdf_path: str = ""


def _resolve_recipients_and_user(req: RunRequest) -> tuple[List[str], Optional[int], str]:
    """Resolve recipient emails and user id from request.

    Priority:
      1. If user_id provided → send to that specific user
      2. If email provided   → send to that email (auto-register)
      3. Otherwise           → send to ALL registered users + .env recipients (deduped)

    In all cases, extra_recipients are merged in (deduped).
    """
    email_recipients: List[str] = []
    resolved_user_id: Optional[int] = req.user_id
    trigger = "UI" if (req.user_id or req.email) else "job"

    if req.user_id:
        with get_session() as session:
            user = session.query(User).filter(User.id == req.user_id).first()
            if not user:
                raise HTTPException(
                    status_code=404,
                    detail=f"User {req.user_id} not found. Subscribe first via POST /api/v1/users.",
                )
            email_recipients = [user.email]
    elif req.email:
        with get_session() as session:
            user = session.query(User).filter(User.email == req.email).first()
            if not user:
                name = req.email.split("@")[0].replace(".", " ").title()
                user = User(name=name, email=req.email)
                session.add(user)
                session.commit()
                session.refresh(user)
            resolved_user_id = user.id
            email_recipients = [user.email]
    else:
        # ── Collect ALL registered users from DB ──────────────────
        with get_session() as session:
            users = session.query(User).all()
            db_emails = [u.email.strip().lower() for u in users if u.email]

        # ── Also include .env EMAIL_RECIPIENTS (belt-and-suspenders) ──
        env_emails = [
            e.strip().lower()
            for e in settings.email_recipients.split(",")
            if e.strip()
        ]

        # Merge & deduplicate (preserve order, DB first)
        seen: set[str] = set()
        all_emails: List[str] = []
        for email in db_emails + env_emails:
            if email and email not in seen:
                seen.add(email)
                all_emails.append(email)
        email_recipients = all_emails

    # ── Merge extra_recipients (deduped, preserve order) ──────────
    if req.extra_recipients:
        seen_set: set[str] = {e.strip().lower() for e in email_recipients}
        for extra in req.extra_recipients:
            normalized = extra.strip().lower()
            if normalized and "@" in normalized and normalized not in seen_set:
                seen_set.add(normalized)
                email_recipients.append(normalized)

    logger.info(
        "Recipients resolved",
        count=len(email_recipients),
        trigger=trigger,
        emails=email_recipients,
    )
    return email_recipients, resolved_user_id, trigger


# ── Single POST endpoint ────────────────────────────────────────────────

@app.post("/api/v1/pipeline/run", response_model=RunResponse)
async def run(req: RunRequest):
    """
    Run the pipeline. Blocks until done, then returns the full result.

    Body examples:
      {"mode": "full"}                                              — default sources only
      {"mode": "research", "user_id": 1}                           — subscribed user, defaults
      {"mode": "competitor", "urls": ["https://mistral.ai/blog"],
       "url_mode": "append"}                                       — defaults + extra URLs
      {"mode": "competitor", "urls": ["https://x.ai/blog"],
       "url_mode": "custom"}                                       — ONLY the given URLs
      {"mode": "research,competitor", "urls": ["https://arxiv.org/abs/2403.12345"],
       "url_mode": "custom", "email": "a@b.com"}                  — custom URLs, ad-hoc user

    mode: "full" | "research" | "competitor" | "model" | "benchmark"
          or comma-separated like "research,competitor"
    url_mode: "default" | "append" | "custom"
    """
    # ── Validate url_mode + urls combo ─────────────────────────────────
    if req.url_mode == "custom" and not req.urls:
        raise HTTPException(
            status_code=400,
            detail="url_mode is 'custom' but no URLs provided. Pass at least one URL in the 'urls' field.",
        )

    started_at = datetime.now(timezone.utc).isoformat()

    email_recipients, resolved_user_id, trigger = _resolve_recipients_and_user(req)

    try:
        selected_agents = _mode_to_agents(req.mode)
        run_config = {
            "requested_mode": req.mode,
            "requested_agents": selected_agents,
            "url_mode": req.url_mode,
            "custom_urls": req.urls,
            "email_recipients": email_recipients,
        }
        state = await run_radar(
            mode=req.mode,
            since_days=req.since_days,
            config=run_config,
            trigger=trigger,
            user_id=resolved_user_id,
            email_recipients=email_recipients,
            custom_urls=req.urls,
            url_mode=req.url_mode,
        )

        return RunResponse(
            run_db_id=state.get("run_db_id"),
            run_id=state.get("run_id", ""),
            status="completed",
            mode=req.mode,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
            findings_count=len(state.get("ranked_findings", [])),
            errors=state.get("errors", []),
            email_status=state.get("email_status", ""),
            pdf_path=state.get("pdf_path", ""),
        )
    except Exception as e:
        return RunResponse(
            run_db_id=None,
            run_id="",
            status="failed",
            mode=req.mode,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
            errors=[{"error": str(e)}],
        )


@app.post("/api/v1/pipeline/run/async", response_model=RunResponse)
async def run_async(req: RunRequest):
    """
    Fire-and-forget run trigger.

    Enqueues the pipeline as a Celery task (digest → audio → blob chain).
    Returns immediately with run_db_id so the frontend can poll for status.
    Falls back to in-process asyncio.create_task if Celery is unavailable.
    """
    if req.url_mode == "custom" and not req.urls:
        raise HTTPException(
            status_code=400,
            detail="url_mode is 'custom' but no URLs provided.",
        )

    started_at = datetime.now(timezone.utc).isoformat()
    email_recipients, resolved_user_id, trigger = _resolve_recipients_and_user(req)
    selected_agents = _mode_to_agents(req.mode)
    run_config = {
        "requested_mode": req.mode,
        "requested_agents": selected_agents,
        "url_mode": req.url_mode,
        "custom_urls": req.urls,
        "email_recipients": email_recipients,
    }

    # Create DB rows first so the frontend has a run_id to poll immediately
    from pipeline.runner import prepare_radar_run
    initial_state = prepare_radar_run(
        mode=req.mode,
        since_days=req.since_days,
        config=run_config,
        trigger=trigger,
        user_id=resolved_user_id,
        email_recipients=email_recipients,
        custom_urls=req.urls,
        url_mode=req.url_mode,
    )
    run_db_id = initial_state.get("run_db_id")
    run_id    = initial_state.get("run_id", "")

    # ── Enqueue via Celery if available, otherwise fall back to asyncio ──
    celery_available = False
    try:
        from workers.tasks import run_digest_pipeline, generate_audio_task, upload_blob_task
        from cache.redis_client import invalidate_digest_cache
        if run_db_id:
            invalidate_digest_cache(run_db_id)
        (
            run_digest_pipeline.s(
                run_db_id=run_db_id,
                mode=req.mode,
                since_days=req.since_days,
                email_recipients=email_recipients,
                custom_urls=req.urls or [],
                url_mode=req.url_mode,
            )
            | generate_audio_task.s()
            | upload_blob_task.s()
        ).apply_async()
        celery_available = True
        logger.info("run_enqueued_celery", run_db_id=run_db_id)
    except Exception as _ce:
        logger.warning("celery_unavailable_fallback_asyncio", error=str(_ce))

    if not celery_available:
        # Fallback: run in-process (single-server / dev mode)
        from pipeline.runner import execute_prepared_radar

        async def _runner_task(state):
            try:
                await execute_prepared_radar(state)
            finally:
                _background_runs.pop(run_db_id, None)

        task = asyncio.create_task(_runner_task(initial_state))
        if run_db_id:
            _background_runs[run_db_id] = task

    return RunResponse(
        run_db_id=run_db_id,
        run_id=run_id,
        status="queued" if celery_available else "running",
        mode=req.mode,
        started_at=started_at,
        finished_at=None,
        findings_count=0,
        errors=[],
        email_status="queued",
        pdf_path="",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "valid_agents": sorted(VALID_AGENTS)}


# ── User subscription ────────────────────────────────────────────────────

class SubscribeRequest(BaseModel):
    name: str
    email: str


class SchedulerSubscribeRequest(BaseModel):
    email: str
    name: Optional[str] = None


class CompareRequest(BaseModel):
    date_a: str
    date_b: str
    run_a_id: Optional[int] = None
    run_b_id: Optional[int] = None


@app.post("/api/v1/users")
async def subscribe(req: SubscribeRequest):
    """
    Subscribe a user to receive digest emails.

    Body: {"name": "Ramesh", "email": "ramesh@example.com"}
    Returns the created user record.  If the email already exists, returns the existing record.
    """
    with get_session() as session:
        existing = session.query(User).filter(User.email == req.email).first()
        if existing:
            return {
                "id": existing.id,
                "name": existing.name,
                "email": existing.email,
                "subscribed_at": existing.subscribed_at.isoformat() if existing.subscribed_at else None,
                "message": "Already subscribed",
            }

        user = User(name=req.name, email=req.email)
        session.add(user)
        session.commit()
        session.refresh(user)

        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "subscribed_at": user.subscribed_at.isoformat() if user.subscribed_at else None,
            "message": "Subscribed successfully",
        }


@app.get("/api/v1/users")
async def get_users():
    """Return all subscribed users."""
    with get_session() as session:
        users = session.query(User).order_by(User.subscribed_at.desc()).all()
        return [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "subscribed_at": u.subscribed_at.isoformat() if u.subscribed_at else None,
            }
            for u in users
        ]


@app.post("/api/v1/scheduler/subscribe")
async def scheduler_subscribe(req: SchedulerSubscribeRequest):
    """
    Subscribe an email for daily scheduled report delivery.
    Name is optional; if omitted, we derive it from email prefix.
    """
    email = req.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email.")

    derived_name = (req.name or "").strip()
    if not derived_name:
        local = email.split("@")[0]
        derived_name = local.replace(".", " ").replace("_", " ").title()

    with get_session() as session:
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            if req.name and existing.name != derived_name:
                existing.name = derived_name
                session.commit()
            return {
                "id": existing.id,
                "name": existing.name,
                "email": existing.email,
                "schedule_time": settings.daily_run_time,
                "timezone": settings.timezone,
                "message": "Already subscribed for daily schedule",
            }

        user = User(name=derived_name, email=email)
        session.add(user)
        session.commit()
        session.refresh(user)
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "schedule_time": settings.daily_run_time,
            "timezone": settings.timezone,
            "message": "Subscribed for daily schedule",
        }


@app.get("/api/v1/scheduler/subscribers")
async def scheduler_subscribers():
    with get_session() as session:
        users = session.query(User).order_by(User.subscribed_at.desc()).all()
        return {
            "schedule_time": settings.daily_run_time,
            "timezone": settings.timezone,
            "subscribers": [
                {
                    "id": u.id,
                    "name": u.name,
                    "email": u.email,
                    "subscribed_at": u.subscribed_at.isoformat() if u.subscribed_at else None,
                }
                for u in users
            ],
        }


@app.post("/api/v1/compare")
async def compare_runs(req: CompareRequest):
    """
    Compare two selected dates by running full pipelines for both dates in parallel.
    First call (without run ids) triggers both runs and returns running.
    Subsequent polls (with run ids) return running/completed with diff payload.
    """
    target_a = _parse_iso_date(req.date_a)
    target_b = _parse_iso_date(req.date_b)

    if target_b < target_a:
        raise HTTPException(status_code=400, detail="date_b must be same or after date_a.")

    def _since_days_for_date(target: date) -> int:
        delta = (datetime.now(timezone.utc).date() - target).days
        return max(1, delta + 1)

    # First request: trigger both runs in parallel
    if req.run_a_id is None or req.run_b_id is None:
        created_run_ids: List[int] = []

        async def _schedule(label_date: date):
            run_config = {
                "requested_mode": "full",
                "requested_agents": _mode_to_agents("full"),
                "comparison_target_date": label_date.isoformat(),
                "comparison_diff_view": True,
                "suppress_email": True,
            }
            initial_state = prepare_radar_run(
                mode="full",
                since_days=_since_days_for_date(label_date),
                config=run_config,
                trigger="UI",
                user_id=None,
                email_recipients=[],
                custom_urls=[],
                url_mode="default",
            )
            run_db_id = initial_state.get("run_db_id")
            if run_db_id:
                created_run_ids.append(run_db_id)

                async def _runner_task(state):
                    try:
                        await execute_prepared_radar(state)
                    finally:
                        _background_runs.pop(run_db_id, None)

                _background_runs[run_db_id] = asyncio.create_task(_runner_task(initial_state))

        await asyncio.gather(_schedule(target_a), _schedule(target_b))
        if len(created_run_ids) < 2:
            raise HTTPException(status_code=500, detail="Failed to start compare runs.")

        return {
            "status": "running",
            "message": "Compare runs started in parallel. Poll for completion.",
            "date_a": req.date_a,
            "date_b": req.date_b,
            "run_a_id": created_run_ids[0],
            "run_b_id": created_run_ids[1],
        }

    with get_session() as session:
        run_a = session.query(Run).filter(Run.id == req.run_a_id).first()
        run_b = session.query(Run).filter(Run.id == req.run_b_id).first()

    if not run_a or not run_b:
        raise HTTPException(status_code=404, detail="One or both compare run ids not found.")

    status_a = _normalize_run_status(run_a.status)
    status_b = _normalize_run_status(run_b.status)
    if status_a == "running" or status_b == "running":
        return {
            "status": "running",
            "message": "Compare runs are still processing. Keep polling.",
            "date_a": req.date_a,
            "date_b": req.date_b,
            "run_a_id": run_a.id,
            "run_b_id": run_b.id,
            "run_a_status": status_a,
            "run_b_status": status_b,
        }

    if status_a == "failed" or status_b == "failed":
        return {
            "status": "completed",
            "date_a": req.date_a,
            "date_b": req.date_b,
            "run_a_id": run_a.id,
            "run_b_id": run_b.id,
            "summary": {
                "baseline_findings": 0,
                "candidate_findings": 0,
                "added_count": 0,
                "removed_count": 0,
                "impact_changes_count": 0,
                "major_highlights": ["One of the compare runs failed. Please retry compare."],
            },
            "agent_deltas": [],
            "added_findings": [],
            "removed_findings": [],
            "impact_changed_findings": [],
        }

    with get_session() as session:
        findings_a = _collect_run_findings(session, run_a)
        findings_b = _collect_run_findings(session, run_b)

    payload = _compute_compare_payload(run_a, run_b, findings_a, findings_b)
    payload["section_comparison"] = await _generate_llm_section_comparison(
        req.date_a,
        req.date_b,
        findings_a,
        findings_b,
    )
    payload["date_a"] = req.date_a
    payload["date_b"] = req.date_b
    payload["run_a_id"] = run_a.id
    payload["run_b_id"] = run_b.id
    return payload


# ── Export PDF for a specific run ─────────────────────────────────────────

@app.get("/api/v1/runs/{run_id}/export/pdf")
async def export_pdf(run_id: int):
    """
    Download the PDF digest generated by a specific pipeline run.

    Returns the PDF as a downloadable file.
    Returns 404 if the run doesn't exist or has no PDF stored.
    """
    with get_session() as session:
        run = session.query(Run).filter(Run.id == run_id).first()

        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

        if not run.pdf_content:
            raise HTTPException(
                status_code=404,
                detail=f"Run {run_id} has no PDF stored. The pipeline may not have generated a report for this run.",
            )

        # Derive a nice filename from pdf_path or fall back to run_id
        filename = f"digest-run-{run_id}.pdf"
        if run.pdf_path:
            from pathlib import Path
            filename = Path(run.pdf_path).name

        return Response(
            content=run.pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )


# ── GET all runs with findings + resources ────────────────────────────────

def _parse_json(text: Optional[str]) -> Any:
    """Safely parse a JSON string, return {} on failure."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


@app.get("/api/v1/runs")
async def get_runs(
    status: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
):
    """
    Return all runs joined with their extraction, findings, and resources.

    Response: list of run objects, each with nested findings[] and resources[].
    Binary fields (html_content, pdf_content) are excluded to keep it lightweight.
    """
    with get_session() as session:
        query = session.query(Run).order_by(Run.started_at.desc())
        runs = query.all()

        result = []
        for run in runs:
            normalized_status = _normalize_run_status(run.status)
            if status and normalized_status != status:
                continue
            if start_date and run.started_at and run.started_at.date().isoformat() < start_date:
                continue
            if end_date and run.started_at and run.started_at.date().isoformat() > end_date:
                continue

            # ── Extraction metadata
            extraction = (
                session.query(Extraction)
                .filter(Extraction.id == run.extraction_id)
                .first()
            ) if run.extraction_id else None

            # ── Findings for this extraction (exclude heavy binary columns)
            findings_rows = (
                session.query(Finding)
                .filter(Finding.extraction_id == run.extraction_id)
                .all()
            ) if run.extraction_id else []

            findings_out = []
            findings_by_agent = {a: 0 for a in AGENT_ORDER}
            for f in findings_rows:
                finding_meta = _parse_json(f.metadata_)
                agent_ui = f.agent_name.replace("_intel", "").replace("provider", "model").replace("hf", "benchmark")
                if agent_ui in findings_by_agent:
                    findings_by_agent[agent_ui] += 1
                findings_out.append({
                    "id": f.id,
                    "agent_name": f.agent_name,
                    "metadata": finding_meta,
                })

            # ── Resources for this run
            resources_rows = (
                session.query(Resource)
                .filter(Resource.run_id == run.id)
                .all()
            )

            resources_out = []
            for r in resources_rows:
                resources_out.append({
                    "id": r.id,
                    "agent_name": r.agent_name,
                    "name": r.name,
                    "url": r.url,
                    "resource_type": r.resource_type,
                    "discovered_at": r.discovered_at.isoformat() if r.discovered_at else None,
                })

            # ── User who triggered this run
            user = (
                session.query(User).filter(User.id == run.user_id).first()
            ) if run.user_id else None

            extraction_meta = _parse_json(extraction.metadata_) if extraction else {}
            selected_agents = extraction_meta.get("requested_agents") or _mode_to_agents(extraction_meta.get("requested_mode", "full"))
            if not selected_agents:
                selected_agents = AGENT_ORDER

            recipient_emails = extraction_meta.get("email_recipients", [])
            custom_urls = extraction_meta.get("custom_urls", [])
            requested_mode = extraction_meta.get("requested_mode", "full")

            result.append({
                "run_id": run.id,
                "extraction_id": run.extraction_id,
                "user_id": run.user_id,
                "user_name": user.name if user else None,
                "mode": requested_mode,
                "status": normalized_status,
                "time_taken": run.time_taken,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": _finished_at_iso(run),
                "recipient_emails": recipient_emails,
                "custom_urls": custom_urls,
                "agent_statuses": _serialize_agent_statuses(selected_agents, findings_by_agent, normalized_status),
                "findings_count": len(findings_out),
                "pdf_available": bool(run.pdf_content),
                "pdf_path": run.pdf_path,
                "extraction_metadata": extraction_meta,
                "findings": findings_out,
                "resources": resources_out,
            })

    return result


@app.get("/api/v1/runs/{run_id}")
async def get_run_detail(run_id: int):
    # ── L1: Redis digest cache — served in ~2ms, skips all DB queries ────
    from cache.redis_client import get_digest_cache
    cached = get_digest_cache(run_id)
    if cached:
        return {
            "run_id":          run_id,
            "status":          "success",
            "cache_hit":       True,
            "digest_json":     cached.get("digest_json", {}),
            "digest_markdown": cached.get("digest_markdown", ""),
            "ranked_findings": cached.get("ranked_findings", []),
            "findings_count":  len(cached.get("ranked_findings", [])),
            "errors_count":    cached.get("errors_count", 0),
        }

    with get_session() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

        extraction = (
            session.query(Extraction).filter(Extraction.id == run.extraction_id).first()
            if run.extraction_id else None
        )
        findings_rows = (
            session.query(Finding).filter(Finding.extraction_id == run.extraction_id).all()
            if run.extraction_id else []
        )
        resources_rows = session.query(Resource).filter(Resource.run_id == run.id).all()
        user = session.query(User).filter(User.id == run.user_id).first() if run.user_id else None

        normalized_status = _normalize_run_status(run.status)
        extraction_meta = _parse_json(extraction.metadata_) if extraction else {}
        selected_agents = extraction_meta.get("requested_agents") or _mode_to_agents(extraction_meta.get("requested_mode", "full"))
        if not selected_agents:
            selected_agents = AGENT_ORDER

        findings_by_agent = {a: 0 for a in AGENT_ORDER}
        findings_out: List[Dict[str, Any]] = []
        for f in findings_rows:
            meta = _parse_json(f.metadata_)
            agent_ui = f.agent_name.replace("_intel", "").replace("provider", "model").replace("hf", "benchmark")
            if agent_ui in findings_by_agent:
                findings_by_agent[agent_ui] += 1
            findings_out.append({
                "id": f.id,
                "agent_name": f.agent_name,
                "metadata": meta,
            })

        return {
            "run_id": run.id,
            "status": normalized_status,
            "mode": extraction_meta.get("requested_mode", "full"),
            "selected_agents": selected_agents,
            "recipient_emails": extraction_meta.get("email_recipients", []),
            "custom_urls": extraction_meta.get("custom_urls", []),
            "url_mode": extraction_meta.get("url_mode", "default"),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": _finished_at_iso(run),
            "time_taken": run.time_taken,
            "user_id": run.user_id,
            "user_name": user.name if user else None,
            "findings_count": len(findings_out),
            "agent_statuses": _serialize_agent_statuses(selected_agents, findings_by_agent, normalized_status),
            "pdf_available": bool(run.pdf_content),
            "pdf_path": run.pdf_path,
            "findings": findings_out,
            "resources": [
                {
                    "id": r.id,
                    "agent_name": r.agent_name,
                    "name": r.name,
                    "url": r.url,
                    "resource_type": r.resource_type,
                    "discovered_at": r.discovered_at.isoformat() if r.discovered_at else None,
                }
                for r in resources_rows
            ],
        }


@app.get("/api/v1/runs/{run_id}/logs")
async def get_run_logs(run_id: int):
    """Return per-agent status logs for a given run (thin wrapper around existing logic)."""
    with get_session() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

        extraction = (
            session.query(Extraction).filter(Extraction.id == run.extraction_id).first()
            if run.extraction_id else None
        )
        findings_rows = (
            session.query(Finding).filter(Finding.extraction_id == run.extraction_id).all()
            if run.extraction_id else []
        )

        normalized_status = _normalize_run_status(run.status)
        extraction_meta = _parse_json(extraction.metadata_) if extraction else {}
        selected_agents = extraction_meta.get("requested_agents") or _mode_to_agents(
            extraction_meta.get("requested_mode", "full")
        )
        if not selected_agents:
            selected_agents = AGENT_ORDER

        findings_by_agent = {a: 0 for a in AGENT_ORDER}
        for f in findings_rows:
            agent_ui = f.agent_name.replace("_intel", "").replace("provider", "model").replace("hf", "benchmark")
            if agent_ui in findings_by_agent:
                findings_by_agent[agent_ui] += 1

        agent_statuses = _serialize_agent_statuses(selected_agents, findings_by_agent, normalized_status)

        # Attach any agent_errors from extraction metadata
        agent_errors = extraction_meta.get("agent_errors", {})
        for status_entry in agent_statuses:
            label_lower = status_entry.get("label", "").lower()
            if label_lower in agent_errors:
                status_entry["error"] = agent_errors[label_lower]

        return {
            "run_id": run.id,
            "status": normalized_status,
            "agent_statuses": agent_statuses,
        }


@app.get("/api/v1/dashboard")
async def get_dashboard():
    with get_session() as session:
        last_run = session.query(Run).order_by(Run.started_at.desc()).first()
        top_rows = session.query(Finding).order_by(Finding.id.desc()).limit(50).all()
        top_findings = []
        for row in top_rows:
            meta = _parse_json(row.metadata_)
            if not meta:
                continue
            original_id = str(meta.get("id") or row.id)
            top_findings.append({
                "id": f"{original_id}-{row.id}",
                "original_id": original_id,
                "title": meta.get("title", "Untitled"),
                "date_detected": meta.get("date_detected", ""),
                "source_url": meta.get("source_url", ""),
                "publisher": meta.get("publisher", ""),
                "agent_id": row.agent_name.replace("_intel", "").replace("provider", "model").replace("hf", "benchmark"),
                "category": meta.get("category", "unknown"),
                "summary_short": meta.get("what_changed", ""),
                "summary_long": meta.get("why_it_matters", ""),
                "why_it_matters": meta.get("why_it_matters", ""),
                "evidence": meta.get("evidence_snippet", ""),
                "confidence": meta.get("confidence", "MEDIUM"),
                "tags": meta.get("tags", []),
                "entities": meta.get("entities", []),
                "impact_score": float(meta.get("impact_score", 0) or 0),
            })

        top_findings.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        top_findings = top_findings[:10]

        return {
            "last_run": (
                {
                    "run_id": last_run.id,
                    "status": _normalize_run_status(last_run.status),
                    "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
                    "finished_at": _finished_at_iso(last_run),
                    "time_taken": last_run.time_taken,
                }
                if last_run else None
            ),
            "top_findings": top_findings,
        }


@app.get("/api/v1/findings")
async def get_findings(
    agent_id: Optional[str] = Query(default=None),
    entity: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    run_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    with get_session() as session:
        query = session.query(Finding)
        if run_id:
            run = session.query(Run).filter(Run.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
            if run.extraction_id:
                query = query.filter(Finding.extraction_id == run.extraction_id)
            else:
                return []

        rows = query.order_by(Finding.id.desc()).all()
        output: List[Dict[str, Any]] = []
        for row in rows:
            meta = _parse_json(row.metadata_)
            original_id = str(meta.get("id") or row.id)
            item = {
                "id": f"{original_id}-{row.id}",
                "original_id": original_id,
                "title": meta.get("title", "Untitled"),
                "date_detected": meta.get("date_detected", ""),
                "source_url": meta.get("source_url", ""),
                "publisher": meta.get("publisher", ""),
                "agent_id": row.agent_name.replace("_intel", "").replace("provider", "model").replace("hf", "benchmark"),
                "category": meta.get("category", "unknown"),
                "summary_short": meta.get("what_changed", ""),
                "summary_long": meta.get("why_it_matters", ""),
                "why_it_matters": meta.get("why_it_matters", ""),
                "evidence": meta.get("evidence_snippet", ""),
                "confidence": meta.get("confidence", "MEDIUM"),
                "tags": meta.get("tags", []),
                "entities": meta.get("entities", []),
                "impact_score": float(meta.get("impact_score", 0) or 0),
            }
            if agent_id and item["agent_id"] != agent_id:
                continue
            if category and item["category"] != category:
                continue
            if entity:
                term = entity.lower()
                publisher = (item.get("publisher") or "").lower()
                entities = [str(e).lower() for e in item.get("entities", [])]
                if term not in publisher and not any(term in e for e in entities):
                    continue
            output.append(item)

        output.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        return output[:limit]


# ── Competitor source management ──────────────────────────────────────────

class CompetitorRequest(BaseModel):
    name: str                           # e.g. "Mistral AI Blog"
    url: str                            # e.g. "https://mistral.ai/news/rss.xml"
    source_type: str = "rss"            # "rss" | "webpage"
    selector: Optional[str] = None      # CSS selector (only for webpage type)


@app.get("/api/v1/sources/competitors")
async def list_competitors():
    """
    Return all competitor sources (default + user-added).

    Each row includes is_default and is_active flags so the UI can
    distinguish system-seeded vs user-added and toggle them on/off.
    """
    with get_session() as session:
        rows = session.query(Competitor).order_by(Competitor.id).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "url": c.url,
                "source_type": c.source_type,
                "selector": c.selector,
                "is_default": c.is_default,
                "is_active": c.is_active,
                "added_by": c.added_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ]


@app.post("/api/v1/sources/competitors")
async def add_competitor(req: CompetitorRequest):
    """
    Add a new competitor source URL.

    Body: {"name": "Mistral AI Blog", "url": "https://mistral.ai/news/rss.xml", "source_type": "rss"}
    Returns the created record.  Rejects duplicate URLs.
    """
    if req.source_type not in ("rss", "webpage"):
        raise HTTPException(status_code=400, detail="source_type must be 'rss' or 'webpage'.")

    with get_session() as session:
        existing = session.query(Competitor).filter(Competitor.url == req.url).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"URL already exists (id={existing.id}).")

        competitor = Competitor(
            name=req.name,
            url=req.url,
            source_type=req.source_type,
            selector=req.selector,
            is_default=False,
            is_active=True,
            added_by=None,
        )
        session.add(competitor)
        session.commit()
        session.refresh(competitor)

        return {
            "id": competitor.id,
            "name": competitor.name,
            "url": competitor.url,
            "source_type": competitor.source_type,
            "selector": competitor.selector,
            "is_default": competitor.is_default,
            "is_active": competitor.is_active,
            "message": "Competitor source added successfully",
        }


@app.put("/api/v1/sources/competitors/{competitor_id}")
async def toggle_competitor(competitor_id: int, is_active: bool = True):
    """
    Toggle a competitor source on or off.

    Query param: ?is_active=true  or  ?is_active=false
    """
    with get_session() as session:
        competitor = session.query(Competitor).filter(Competitor.id == competitor_id).first()
        if not competitor:
            raise HTTPException(status_code=404, detail=f"Competitor {competitor_id} not found.")

        competitor.is_active = is_active
        session.commit()

        return {
            "id": competitor.id,
            "name": competitor.name,
            "is_active": competitor.is_active,
            "message": f"Competitor {'activated' if is_active else 'deactivated'}",
        }


class CrawlRequest(BaseModel):
    url: str                            # URL to crawl
    source_type: str = "rss"            # "rss" | "webpage"
    depth: int = 1                      # 1 = single page, 2-3 = follow internal links
    max_pages: int = 10                 # max pages to crawl at depth > 1
    email: Optional[str] = None         # email to send PDF digest to
    mode: str = "competitor"            # which agent(s) to run: "competitor", "research", etc.


@app.post("/api/v1/sources/competitors/crawl")
async def crawl_competitor(req: CrawlRequest):
    """
    Crawl a URL, then run the full pipeline (LLM analysis → ranking → digest
    → PDF → email) with the crawled URL(s) as custom sources.

    Supports deep crawling + headless fallback for JS-rendered pages.
    After crawling, triggers run_radar with url_mode="custom" so the
    intelligence agents analyze the crawled content and produce a PDF digest.

    Supports deep crawling:
      depth=1 → crawl only the given URL (default)
      depth=2 → crawl the URL + follow internal links found on it
      depth=3 → crawl the URL + follow links + follow links from those pages

    Body examples:
      {"url": "https://openai.com/blog/rss.xml", "source_type": "rss", "email": "a@b.com"}
      {"url": "https://openai.com/blog", "source_type": "webpage", "depth": 2, "email": "a@b.com"}
      {"url": "https://openai.com/blog", "source_type": "webpage", "depth": 3, "max_pages": 15}
    """
    if req.source_type not in ("rss", "webpage"):
        raise HTTPException(status_code=400, detail="source_type must be 'rss' or 'webpage'.")
    if req.depth < 1 or req.depth > 3:
        raise HTTPException(status_code=400, detail="depth must be 1, 2, or 3.")
    if req.max_pages < 1 or req.max_pages > 30:
        raise HTTPException(status_code=400, detail="max_pages must be between 1 and 30.")

    from core.tools import crawl_page, fetch_rss_feed, fetch_headless

    try:
        crawl_result: dict = {}

        # ── RSS: simple, no depth needed ─────────────────────────────
        if req.source_type == "rss":
            items = await fetch_rss_feed.ainvoke({"url": req.url})
            if not isinstance(items, list):
                items = []
            crawl_result = {
                "url": req.url,
                "source_type": "rss",
                "items_count": len(items),
                "items": items,
                "method": "rss_parser",
                "depth": 1,
            }

        else:
            # ── Webpage: smart crawl with auto-fallback + depth ──────

            async def _smart_crawl(target_url: str) -> dict:
                """Try crawl_page first, auto-fallback to headless if blocked."""
                page_result = await crawl_page.ainvoke({"url": target_url})
                method_used = "crawl_page"

                if isinstance(page_result, dict):
                    status = page_result.get("status_code", 0)
                    content_len = page_result.get("content_length", 0)
                    content = page_result.get("content", "")

                    needs_headless = (
                        status == 403
                        or status == 0
                        or content_len < 100
                        or ("javascript" in content.lower() and content_len < 200)
                    )

                    if needs_headless:
                        print(f"[CRAWL] crawl_page blocked for {target_url} (status={status}), trying headless...")
                        page_result = await fetch_headless.ainvoke({"url": target_url})
                        method_used = "headless_browser"

                if not isinstance(page_result, dict):
                    page_result = {"url": target_url, "error": "Failed to crawl"}

                page_result["method"] = method_used
                return page_result

            # ── Depth 1: single page ─────────────────────────────────
            root_page = await _smart_crawl(req.url)
            all_items = [root_page]
            visited = {req.url.rstrip("/")}

            if req.depth >= 2:
                # ── Depth 2: follow links from root page ─────────────
                links = root_page.get("links", [])
                print(f"[CRAWL] Depth 2: found {len(links)} links on {req.url}")

                depth2_urls = []
                for link in links[:req.max_pages]:
                    link_url = link.get("url", "").rstrip("/")
                    if link_url and link_url not in visited:
                        depth2_urls.append(link_url)
                        visited.add(link_url)

                for child_url in depth2_urls:
                    print(f"[CRAWL] Depth 2: crawling {child_url}")
                    child_page = await _smart_crawl(child_url)
                    all_items.append(child_page)

                if req.depth >= 3:
                    # ── Depth 3: follow links from depth-2 pages ─────
                    remaining = req.max_pages - len(all_items)
                    if remaining > 0:
                        depth3_urls = []
                        for item in all_items[1:]:  # skip root
                            for link in item.get("links", []):
                                link_url = link.get("url", "").rstrip("/")
                                if link_url and link_url not in visited:
                                    depth3_urls.append(link_url)
                                    visited.add(link_url)
                                    if len(depth3_urls) >= remaining:
                                        break
                            if len(depth3_urls) >= remaining:
                                break

                        for child_url in depth3_urls:
                            print(f"[CRAWL] Depth 3: crawling {child_url}")
                            child_page = await _smart_crawl(child_url)
                            all_items.append(child_page)

            # Remove 'links' from response items to keep it clean
            for item in all_items:
                item.pop("links", None)

            crawl_result = {
                "url": req.url,
                "source_type": "webpage",
                "depth": req.depth,
                "items_count": len(all_items),
                "items": all_items,
            }

        # ── PIPELINE: run full analysis → PDF → email ─────────────────
        print(f"[CRAWL] Crawl complete. Triggering pipeline (mode={req.mode}, url_mode=custom)...")

        # Resolve email recipients
        email_recipients: List[str] = []
        resolved_user_id: Optional[int] = None

        if req.email:
            with get_session() as session:
                user = session.query(User).filter(User.email == req.email).first()
                if not user:
                    name = req.email.split("@")[0].replace(".", " ").title()
                    user = User(name=name, email=req.email)
                    session.add(user)
                    session.commit()
                    session.refresh(user)
                resolved_user_id = user.id
                email_recipients = [user.email]
        else:
            # No email provided — send to all subscribers
            with get_session() as session:
                users = session.query(User).all()
                email_recipients = [u.email for u in users]

        # Run the pipeline with the crawled URL as custom source
        state = await run_radar(
            mode=req.mode,
            since_days=1,
            trigger="UI",
            user_id=resolved_user_id,
            email_recipients=email_recipients,
            custom_urls=[req.url],
            url_mode="custom",
        )

        # Combine crawl results + pipeline results
        crawl_result["pipeline"] = {
            "run_id": state.get("run_id", ""),
            "status": "completed",
            "mode": req.mode,
            "findings_count": len(state.get("ranked_findings", [])),
            "email_status": state.get("email_status", ""),
            "pdf_path": state.get("pdf_path", ""),
            "errors": state.get("errors", []),
        }

        return crawl_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl + pipeline failed: {str(e)}")


@app.delete("/api/v1/sources/competitors/{competitor_id}")
async def delete_competitor(competitor_id: int):
    """
    Delete a user-added competitor source.

    Default (seeded) sources cannot be deleted — deactivate them instead
    via PUT /competitors/{id}?is_active=false.
    """
    with get_session() as session:
        competitor = session.query(Competitor).filter(Competitor.id == competitor_id).first()
        if not competitor:
            raise HTTPException(status_code=404, detail=f"Competitor {competitor_id} not found.")

        if competitor.is_default:
            raise HTTPException(
                status_code=403,
                detail="Cannot delete a default source. Use PUT /api/v1/sources/competitors/{id}?is_active=false to deactivate it.",
            )

        session.delete(competitor)
        session.commit()

        return {"message": f"Competitor '{competitor.name}' deleted successfully."}


# ── Authentication ────────────────────────────────────────────────────────

JWT_SECRET = settings.api_secret_key or "frontier-ai-radar-default-secret"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


def _hash_password(password: str) -> str:
    """Hash a password with a random salt using PBKDF2."""
    salt = secrets.token_hex(16)
    hash_val = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${hash_val.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt, hash_hex = stored.split("$", 1)
        hash_val = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return hash_val.hex() == hash_hex
    except (ValueError, AttributeError):
        return False


def _create_jwt(user_id: int, email: str, name: str, is_admin: bool = False) -> str:
    """Create a JWT token for the given user."""
    if pyjwt is None:
        # Fallback: simple base64 token (not secure, but works without PyJWT)
        import base64
        payload_str = json.dumps({"user_id": user_id, "email": email, "name": name, "is_admin": is_admin})
        return base64.urlsafe_b64encode(payload_str.encode()).decode()
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT token."""
    if pyjwt is None:
        import base64
        try:
            payload_str = base64.urlsafe_b64decode(token.encode()).decode()
            return json.loads(payload_str)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token.")
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please sign in again.")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class SigninRequest(BaseModel):
    email: str
    password: str


@app.post("/api/v1/auth/signup")
async def auth_signup(req: SignupRequest):
    """
    Register a new user account.

    If the email already exists as a subscriber (no password), it will be
    upgraded to a full account with login credentials.
    """
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if "@" not in req.email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    with get_session() as session:
        existing = session.query(User).filter(User.email == req.email.strip().lower()).first()

        if existing and existing.password_hash:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Please sign in.",
            )

        if existing:
            # Upgrade existing subscriber to full account
            existing.password_hash = _hash_password(req.password)
            if req.name.strip():
                existing.name = req.name.strip()
            session.commit()
            session.refresh(existing)
            token = _create_jwt(existing.id, existing.email, existing.name, bool(existing.is_admin))
            return {
                "token": token,
                "user": {"id": existing.id, "name": existing.name, "email": existing.email, "is_admin": bool(existing.is_admin)},
            }

        # Create new user (new signups are regular users by default)
        user = User(
            name=req.name.strip(),
            email=req.email.strip().lower(),
            password_hash=_hash_password(req.password),
            is_admin=False,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        token = _create_jwt(user.id, user.email, user.name, bool(user.is_admin))
        return {
            "token": token,
            "user": {"id": user.id, "name": user.name, "email": user.email, "is_admin": bool(user.is_admin)},
        }


@app.post("/api/v1/auth/signin")
async def auth_signin(req: SigninRequest):
    """
    Authenticate a user and return a JWT token.
    """
    with get_session() as session:
        user = session.query(User).filter(User.email == req.email.strip().lower()).first()

        if not user or not user.password_hash:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        if not _verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        token = _create_jwt(user.id, user.email, user.name, bool(user.is_admin))
        return {
            "token": token,
            "user": {"id": user.id, "name": user.name, "email": user.email, "is_admin": bool(user.is_admin)},
        }


@app.get("/api/v1/auth/me")
async def auth_me(request: Request):
    """
    Validate the current JWT token and return the authenticated user.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header.")

    token = auth_header.split(" ", 1)[1]
    payload = _decode_jwt(token)

    return {
        "user": {
            "id": payload.get("user_id"),
            "name": payload.get("name"),
            "email": payload.get("email"),
            "is_admin": payload.get("is_admin", True),  # default True for existing tokens without the field
        }
    }


# ── Blob Asset SAS URLs ───────────────────────────────────────────────────────

@app.get("/api/v1/runs/{run_id}/asset")
async def get_run_asset_url(
    run_id: int,
    type: str = Query(..., description="Asset type: 'pdf' or 'audio'"),
):
    """Return a time-limited SAS URL for a run's PDF or audio blob asset.

    Checks the DB-cached SAS first (valid for 24 h with 1 h buffer).
    Generates and caches a fresh SAS if the cached one is missing or expired.

    Returns:
        {"url": "https://...", "asset_type": "pdf"|"audio"}

    Raises:
        400 — unknown asset type
        404 — run not found, or blob path not set for that asset
        503 — Azure Blob not configured
        500 — SAS generation failed
    """
    if type not in ("pdf", "audio"):
        raise HTTPException(status_code=400, detail="type must be 'pdf' or 'audio'")

    with get_session() as session:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        blob_path = run.blob_pdf_path if type == "pdf" else run.blob_audio_path
        if not blob_path:
            raise HTTPException(
                status_code=404,
                detail=f"No {type} blob path found for run {run_id}. "
                       "Asset may not have been uploaded yet.",
            )

        try:
            from storage.blob import get_or_refresh_sas, is_configured
        except ImportError:
            raise HTTPException(status_code=503, detail="Blob storage module unavailable")

        if not is_configured():
            raise HTTPException(status_code=503, detail="Azure Blob Storage is not configured")

        sas_cache: dict = run.blob_sas_cache or {}
        url, updated_field = get_or_refresh_sas(sas_cache, type, blob_path)

        if not url:
            raise HTTPException(status_code=500, detail="Failed to generate secure URL")

        # Persist the refreshed SAS back to DB if it was regenerated
        if updated_field is not None:
            new_cache = dict(sas_cache)
            new_cache[type] = updated_field
            run.blob_sas_cache = new_cache
            session.commit()

        return {"url": url, "asset_type": type}


# ── Digest Chat ──────────────────────────────────────────────────────────

class DigestChatRequest(BaseModel):
    run_id: str
    message: str
    history: List[Dict[str, str]] = []


@app.get("/api/v1/voice/{run_id}/history")
async def get_voice_history(
    run_id:  int,
    user_id: Optional[int] = Query(default=None),
):
    """Return persisted voice conversation history for (run_id, user_id).

    Used by the voice page on load to restore the conversation transcript and
    to initialise the IndexedDB audio-key counter so new recordings don't
    overwrite existing ones.
    """
    from db.chat import get_or_create_session, load_voice_history

    info       = get_or_create_session(run_id=run_id, user_id=user_id)
    session_id = info["session_id"]
    is_new     = info.get("is_new", False)
    messages   = load_voice_history(session_id)

    return {
        "session_id": session_id,
        "is_new":     is_new,
        "messages":   messages,
    }


@app.websocket("/api/v1/voice/{run_id}")
async def voice_websocket(websocket: WebSocket, run_id: int):
    """Real-time voice agent WebSocket.

    Connect:  ws://host/api/v1/voice/{run_id}?user_id=<int>

    Protocol: see api/voice.py module docstring.
    """
    # Parse user_id manually from query string — avoids FastAPI injection issues
    # on WebSocket routes in some versions
    user_id: Optional[int] = None
    raw_uid = websocket.query_params.get("user_id")
    if raw_uid:
        try:
            user_id = int(raw_uid)
        except ValueError:
            pass
    from api.voice import voice_session
    await voice_session(websocket, run_id=run_id, user_id=user_id)


@app.post("/chat")
async def chat_with_digest(req: DigestChatRequest):
    """Chat with an AI about a specific digest run using the run's findings as context."""
    try:
        run_id_int = int(req.run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="run_id must be a valid integer string")

    with get_session() as session:
        run = session.get(Run, run_id_int)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        findings = (
            session.query(Finding)
            .filter(Finding.run_id == run_id_int)
            .order_by(Finding.rank.asc().nullslast(), Finding.impact_score.desc())
            .limit(25)
            .all()
        )

        # Build digest context from findings
        date_label = run.started_at.strftime("%B %d, %Y") if run.started_at else "Unknown date"
        ctx_lines = [f"AI Intelligence Brief — {date_label}", ""]
        for i, f in enumerate(findings, 1):
            ctx_lines.append(f"{i}. {f.title or 'Untitled'}")
            if f.what_changed:
                ctx_lines.append(f"   What changed: {f.what_changed}")
            if f.why_it_matters:
                ctx_lines.append(f"   Why it matters: {f.why_it_matters}")
            if f.source_url:
                ctx_lines.append(f"   Source: {f.source_url}")
            ctx_lines.append("")
        digest_context = "\n".join(ctx_lines)

    system_prompt = (
        "You are an AI intelligence assistant for Centific's Frontier AI Radar system. "
        "You have access to a curated AI intelligence digest. "
        "Answer questions based on the digest findings below. "
        "Be concise, insightful, and helpful. "
        "If a question requires deeper information not in the digest, say you can perform a deep search and provide what you know. "
        "Format key points with **bold** for emphasis.\n\n"
        f"DIGEST:\n{digest_context}"
    )

    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage as LCAIMessage

    lc_messages = [SystemMessage(content=system_prompt)]
    for h in req.history[-12:]:
        if h.get("role") == "user":
            lc_messages.append(HumanMessage(content=h["content"]))
        elif h.get("role") == "assistant":
            lc_messages.append(LCAIMessage(content=h["content"]))
    lc_messages.append(HumanMessage(content=req.message))

    try:
        llm = _build_llm()
        result = await llm.ainvoke(lc_messages)
        response_text = result.content if hasattr(result, "content") else str(result)
    except Exception as e:
        logger.error("chat_llm_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

    sources = [f.source_url for f in findings[:5] if f.source_url]

    return {
        "response": response_text,
        "sources": sources,
        "needs_deep_search": False,
    }


# ── Chat infrastructure — lazy singletons ─────────────────────────────────────
# Both the checkpointer and the chat agent are created once on first request
# and reused for the lifetime of the process.  The checkpointer is the same
# AsyncPostgresSaver used by the digest pipeline — the two graphs share it so
# the chat agent can read digest run state via query_digest_state tool.

_chat_graph_singleton = None


async def _get_chat_graph():
    """Lazy-init and return the unified radar graph singleton for chat requests.

    This is the SAME graph as the digest pipeline — create_radar_graph() — with
    the chat_agent node embedded as a subgraph.  The checkpointer is shared so
    query_digest_state can read from digest run checkpoints.

    Digest pipeline runs use their own graph instances created per-run inside
    execute_prepared_radar.  Both share the same PostgreSQL checkpointer (same DB).
    Graph instances are stateless Python objects; state lives in the checkpointer.
    """
    global _chat_graph_singleton
    if _chat_graph_singleton is not None:
        return _chat_graph_singleton
    try:
        from pipeline.runner import _build_checkpointer
        from pipeline.graph import create_radar_graph
        checkpointer          = await _build_checkpointer()
        _chat_graph_singleton = create_radar_graph(checkpointer=checkpointer)
        logger.info("Unified radar graph (chat) initialised",
                    checkpointer=checkpointer is not None)
    except Exception as exc:
        logger.error("chat_graph_init_failed", error=str(exc))
    return _chat_graph_singleton


def _lg_messages_to_chat_format(lg_messages: list) -> list:
    """Convert LangGraph MessagesState message objects to frontend {role, content} dicts."""
    result = []
    for msg in lg_messages:
        if not hasattr(msg, "type"):
            continue
        if msg.type == "human":
            # Strip the [Digest Run ID: N] prefix we inject per turn
            content = re.sub(r"^\[Digest Run ID: \d+\]\n", "", msg.content or "")
            result.append({"role": "user", "content": content})
        elif msg.type == "ai" and not getattr(msg, "tool_calls", []):
            # Only include final AI responses, not tool-call intermediates
            if msg.content:
                result.append({"role": "assistant", "content": msg.content})
    return result


# ── Chat Session ─────────────────────────────────────────────────────────────

@app.get("/api/v1/chat/session")
async def get_chat_session(
    run_id:  int           = Query(...),
    user_id: Optional[int] = Query(default=None),
):
    """
    Get-or-create a chat session for (user_id, run_id) and return the most
    recent 10 messages from the DB.

    For authenticated users the most-recently-active session for (user_id,
    run_id) is found directly via a JOIN — no client-side session_id needed.
    """
    from db.chat import (
        get_or_create_session,
        get_recent_messages_for_run,
        get_popular_questions,
    )

    messages: list = []
    session_id: Optional[str] = None
    is_new = False

    # ── Authenticated: pull the 10 most recent messages straight from DB ──
    if user_id:
        messages, session_id = get_recent_messages_for_run(
            user_id=user_id, run_id=run_id, limit=10
        )

    # ── Resolve / create session row ──────────────────────────────────────
    if not session_id:
        session_info = get_or_create_session(run_id=run_id, user_id=user_id)
        session_id   = session_info["session_id"]
        is_new       = session_info["is_new"]

    popular = get_popular_questions(run_id=run_id, limit=5)

    return {
        "session_id":        session_id,
        "is_new":            is_new,
        "message_count":     len(messages),
        "messages":          messages,
        "popular_questions": [p["question"] for p in popular],
    }


# ── Production Chat Agent — LangGraph ReAct + streaming SSE ──────────────
#
# Architecture:
#   L1  Redis exact-match cache   ~0.5 ms  (bypasses LangGraph entirely)
#   L2  DB    exact-match cache   ~5 ms    (bypasses LangGraph entirely)
#   L3  Semantic similarity       ~20 ms   (bypasses LangGraph entirely)
#   L4  LangGraph ReAct agent     3–8 s    (query_digest_state + search_web tools)
#
# Conversation memory:
#   LangGraph AsyncPostgresSaver checkpoints MessagesState per
#   thread_id = "chat_{session_id}" — no separate Redis/DB needed.
#
# Cross-graph state access:
#   The chat agent's query_digest_state tool reads from the digest graph's
#   checkpoint (thread_id = "run_{run_db_id}") using the SAME checkpointer.
#   This is LangGraph's multi-agent pattern — not a two-system split.

class ChatAskRequest(BaseModel):
    run_id:     str
    message:    str
    history:    List[Dict[str, str]] = []  # kept for API compatibility; LangGraph is primary
    mode:       str = "text"               # "text" (SSE stream) | "voice" (JSON + audio)
    session_id: Optional[str] = None
    user_id:    Optional[int] = None


@app.post("/api/v1/chat/ask")
async def chat_ask(req: ChatAskRequest):
    """
    Production chat endpoint backed by LangGraph ReAct chat agent.

    Cache hierarchy (each level bypasses LangGraph entirely on hit):
      L1  Redis exact-match    ~0.5 ms
      L2  DB    exact-match    ~5 ms
      L3  Semantic similarity  ~20 ms  (Python cosine over FLOAT[] column)
      L4  LangGraph ReAct      3-8 s   (query_digest_state + search_web tools)

    Conversation persistence (L4 path):
      LangGraph AsyncPostgresSaver checkpoints MessagesState per
      thread_id = "chat_{session_id}" automatically on every turn.
    """
    from db.chat import (
        get_or_create_session,
        cache_lookup_exact, cache_lookup_semantic,
    )
    from cache.redis_client import get_cached_answer, set_cached_answer
    from db.chat import _hash

    try:
        run_id_int = int(req.run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="run_id must be a valid integer")

    session_id = req.session_id
    if not session_id:
        info       = get_or_create_session(run_id=run_id_int, user_id=req.user_id)
        session_id = info["session_id"]

    # ── Load conversation context first — needed for cache bypass decision ─
    from db.chat import get_recent_messages
    session_ctx    = get_or_create_session(run_id=run_id_int, user_id=req.user_id)
    window_context = session_ctx.get("window_context")
    prior_messages = get_recent_messages(session_id, limit=10)
    has_history    = bool(prior_messages)

    # ── L1/L2/L3 cache — SKIP when conversation history exists ────────────
    # Cache keys are global per (run_id, question_hash) — they have no session
    # context. A cached "what is my name" answer from session A must never be
    # served to session B. Any question that can reference prior turns is
    # context-dependent and must go through the LLM every time.
    q_hash = _hash(req.message)
    if not has_history:
        cached = get_cached_answer(run_id_int, q_hash)
        if cached:
            logger.info("chat_cache_hit", level="L1_redis", session=session_id)
            if req.mode == "voice":
                return await _make_voice_response(cached["answer"], cached.get("sources", []))
            return _make_sse_response(cached["answer"], cached.get("sources", []))

        cached = cache_lookup_exact(run_id_int, req.message)
        if cached:
            logger.info("chat_cache_hit", level="L2_db_exact", session=session_id)
            set_cached_answer(run_id_int, q_hash, cached)
            if req.mode == "voice":
                return await _make_voice_response(cached["answer"], cached.get("sources", []))
            return _make_sse_response(cached["answer"], cached.get("sources", []))

        cached = cache_lookup_semantic(run_id_int, req.message)
        if cached:
            logger.info("chat_cache_hit", level="L3_semantic",
                        sim=cached["cache_hit"], session=session_id)
            set_cached_answer(run_id_int, q_hash, cached)
            if req.mode == "voice":
                return await _make_voice_response(cached["answer"], cached.get("sources", []))
            return _make_sse_response(cached["answer"], cached.get("sources", []))
    else:
        logger.info("chat_cache_bypass", reason="conversation_history_exists",
                    session=session_id, prior_count=len(prior_messages))

    # ── L4: Unified LangGraph radar graph → chat_agent node ──────────────
    radar_graph = await _get_chat_graph()
    if not radar_graph:
        raise HTTPException(status_code=503, detail="Chat graph not available")

    chat_state   = create_chat_initial_state(
        run_id_int, req.message, session_id, req.mode,
        prior_messages=prior_messages,
        window_context=window_context,
    )
    agent_config = {"configurable": {"thread_id": f"chat_{session_id}"}}

    # ── Voice mode — collect full response then TTS ───────────────────────
    if req.mode == "voice":
        try:
            result      = await radar_graph.ainvoke(chat_state, config=agent_config)
            lg_messages = result.get("messages", [])
            response_text = ""
            for msg in reversed(lg_messages):
                if (hasattr(msg, "type") and msg.type == "ai"
                        and not getattr(msg, "tool_calls", [])
                        and msg.content):
                    response_text = msg.content
                    break
            response_text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", response_text)
            response_text = re.sub(r"#+\s*", "", response_text)
            response_text = re.sub(r"\[Finding\s*\d+\]", "", response_text)
        except Exception as exc:
            logger.error("chat_ask_agent_error", error=str(exc))
            raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

        asyncio.create_task(
            _save_to_cache(run_id_int, req.message, response_text, [], req.mode)
        )
        from db.chat import save_message
        try:
            save_message(session_id, "user", req.message, mode=req.mode)
            count = save_message(session_id, "assistant", response_text, mode=req.mode)
            if count % 5 == 0:
                asyncio.create_task(_summarise_and_update(session_id, count))
        except Exception as _e:
            logger.warning("chat_save_message_failed", error=str(_e))
        return await _make_voice_response(response_text, [])

    # ── Text mode — streaming SSE via astream_events ─────────────────────
    async def _token_stream():
        full_text   = ""
        source_urls: List[str] = []
        try:
            async for event in radar_graph.astream_events(
                chat_state, config=agent_config, version="v2"
            ):
                kind      = event["event"]
                node_name = event.get("metadata", {}).get("langgraph_node", "")

                if kind == "on_chat_model_stream":
                    token = event["data"]["chunk"].content
                    if token:
                        full_text += token
                        yield f"data: {json.dumps({'token': token})}\n\n"

                elif kind == "on_tool_start" and node_name in ("tools", "chat_agent"):
                    tool_name = event.get("name", "")
                    if tool_name == "search_web":
                        yield f"data: {json.dumps({'status': 'Searching the web...'})}\n\n"
                    elif tool_name == "query_digest_state":
                        yield f"data: {json.dumps({'status': 'Loading digest context...'})}\n\n"

                elif kind == "on_tool_end" and event.get("name") == "search_web":
                    output = str(event["data"].get("output", ""))
                    # Primary: extract from the structured JSON block appended by search_web
                    json_match = re.search(r"__SOURCES_JSON__:(\[.*?\])", output)
                    if json_match:
                        try:
                            extracted = json.loads(json_match.group(1))
                            for url in extracted:
                                url = url.strip().rstrip(".,;:)>]\"'")
                                if url and url not in source_urls:
                                    source_urls.append(url)
                        except Exception:
                            pass
                    else:
                        # Fallback: regex over "Source: URL" lines, strip trailing punctuation
                        for url in re.findall(r"Source:\s*(https?://\S+)", output):
                            url = re.sub(r'[.,;:)\]>"\']+$', '', url).strip()
                            if url and url not in source_urls:
                                source_urls.append(url)

            yield f"data: {json.dumps({'done': True, 'sources': source_urls, 'session_id': session_id})}\n\n"

            if full_text:
                asyncio.create_task(
                    _save_to_cache(run_id_int, req.message, full_text, source_urls, req.mode)
                )
                # Save messages to DB synchronously so next request has history
                # Summary generation (every 5 msgs) runs in background — it's the slow part
                from db.chat import save_message, load_session_messages, update_window_context
                try:
                    save_message(session_id, "user", req.message, mode=req.mode)
                    count = save_message(session_id, "assistant", full_text,
                                         sources=source_urls, mode=req.mode)
                    if count % 5 == 0:
                        asyncio.create_task(
                            _summarise_and_update(session_id, count)
                        )
                except Exception as _e:
                    logger.warning("chat_save_message_failed", error=str(_e))

        except Exception as exc:
            logger.error("chat_ask_stream_error", error=str(exc))
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        _token_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _save_to_cache(
    run_id:  int,
    question: str,
    answer:   str,
    sources:  List[str],
    mode:     str,
) -> None:
    """Background task: save answer to DB cache + warm Redis L1."""
    from db.chat import cache_save, _hash
    from cache.redis_client import set_cached_answer
    try:
        cache_save(run_id, question, answer, sources, mode=mode)
        set_cached_answer(run_id, _hash(question),
                          {"answer": answer, "sources": sources,
                           "tool_calls_used": [], "cache_hit": "fresh"})
    except Exception as exc:
        logger.warning("cache_save_failed", error=str(exc))


async def _summarise_and_update(session_id: str, msg_count: int) -> None:
    """Background task: generate a rolling conversation summary every 5 messages."""
    from db.chat import load_session_messages, update_window_context
    try:
        messages = load_session_messages(session_id, limit=30)
        if not messages:
            return

        convo = "\n".join(
            f"{m['role'].upper()}: {m['content'][:400]}"
            for m in messages
        )
        summary_prompt = (
            "Summarise this conversation in under 150 words. "
            "Capture: key topics discussed, findings referenced, user's name if mentioned, "
            "user interests, and any follow-up questions. Be concise and factual.\n\n"
            f"Conversation:\n{convo}\n\nSummary:"
        )

        from langchain_openai import ChatOpenAI
        from config.settings import settings
        llm = ChatOpenAI(
            model=settings.openrouter_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0.0,
            max_tokens=200,
        )
        result  = await llm.ainvoke(summary_prompt)
        summary = result.content.strip()
        update_window_context(session_id, summary)
        logger.info("chat_window_context_updated",
                    session_id=session_id, msg_count=msg_count, length=len(summary))

    except Exception as exc:
        logger.warning("summarise_failed", error=str(exc))


def _make_sse_response(answer: str, sources: List[str]) -> StreamingResponse:
    """Wrap a cached answer as a single-shot SSE stream (instant to client)."""
    async def _instant():
        # Stream word by word for consistent UX even on cache hits
        words = answer.split(" ")
        for i, word in enumerate(words):
            token = (word + " ") if i < len(words) - 1 else word
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'done': True, 'sources': sources, 'cache_hit': True})}\n\n"
    return StreamingResponse(
        _instant(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _make_voice_response(response_text: str, source_urls: List[str]) -> dict:
    """Generate ElevenLabs audio and return voice response dict."""
    import base64
    audio_b64: Optional[str] = None
    try:
        from storage.post_run import _resolve_elevenlabs_key
        from voice.generate_voice_digest import (
            generate_audio, _chunk_text, VOICE_PRESETS, _load_config_env, CONFIG_ENV,
        )
        api_key = _resolve_elevenlabs_key()
        if api_key:
            cfg          = _load_config_env(CONFIG_ENV)
            voice_name   = cfg.get("VOICE_PRESET", "rachel")
            audio_format = cfg.get("AUDIO_FORMAT", "mp3_44100_128")
            chunk_size   = int(cfg.get("CHUNK_SIZE", 4500))
            voice_id     = VOICE_PRESETS.get(voice_name, VOICE_PRESETS["rachel"])
            clean_text   = re.sub(r"\*\*(.*?)\*\*", r"\1", response_text)
            clean_text   = re.sub(r"^- ", "", clean_text, flags=re.MULTILINE)
            chunks       = _chunk_text(clean_text.strip(), chunk_size)
            loop         = asyncio.get_running_loop()
            audio_parts  = []
            for chunk in chunks:
                part = await loop.run_in_executor(
                    None,
                    lambda c=chunk: generate_audio(c, voice_id, api_key, audio_format),
                )
                audio_parts.append(part)
            audio_b64 = base64.b64encode(b"".join(audio_parts)).decode("utf-8")
    except Exception as exc:
        logger.warning("chat_ask_tts_failed", error=str(exc))

    return {
        "response":     response_text,
        "audio_base64": audio_b64,
        "sources":      source_urls,
        "mode":         "voice",
    }


# ── Start ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)
