"""Source management routes."""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel

router = APIRouter()


class SourceCreate(BaseModel):
    """Source creation model."""
    url: str
    agent_type: str
    config: Dict[str, Any] = {}


class SourceResponse(BaseModel):
    """Source response model."""
    id: str
    url: str
    agent_type: str
    config: Dict[str, Any]


# STUB: Team will implement real source storage
_sources: List[Dict[str, Any]] = []


@router.get("/sources", response_model=List[SourceResponse])
async def list_sources():
    """List all configured sources."""
    return _sources


@router.post("/sources", response_model=SourceResponse)
async def create_source(source: SourceCreate):
    """Create a new source."""
    # STUB: Team will implement real source creation
    source_dict = {
        "id": f"source-{len(_sources)}",
        "url": source.url,
        "agent_type": source.agent_type,
        "config": source.config,
    }
    _sources.append(source_dict)
    return source_dict


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str):
    """Get a specific source."""
    source = next((s for s in _sources if s["id"] == source_id), None)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    """Delete a source."""
    global _sources
    _sources = [s for s in _sources if s["id"] != source_id]
    return {"message": "Source deleted"}
