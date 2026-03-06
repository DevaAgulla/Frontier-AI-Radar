"""Findings query routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

router = APIRouter()


class FindingResponse(BaseModel):
    """Finding response model."""
    id: str
    title: str
    source_url: str
    agent_source: str
    impact_score: float


@router.get("/findings", response_model=List[FindingResponse])
async def list_findings(
    agent_source: Optional[str] = Query(None, description="Filter by agent source"),
    min_impact: Optional[float] = Query(None, description="Minimum impact score"),
    limit: int = Query(100, description="Maximum number of findings"),
):
    """List findings with optional filters."""
    # STUB: Team will implement real findings storage/query
    # For now, return empty list
    return []


@router.get("/findings/{finding_id}", response_model=Dict[str, Any])
async def get_finding(finding_id: str):
    """Get a specific finding."""
    # STUB: Team will implement real finding retrieval
    raise HTTPException(status_code=404, detail="Finding not found")
