"""Frontier AI Radar — Simple FastAPI entry point."""

import os
import json
import asyncio
import hashlib
import secrets
import uvicorn
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
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
    VALID_AGENTS,
)
from pipeline.scheduler import start_scheduler, stop_scheduler
from db.connection import init_db, get_session
from db.models import Run, Extraction, Finding, Resource, User, Competitor
from config.settings import settings
from agents.base_agent import _build_llm, parse_json_object

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise SQLite DB + start daily cron scheduler."""
    init_db()
    start_scheduler()
    yield
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
    user_id: Optional[int] = None   # subscribed user id (UI trigger)
    email: Optional[str] = None     # ad-hoc email (UI trigger, no subscription needed)
    urls: List[str] = []            # custom URLs for targeted crawling
    url_mode: str = "default"       # "default" | "append" | "custom"

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
    Returns immediately with run_db_id/status=running while pipeline executes in background.
    """
    if req.url_mode == "custom" and not req.urls:
        raise HTTPException(
            status_code=400,
            detail="url_mode is 'custom' but no URLs provided. Pass at least one URL in the 'urls' field.",
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
    run_id = initial_state.get("run_id", "")

    async def _runner_task(state):
        try:
            await execute_prepared_radar(state)
        finally:
            if run_db_id in _background_runs:
                _background_runs.pop(run_db_id, None)

    task = asyncio.create_task(_runner_task(initial_state))
    if run_db_id:
        _background_runs[run_db_id] = task

    return RunResponse(
        run_db_id=run_db_id,
        run_id=run_id,
        status="running",
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
                "Content-Disposition": f'attachment; filename="{filename}"',
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


def _create_jwt(user_id: int, email: str, name: str) -> str:
    """Create a JWT token for the given user."""
    if pyjwt is None:
        # Fallback: simple base64 token (not secure, but works without PyJWT)
        import base64
        payload_str = json.dumps({"user_id": user_id, "email": email, "name": name})
        return base64.urlsafe_b64encode(payload_str.encode()).decode()
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name,
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
            token = _create_jwt(existing.id, existing.email, existing.name)
            return {
                "token": token,
                "user": {"id": existing.id, "name": existing.name, "email": existing.email},
            }

        # Create new user
        user = User(
            name=req.name.strip(),
            email=req.email.strip().lower(),
            password_hash=_hash_password(req.password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        token = _create_jwt(user.id, user.email, user.name)
        return {
            "token": token,
            "user": {"id": user.id, "name": user.name, "email": user.email},
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

        token = _create_jwt(user.id, user.email, user.name)
        return {
            "token": token,
            "user": {"id": user.id, "name": user.name, "email": user.email},
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
        }
    }


# ── Start ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)
