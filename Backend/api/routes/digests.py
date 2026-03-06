"""Digest management routes."""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter()


@router.get("/digests", response_model=List[Dict[str, Any]])
async def list_digests():
    """List all generated digests."""
    # STUB: Team will implement real digest listing
    reports_dir = Path("data/reports")
    if not reports_dir.exists():
        return []
    
    digests = []
    for pdf_file in reports_dir.glob("*.pdf"):
        digests.append({
            "id": pdf_file.stem,
            "path": str(pdf_file),
            "created": pdf_file.stat().st_mtime,
        })
    return digests


@router.get("/digests/{digest_id}/download")
async def download_digest(digest_id: str):
    """Download a digest PDF."""
    # STUB: Team will implement real digest download
    pdf_path = Path(f"data/reports/{digest_id}.pdf")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Digest not found")
    return FileResponse(pdf_path, media_type="application/pdf")
