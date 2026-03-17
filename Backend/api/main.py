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
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket
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
    """Startup: initialise DB, run schema migrations, start LiveKit worker.

    Scheduling is handled by Celery beat (external process).
    APScheduler is started only when Celery is not available (dev / single-server).
    """
    init_db()
    from db.chat import ensure_chat_schema
    ensure_chat_schema()

    # Pre-warm the embedding thread pool.
    # init_pool() creates the ThreadPoolExecutor and submits dummy tasks to force
    # thread creation — _thread_initializer loads the SentenceTransformer model
    # in each worker thread right now, not on the first chat request.
    try:
        from core.embedding_executor import init_pool
        init_pool()
        logger.info("embedding_pool_initialized")
    except Exception as _emb_err:
        logger.warning("embedding_pool_init_failed", error=str(_emb_err))

    # Pre-warm the chat LangGraph graph.
    # _get_chat_graph() is normally lazy (first /chat/ask call pays 1-2s to build
    # the graph + establish checkpointer connection). Schedule it as a background
    # task so it runs concurrently with server startup — warm before first request.
    async def _prewarm_chat_graph():
        try:
            await _get_chat_graph()
            logger.info("chat_graph_prewarmed")
        except Exception as _g_err:
            logger.warning("chat_graph_prewarm_failed", error=str(_g_err))
    asyncio.create_task(_prewarm_chat_graph())

    # Start APScheduler only when Celery beat is not running this deployment
    celery_beat_running = False
    try:
        from workers.celery_app import celery_app as _ca
        _ca.control.ping(timeout=1)
        celery_beat_running = True
    except Exception:
        pass

    if not celery_beat_running and _apscheduler_available:
        start_scheduler()

    # ── Start LiveKit voice worker in background (same process, same event loop)
    # Requires LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env
    # Skipped silently if credentials are missing or livekit-agents is not installed.
    _livekit_task = None
    try:
        _lk_url    = settings.livekit_url    or os.environ.get("LIVEKIT_URL", "")
        _lk_key    = settings.livekit_api_key or os.environ.get("LIVEKIT_API_KEY", "")
        _lk_secret = settings.livekit_api_secret or os.environ.get("LIVEKIT_API_SECRET", "")

        if _lk_url and _lk_key and _lk_secret:
            from livekit.agents import WorkerOptions
            from livekit.agents.worker import AgentServer
            from voice_livekit.agent import entrypoint as _lk_entrypoint

            _lk_worker = AgentServer.from_server_options(
                WorkerOptions(
                    entrypoint_fnc = _lk_entrypoint,
                    ws_url         = _lk_url,
                    api_key        = _lk_key,
                    api_secret     = _lk_secret,
                )
            )
            _livekit_task = asyncio.create_task(_lk_worker.run(devmode=True))
            logger.info("livekit_worker_started", url=_lk_url)
        else:
            logger.info("livekit_worker_skipped", reason="credentials not set — voice falls back to WebSocket")
    except ImportError as _lk_imp_err:
        logger.warning("livekit_worker_skipped", reason=str(_lk_imp_err))
    except Exception as _lk_err:
        logger.warning("livekit_worker_failed", error=str(_lk_err))

    yield

    # ── Shutdown
    if _livekit_task and not _livekit_task.done():
        _livekit_task.cancel()
        try:
            await _livekit_task
        except asyncio.CancelledError:
            pass

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
    period: str = "daily"                  # "daily" | "weekly" | "monthly" — used for tab filtering
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
            "period": req.period,
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
        from cache.redis_client import invalidate_digest_cache, invalidate_prefetch_runs
        if run_db_id:
            invalidate_digest_cache(run_db_id)
        invalidate_prefetch_runs()   # bust runs/dashboard cache so fresh data is served
        digest_step = run_digest_pipeline.s(
            run_db_id=run_db_id,
            mode=req.mode,
            since_days=req.since_days,
            email_recipients=email_recipients,
            custom_urls=req.urls or [],
            url_mode=req.url_mode,
        )
        if settings.enable_elevenlabs:
            task_chain = digest_step | generate_audio_task.s() | upload_blob_task.s()
        else:
            task_chain = digest_step | upload_blob_task.s()
        task_chain.apply_async()
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


# ── Login-time prefetch ───────────────────────────────────────────────────────

@app.get("/api/v1/prefetch")
async def prefetch_user_data(user_id: Optional[int] = Query(default=None)):
    """Single endpoint called once at login.

    Runs all expensive read queries in parallel, warms Redis, and returns the
    full payload so the frontend can hydrate its local state in one network round
    trip. Subsequent calls to /runs, /dashboard, /audio/{id}/presets all hit
    Redis (<2 ms) instead of PostgreSQL.

    Cache TTLs: runs/dashboard = 15 min, presets = 1 h.
    """
    from cache.redis_client import (
        get_prefetch_runs, set_prefetch_runs,
        get_prefetch_dashboard, set_prefetch_dashboard,
        get_prefetch_presets, set_prefetch_presets,
    )

    # ── runs ────────────────────────────────────────────────────────────────
    async def _warm_runs() -> list:
        cached = get_prefetch_runs()
        if cached is not None:
            return cached
        data = await get_runs()          # call the existing handler directly
        set_prefetch_runs(data)
        return data

    # ── dashboard ───────────────────────────────────────────────────────────
    async def _warm_dashboard() -> dict:
        cached = get_prefetch_dashboard()
        if cached is not None:
            return cached
        data = await get_dashboard()
        set_prefetch_dashboard(data)
        return data

    runs_result, dashboard_result = await asyncio.gather(
        asyncio.wait_for(_warm_runs(),      timeout=12.0),
        asyncio.wait_for(_warm_dashboard(), timeout=12.0),
        return_exceptions=True,
    )

    # ── presets + popular questions for the latest run ───────────────────────
    from cache.redis_client import (
        get_popular_questions_cached, set_popular_questions_cached,
    )
    latest_run_id: Optional[int] = None
    presets_result  = None
    popular_result  = None

    if isinstance(runs_result, list) and runs_result:
        latest_run_id = runs_result[0].get("run_id")
        if latest_run_id:
            # Presets
            cached_p = get_prefetch_presets(latest_run_id)
            if cached_p is not None:
                presets_result = cached_p
            else:
                try:
                    presets_result = await asyncio.wait_for(
                        list_audio_presets(latest_run_id), timeout=8.0
                    )
                    set_prefetch_presets(latest_run_id, presets_result)
                except Exception:
                    pass

            # Popular questions (quick-prompts chip data)
            cached_q = get_popular_questions_cached(latest_run_id)
            if cached_q is not None:
                popular_result = cached_q
            else:
                try:
                    from db.chat import get_popular_questions
                    db_pop = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: get_popular_questions(latest_run_id, limit=5)
                    )
                    popular_result = [p["question"] for p in db_pop]
                    set_popular_questions_cached(latest_run_id, popular_result)
                except Exception:
                    pass

    return {
        "runs":              runs_result      if not isinstance(runs_result, Exception)      else [],
        "dashboard":         dashboard_result if not isinstance(dashboard_result, Exception) else {},
        "presets":           presets_result,
        "popular_questions": popular_result,
        "latest_run_id":     latest_run_id,
    }


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

        from pathlib import Path as _Path
        filename = f"digest-run-{run_id}.pdf"
        if run.pdf_path:
            filename = _Path(run.pdf_path).name

        # Strategy 1: serve from local pdf_path
        if run.pdf_path and _Path(run.pdf_path).exists():
            pdf_bytes = _Path(run.pdf_path).read_bytes()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{filename}"'},
            )

        # Strategy 2: redirect via Azure Blob SAS URL
        if run.blob_pdf_path:
            try:
                from storage.blob import get_or_refresh_sas, is_configured
                from db.persist import update_pdf_sas
                if is_configured():
                    url, new_entry = get_or_refresh_sas(run_id, "pdf", run.blob_pdf_path)
                    if new_entry:
                        update_pdf_sas(run_id, new_entry)
                    if url:
                        from fastapi.responses import RedirectResponse
                        return RedirectResponse(url=url)
            except Exception:
                pass

        raise HTTPException(
            status_code=404,
            detail=f"Run {run_id} has no PDF available. The pipeline may not have generated a report yet.",
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


def _load_persona_prompt(persona_id: str) -> Optional[str]:
    """Load the digest_system_prompt for the given persona_type slug from DB.

    Returns None if persona not found or DB unavailable.
    """
    if not persona_id:
        return None
    try:
        from db.connection import get_session as db_session
        from sqlalchemy import text
        with db_session() as sess:
            row = sess.execute(text("""
                SELECT digest_system_prompt
                FROM   ai_data_radar.persona_templates
                WHERE  persona_type = :pid AND is_system_default = TRUE
                LIMIT  1
            """), {"pid": persona_id}).fetchone()
        if row and row[0]:
            logger.info("persona_prompt_loaded", persona_id=persona_id, chars=len(row[0]))
            return row[0]
        logger.warning("persona_prompt_not_found", persona_id=persona_id,
                       note="Check ai_data_radar.persona_templates WHERE persona_type=? AND is_system_default=TRUE")
        return None
    except Exception as exc:
        logger.warning("persona_load_failed", persona_id=persona_id, error=str(exc))
        return None


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
    # ── L1: prefetch cache (unfiltered list only) ─────────────────────────
    if not status and not start_date and not end_date:
        from cache.redis_client import get_prefetch_runs
        _cached = get_prefetch_runs()
        if _cached:          # non-empty list only — empty [] falls through to DB
            return _cached

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
            period = extraction_meta.get("period", "daily")

            result.append({
                "run_id": run.id,
                "extraction_id": run.extraction_id,
                "user_id": run.user_id,
                "user_name": user.name if user else None,
                "mode": requested_mode,
                "period": period,
                "status": normalized_status,
                "time_taken": run.time_taken,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": _finished_at_iso(run),
                "recipient_emails": recipient_emails,
                "custom_urls": custom_urls,
                "agent_statuses": _serialize_agent_statuses(selected_agents, findings_by_agent, normalized_status),
                "findings_count": len(findings_out),
                "pdf_available": bool(run.blob_pdf_path or run.pdf_path),
                "pdf_path": run.pdf_path,
                "extraction_metadata": extraction_meta,
                "findings": findings_out,
                "resources": resources_out,
            })

    # ── Write-through: warm Redis for next request (only non-empty results) ─
    if not status and not start_date and not end_date and result:
        from cache.redis_client import set_prefetch_runs
        set_prefetch_runs(result)

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
            "pdf_available": bool(run.blob_pdf_path or run.pdf_path),
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
    # ── L1: prefetch cache ────────────────────────────────────────────────
    from cache.redis_client import get_prefetch_dashboard, set_prefetch_dashboard
    _cached = get_prefetch_dashboard()
    if _cached and _cached.get("last_run") is not None:   # only serve if it has real data
        return _cached

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

        result = {
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
        set_prefetch_dashboard(result)
        return result


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

        url, new_entry = get_or_refresh_sas(run_id, type, blob_path)

        if not url:
            raise HTTPException(status_code=500, detail="Failed to generate secure URL")

        # Persist the refreshed SAS to run_asset_cache if it was regenerated
        if new_entry is not None:
            from db.persist import update_pdf_sas
            update_pdf_sas(run_id, new_entry)

        return {"url": url, "asset_type": type}


# ── On-Demand Audio Book Generation ──────────────────────────────────────────

@app.get("/api/v1/audio/{run_id}/presets")
async def list_audio_presets(run_id: int):
    """Return all active voice presets + which ones have audio for this run.

    Response:
      { "script_ready": bool,
        "presets": [{ "id", "label", "gender", "style", "is_ready", "audio_url" }, ...] }
    """
    # ── L1: prefetch cache ────────────────────────────────────────────────
    from cache.redis_client import get_prefetch_presets, set_prefetch_presets
    _cached = get_prefetch_presets(run_id)
    if _cached and _cached.get("presets") is not None:   # only serve if it has real data
        return _cached

    from db.models import VoicePreset, RunAudioPreset
    from storage.blob import is_configured, get_or_refresh_preset_sas
    from db.persist import update_audio_preset_sas

    with get_session() as session:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        script_ready: bool = bool(run.audio_script_blob_path)

        # Load generated presets from run_audio_presets table (normalized)
        audio_preset_rows = (
            session.query(RunAudioPreset)
            .filter_by(run_id=run_id, is_ready=True)
            .all()
        )
        preset_blob_map: dict = {row.preset_id: row.blob_path for row in audio_preset_rows}

        presets_db = session.query(VoicePreset).filter(VoicePreset.is_active == True).all()
        preset_list = []
        for p in presets_db:
            blob_path = preset_blob_map.get(p.id)
            is_ready  = bool(blob_path)
            audio_url: Optional[str] = None

            if is_ready:
                if is_configured() and blob_path and not blob_path.startswith("/") and ":\\" not in blob_path:
                    url, new_entry = get_or_refresh_preset_sas(run_id, p.id, blob_path)
                    if new_entry:
                        update_audio_preset_sas(run_id, p.id, new_entry)
                    audio_url = url
                if not audio_url:
                    audio_url = f"/api/audio/{run_id}?preset_id={p.id}"

            preset_list.append({
                "id":        p.id,
                "label":     p.label,
                "gender":    p.gender,
                "style":     p.style,
                "is_ready":  is_ready,
                "audio_url": audio_url,
            })

    result = {"script_ready": script_ready, "presets": preset_list}
    set_prefetch_presets(run_id, result)
    return result


@app.post("/api/v1/audio/{run_id}/generate")
async def generate_audio_on_demand(
    run_id:    int,
    preset_id: str = Query(..., description="Voice preset ID, e.g. rachel_professional"),
):
    """Generate audio for one voice preset using the stored audio script.

    Flow:
      1. Load audio script from runs.audio_script_blob_path
      2. Fetch voice_id from voice_presets table
      3. ElevenLabs TTS (batched) on the script
      4. Save MP3 locally + upload to blob
      5. Update runs.audio_presets_paths JSON
      6. Return audio_url for immediate playback
    """
    from pathlib import Path as _Path
    from db.models import VoicePreset
    from storage.blob import is_configured, blob_path_for_run, upload_file, download_text
    from storage.post_run import _resolve_elevenlabs_key
    from voice.generate_voice_digest import tts_from_script, _load_config_env, CONFIG_ENV
    from db.persist import update_audio_preset_path

    with get_session() as session:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        preset = session.get(VoicePreset, preset_id)
        if not preset:
            raise HTTPException(status_code=404, detail=f"Voice preset '{preset_id}' not found")
        script_path_or_blob: Optional[str] = run.audio_script_blob_path
        started_at_dt = run.started_at

        # Check run_audio_presets table — already generated?
        from db.models import RunAudioPreset
        existing_preset = (
            session.query(RunAudioPreset)
            .filter_by(run_id=run_id, preset_id=preset_id, is_ready=True)
            .first()
        )

    # Return cached immediately if already generated
    if existing_preset:
        return {"status": "cached", "preset_id": preset_id,
                "audio_url": f"/api/audio/{run_id}?preset_id={preset_id}"}

    if not script_path_or_blob:
        raise HTTPException(
            status_code=404,
            detail="Audio script not ready for this run yet. "
                   "The post-pipeline processing may still be running.",
        )

    # Read script from blob or local path
    loop = asyncio.get_event_loop()
    script_text = ""
    if is_configured() and not script_path_or_blob.startswith("/") and ":\\" not in script_path_or_blob:
        try:
            script_text = await loop.run_in_executor(None, download_text, script_path_or_blob)
        except Exception as exc:
            logger.warning("audio_generate: blob read failed, trying local", error=str(exc))
    if not script_text:
        local = _Path(script_path_or_blob)
        if local.exists():
            script_text = local.read_text(encoding="utf-8")
        else:
            raise HTTPException(status_code=404, detail="Audio script file not accessible.")

    api_key = _resolve_elevenlabs_key()
    if not api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured.")

    cfg          = _load_config_env(CONFIG_ENV)
    audio_format = cfg.get("AUDIO_FORMAT", "mp3_44100_128")
    chunk_size   = int(cfg.get("CHUNK_SIZE", 4500))

    date_str = started_at_dt.strftime("%Y%m%d-%H%M%S") if started_at_dt else \
               datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    audio_dir = _Path(__file__).resolve().parent.parent / "data" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_path = audio_dir / f"digest-{date_str}_{preset_id}.mp3"

    logger.info("audio_generate: starting TTS", run_id=run_id, preset=preset_id,
                words=len(script_text.split()))

    try:
        await loop.run_in_executor(
            None,
            lambda: tts_from_script(
                script_text=script_text,
                voice_id=preset.voice_id,
                api_key=api_key,
                out_path=out_path,
                audio_format=audio_format,
                chunk_size=chunk_size,
            ),
        )
    except Exception as exc:
        logger.error("audio_generate: TTS failed", run_id=run_id, preset=preset_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Audio generation failed: {exc}")

    # Upload to blob + update DB
    stored_path: str = str(out_path)
    if is_configured():
        try:
            bp = blob_path_for_run(date_str, f"presets/{preset_id}.mp3")
            upload_file(out_path, bp)
            stored_path = bp
        except Exception as exc:
            logger.warning("audio_generate: blob upload failed, keeping local", error=str(exc))

    update_audio_preset_path(run_id, preset_id, stored_path)
    # Bust the presets cache so the next fetch picks up the new is_ready=True state
    from cache.redis_client import invalidate_prefetch_presets
    invalidate_prefetch_presets(run_id)
    logger.info("audio_generate: done", run_id=run_id, preset=preset_id)
    return {"status": "done", "preset_id": preset_id,
            "audio_url": f"/api/audio/{run_id}?preset_id={preset_id}"}


# ── Persona Templates ────────────────────────────────────────────────────────

@app.get("/api/v1/personas")
async def get_personas():
    """Return all public system persona templates for the UI.

    IMPORTANT: digest_system_prompt is NOT returned here — it is loaded
    server-side only when building LLM calls. The frontend receives only
    the display fields needed to render the persona selector.
    """
    try:
        from db.connection import get_session as db_session
        from sqlalchemy import text
        with db_session() as sess:
            rows = sess.execute(text("""
                SELECT persona_type, name, description, suggested_questions
                FROM   ai_data_radar.persona_templates
                WHERE  visibility = 'public' AND is_system_default = TRUE
                ORDER  BY created_at ASC
            """)).fetchall()
        return [
            {
                "id":          r[0],
                "label":       r[1],
                "description": r[2],
                "prompts":     r[3] if isinstance(r[3], list) else [],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("personas_load_failed", error=str(exc))
        return []


# ── LiveKit Voice Token ───────────────────────────────────────────────────────

@app.get("/api/v1/voice/livekit-token")
async def get_livekit_token(
    run_id:     int           = Query(..., description="Digest run ID"),
    user_id:    Optional[int] = Query(default=None),
    voice:      str           = Query(default="rachel", description="Voice preset: rachel | adam | elli"),
    persona_id: Optional[str] = Query(default=None, description="Persona type slug"),
):
    """
    Generate a LiveKit access token for the client to join a voice room.

    Room name convention: "radar-{run_id}" (or "radar-{run_id}-{user_id}" when user_id provided).
    Room metadata is set to the voice preset so the agent can pick the correct ElevenLabs voice.

    Requires environment variables:
        LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL

    Returns:
        {token: str, ws_url: str, room: str}
    """
    livekit_api_key    = settings.livekit_api_key    or os.environ.get("LIVEKIT_API_KEY", "")
    livekit_api_secret = settings.livekit_api_secret or os.environ.get("LIVEKIT_API_SECRET", "")
    livekit_url        = settings.livekit_url        or os.environ.get("LIVEKIT_URL", "")

    if not all([livekit_api_key, livekit_api_secret, livekit_url]):
        raise HTTPException(
            status_code=503,
            detail="LiveKit not configured. Set LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL.",
        )

    try:
        from livekit.api import AccessToken, VideoGrants  # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="livekit-api package not installed. Run: pip install livekit-api",
        )

    room_name     = f"radar-{run_id}" + (f"-{user_id}" if user_id else "")
    identity      = f"user-{user_id or 0}-{run_id}"
    room_metadata = json.dumps({"voice": voice, "persona_id": persona_id or ""})

    # Create (or update) the LiveKit room with metadata via the server API.
    # This is the correct pattern: ctx.room.metadata in the agent reads ROOM-level
    # metadata, which must be set server-side — not via the participant's token.
    # AccessToken.with_metadata() sets participant metadata (different thing).
    try:
        from livekit import api as _lk_server
        async with _lk_server.LiveKitAPI(
            url=livekit_url,
            api_key=livekit_api_key,
            api_secret=livekit_api_secret,
        ) as _lk_api:
            try:
                await _lk_api.room.create_room(
                    _lk_server.CreateRoomRequest(
                        name=room_name,
                        metadata=room_metadata,
                    )
                )
            except Exception:
                # Room already exists — update its metadata
                await _lk_api.room.update_room_metadata(
                    _lk_server.UpdateRoomMetadataRequest(
                        room=room_name,
                        metadata=room_metadata,
                    )
                )
    except Exception as _room_err:
        logger.warning("livekit_room_metadata_failed", error=str(_room_err),
                       note="agent will fall back to participant metadata")

    token = (
        AccessToken(livekit_api_key, livekit_api_secret)
        .with_identity(identity)
        .with_name(f"User {user_id or 'anonymous'}")
        .with_grants(VideoGrants(room_join=True, room=room_name))
        .with_metadata(room_metadata)   # also set on participant as redundant fallback
        .to_jwt()
    )

    logger.info("livekit_token: issued", room=room_name, user=identity, voice=voice,
                persona_id=persona_id or "")
    return {"token": token, "ws_url": livekit_url, "room": room_name}


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
    from sqlalchemy.exc import IntegrityError

    try:
        info       = get_or_create_session(run_id=run_id, user_id=user_id)
        session_id = info["session_id"]
        is_new     = info.get("is_new", False)
        messages   = load_voice_history(session_id)
    except IntegrityError:
        # run_id doesn't exist in the runs table yet — return empty history
        logger.warning("voice_history_run_not_found", run_id=run_id)
        return {"session_id": None, "is_new": True, "messages": []}

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
    run_id:     int           = Query(...),
    user_id:    Optional[int] = Query(default=None),
    persona_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
):
    """
    Get-or-create a chat session and return the most recent messages.

    If session_id is provided (user clicked a specific thread), load messages
    directly from that thread — do NOT fall back to most-recently-active session.
    """
    from cache.redis_client import (
        get_session_meta, set_session_meta,
        rget_messages, rwarm_messages,
        get_popular_questions_cached, set_popular_questions_cached,
    )
    from db.chat import get_or_create_session, load_session_messages, get_popular_questions

    _persona_id = persona_id or ''
    messages: list = []
    is_new = False

    # ── When a specific thread_id is provided, use it directly ────────────
    if session_id:
        cached_msgs = rget_messages(session_id)
        if cached_msgs is not None:
            messages = cached_msgs[-50:]
        else:
            db_messages = load_session_messages(session_id, limit=50)
            if db_messages:
                messages = db_messages
                rwarm_messages(session_id, db_messages)

    else:
        # ── No specific thread — get-or-create for (user, run, persona) ───
        if user_id:
            meta = get_session_meta(user_id, run_id, _persona_id)
            if meta:
                session_id = meta["session_id"]
            else:
                session_info = get_or_create_session(run_id=run_id, user_id=user_id, persona_id=_persona_id)
                session_id   = session_info["session_id"]
                is_new       = session_info["is_new"]
                set_session_meta(user_id, run_id, _persona_id, {"session_id": session_id, "is_new": is_new})
        else:
            session_info = get_or_create_session(run_id=run_id, user_id=None, persona_id=_persona_id)
            session_id   = session_info["session_id"]
            is_new       = session_info["is_new"]

        # Load messages for resolved session
        if session_id and not is_new:
            cached_msgs = rget_messages(session_id)
            if cached_msgs is not None:
                messages = cached_msgs[-10:]
            else:
                db_messages = load_session_messages(session_id, limit=10)
                if db_messages:
                    messages = db_messages
                    rwarm_messages(session_id, db_messages)

    # ── L3: popular questions from Redis ──────────────────────────────────
    popular = get_popular_questions_cached(run_id)
    if popular is None:
        db_pop  = get_popular_questions(run_id=run_id, limit=5)
        popular = [p["question"] for p in db_pop]
        set_popular_questions_cached(run_id, popular)

    return {
        "session_id":        session_id,
        "is_new":            is_new,
        "persona_id":        _persona_id,
        "message_count":     len(messages),
        "messages":          messages,
        "popular_questions": popular,
    }


@app.get("/api/v1/chat/sessions")
async def get_chat_sessions_for_persona(
    user_id:    int           = Query(...),
    persona_id: Optional[str] = Query(default=None),
    run_id:     Optional[int] = Query(default=None),
    limit:      int           = Query(default=10),
):
    """Return recent sessions for (user_id, persona_id), optionally scoped to run_id."""
    from db.chat import get_sessions_for_persona
    return get_sessions_for_persona(user_id, persona_id or '', run_id, limit)


@app.get("/api/v1/chat/threads")
async def get_chat_threads(
    user_id:    int = Query(...),
    persona_id: str = Query(...),
    run_id:     int = Query(...),
    limit:      int = Query(default=20),
):
    """List chat threads (sessions) for a user+persona+run, newest first."""
    from db.chat import list_threads
    threads = list_threads(user_id=user_id, persona_id=persona_id, run_id=run_id, limit=limit)
    return {"threads": threads}


@app.post("/api/v1/chat/threads/new")
async def create_new_chat_thread(
    run_id:     int = Body(...),
    user_id:    int = Body(...),
    persona_id: str = Body(...),
):
    """Create a new chat thread (fresh session) for this user+persona+run."""
    from db.chat import create_new_thread
    thread = create_new_thread(run_id=run_id, user_id=user_id, persona_id=persona_id)
    return thread


# ── Thread title auto-generation helper ───────────────────────────────────

async def _set_thread_title(session_id: str, first_message: str) -> None:
    """Auto-generate thread title from first user message."""
    try:
        from db.chat import update_thread_title
        title = first_message.strip()[:60]
        if len(first_message.strip()) > 60:
            title += "\u2026"
        update_thread_title(session_id, title)
    except Exception:
        pass


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
    persona_id: Optional[str] = None       # persona_type slug (e.g. "sales_leader")


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

    _persona_id = req.persona_id or ''
    session_id = req.session_id
    if not session_id:
        info       = get_or_create_session(
            run_id=run_id_int, user_id=req.user_id, persona_id=_persona_id
        )
        session_id = info["session_id"]

    # ── Load conversation context — strictly scoped to this thread ────────
    from db.chat import get_recent_messages, get_session_info
    session_info   = get_session_info(session_id)
    window_context = session_info["window_context"]
    prior_messages = get_recent_messages(session_id, limit=10)
    has_history    = bool(prior_messages)

    # ── L1/L2/L3 cache — SKIP when conversation history exists ────────────
    # Cache keys are global per (run_id, question_hash) — they have no session
    # context. A cached "what is my name" answer from session A must never be
    # served to session B. Any question that can reference prior turns is
    # context-dependent and must go through the LLM every time.
    # Also bypass ALL caches when a persona is selected — persona responses are
    # personalized and must never be served from a generic (non-persona) cache entry.
    q_hash = _hash(req.message)
    if not has_history and not _persona_id:
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
    elif has_history:
        logger.info("chat_cache_bypass", reason="conversation_history_exists",
                    session=session_id, prior_count=len(prior_messages))
    else:
        logger.info("chat_cache_bypass", reason="persona_selected",
                    session=session_id, persona_id=_persona_id)

    # ── L4: Unified LangGraph radar graph → chat_agent node ──────────────
    radar_graph = await _get_chat_graph()
    if not radar_graph:
        raise HTTPException(status_code=503, detail="Chat graph not available")

    # Load persona system prompt if persona selected
    persona_prompt: Optional[str] = None
    if req.persona_id:
        persona_prompt = _load_persona_prompt(req.persona_id)

    chat_state   = create_chat_initial_state(
        run_id_int, req.message, session_id, req.mode,
        prior_messages=prior_messages,
        window_context=window_context,
        persona_system_prompt=persona_prompt,
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
        from db.chat import save_message, get_last_message_id, embed_message_background
        try:
            save_message(session_id, "user", req.message, mode=req.mode)
            user_msg_id = get_last_message_id(session_id)
            asyncio.create_task(asyncio.to_thread(
                embed_message_background,
                session_id, user_msg_id, "user", req.message,
                req.user_id, _persona_id, run_id_int,
            ))
            count = save_message(session_id, "assistant", response_text, mode=req.mode)
            asst_msg_id = get_last_message_id(session_id)
            asyncio.create_task(asyncio.to_thread(
                embed_message_background,
                session_id, asst_msg_id, "assistant", response_text,
                req.user_id, _persona_id, run_id_int,
            ))
            if count % 5 == 0:
                asyncio.create_task(_summarise_and_update(session_id, count))
            # Auto-generate thread title from first user message
            if session_info.get("message_count", 0) == 0:
                asyncio.create_task(_set_thread_title(session_id, req.message))
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
                from db.chat import (
                    save_message, load_session_messages, update_window_context,
                    get_last_message_id, embed_message_background,
                )
                try:
                    save_message(session_id, "user", req.message, mode=req.mode)
                    user_msg_id = get_last_message_id(session_id)
                    asyncio.create_task(asyncio.to_thread(
                        embed_message_background,
                        session_id, user_msg_id, "user", req.message,
                        req.user_id, _persona_id, run_id_int,
                    ))
                    count = save_message(session_id, "assistant", full_text,
                                         sources=source_urls, mode=req.mode)
                    asst_msg_id = get_last_message_id(session_id)
                    asyncio.create_task(asyncio.to_thread(
                        embed_message_background,
                        session_id, asst_msg_id, "assistant", full_text,
                        req.user_id, _persona_id, run_id_int,
                    ))
                    if count % 5 == 0:
                        asyncio.create_task(
                            _summarise_and_update(session_id, count)
                        )
                    # Auto-generate thread title from first user message
                    if session_info.get("message_count", 0) == 0:
                        asyncio.create_task(_set_thread_title(session_id, req.message))
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
    if not settings.enable_elevenlabs:
        logger.info("chat_ask_tts_skip", reason="elevenlabs_disabled")
        return {"response": response_text, "audio_base64": None, "sources": source_urls, "mode": "voice"}
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


def _cache_digest_sections_background(run_id: int) -> None:
    """Load digest findings from DB, group by agent into sections, and cache embeddings.

    Designed to run in a thread via asyncio.to_thread() — never raises.
    """
    try:
        from db.chat import cache_digest_for_run
        from db.connection import get_session as db_session
        from sqlalchemy import text

        with db_session() as session:
            rows = session.execute(text("""
                SELECT f.agent_name, f.metadata_
                FROM   ai_data_radar.findings f
                JOIN   ai_data_radar.extractions e ON e.id = f.extraction_id
                JOIN   ai_data_radar.runs r ON r.extraction_id = e.id
                WHERE  r.id = :rid
                ORDER  BY f.agent_name, f.id
            """), {"rid": run_id}).fetchall()

        if not rows:
            # Fallback: try ai_data_radar schema
            with db_session() as session:
                rows = session.execute(text("""
                    SELECT f.agent_name, f.metadata_
                    FROM   ai_data_radar.findings f
                    JOIN   ai_data_radar.extractions e ON e.id = f.extraction_id
                    JOIN   ai_data_radar.runs r ON r.extraction_id = e.id
                    WHERE  r.id = :rid
                    ORDER  BY f.agent_name, f.id
                """), {"rid": run_id}).fetchall()

        if not rows:
            logger.warning("cache_digest_sections_no_findings", run_id=run_id)
            return

        import json as _json
        from collections import defaultdict
        by_agent: dict = defaultdict(list)
        for agent_name, metadata_ in rows:
            meta = _json.loads(metadata_) if isinstance(metadata_, str) else (metadata_ or {})
            title   = meta.get("title", "")
            summary = meta.get("what_changed") or meta.get("summary", "")
            why     = meta.get("why_it_matters", "")
            piece = title
            if summary:
                piece += f". {summary}"
            if why:
                piece += f" Why it matters: {why}"
            by_agent[agent_name].append(piece.strip())

        sections = []
        for agent_name, pieces in by_agent.items():
            content = "\n".join(p for p in pieces if p)
            if content:
                sections.append({"section": agent_name, "content": content})

        cache_digest_for_run(run_id, sections)

    except Exception as exc:
        logger.warning("cache_digest_sections_background_failed", run_id=run_id, error=str(exc))


@app.post("/api/v1/digest/{run_id}/cache")
async def cache_digest(run_id: int):
    """Trigger background embedding of digest sections for this run_id."""
    asyncio.create_task(asyncio.to_thread(_cache_digest_sections_background, run_id))
    return {"status": "queued", "run_id": run_id}


# ── Start ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port,
                loop="asyncio" if sys.platform == "win32" else "auto")
