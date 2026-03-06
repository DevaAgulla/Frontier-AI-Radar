"""Run management routes — kept for reference / future use."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from pipeline.runner import run_radar, VALID_AGENTS

import structlog

logger = structlog.get_logger()
router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────────

class RunRequest(BaseModel):
    """POST body for triggering a radar run."""

    mode: str = "full"
    since_days: int = 1
    email_recipients: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v == "full":
            return v
        parts = [p.strip() for p in v.split(",")]
        invalid = [p for p in parts if p not in VALID_AGENTS]
        if invalid:
            raise ValueError(
                f"Unknown agent(s): {', '.join(invalid)}. "
                f"Valid: {', '.join(sorted(VALID_AGENTS))} or 'full'."
            )
        return v

    @field_validator("since_days")
    @classmethod
    def validate_since_days(cls, v: int) -> int:
        if v < 1 or v > 30:
            raise ValueError("since_days must be between 1 and 30.")
        return v


class RunSummary(BaseModel):
    run_id: str
    status: str
    mode: str
    started_at: str
    finished_at: Optional[str] = None


class RunDetail(BaseModel):
    run_id: str
    status: str
    mode: str
    since_days: int
    started_at: str
    finished_at: Optional[str] = None
    findings_count: int = 0
    errors_count: int = 0
    errors: List[Dict[str, Any]] = []
    email_status: str = ""
    pdf_path: str = ""


# ── In-Memory Run Store ──────────────────────────────────────────────────

_runs: Dict[str, Dict[str, Any]] = {}


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/runs", response_model=RunDetail)
async def trigger_run(request: RunRequest):
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    config = request.config or {}
    if request.email_recipients:
        config["email_recipients_override"] = request.email_recipients
    if request.urls:
        config["user_urls"] = request.urls

    run_record: Dict[str, Any] = {
        "run_id": run_id, "status": "running", "mode": request.mode,
        "since_days": request.since_days, "started_at": started_at,
        "finished_at": None, "findings_count": 0, "errors_count": 0,
        "errors": [], "email_status": "", "pdf_path": "",
    }
    _runs[run_id] = run_record

    try:
        state = await run_radar(mode=request.mode, since_days=request.since_days, config=config)
        run_record.update({
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "findings_count": len(state.get("ranked_findings", [])),
            "errors_count": len(state.get("errors", [])),
            "errors": state.get("errors", []),
            "email_status": state.get("email_status", ""),
            "pdf_path": state.get("pdf_path", ""),
        })
    except Exception as e:
        logger.exception("API: run failed", run_id=run_id, error=str(e))
        run_record.update({
            "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "errors": [{"agent_name": "pipeline", "error_type": type(e).__name__,
                        "error_message": str(e)}],
            "errors_count": 1,
        })

    return RunDetail(**run_record)


@router.get("/runs", response_model=List[RunSummary])
async def list_runs():
    return [RunSummary(**{k: r[k] for k in ["run_id","status","mode","started_at","finished_at"]}) for r in reversed(list(_runs.values()))]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return RunDetail(**run)


@router.get("/runs/{run_id}/pdf")
async def download_run_pdf(run_id: str):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    if run["status"] == "running":
        raise HTTPException(status_code=409, detail="Run still in progress.")
    pdf_path = run.get("pdf_path", "")
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No PDF generated.")
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk.")
    return FileResponse(pdf_file, media_type="application/pdf", filename=pdf_file.name)
