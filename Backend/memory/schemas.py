"""Memory data models."""

from typing import TypedDict, Optional
from datetime import datetime


class EntityProfile(TypedDict):
    """Profile for a tracked entity (organization, model, benchmark)."""

    id: str
    name: str
    type: str  # "organization" | "model" | "benchmark" | "dataset"
    description: str
    first_seen: str  # ISO format
    last_updated: str  # ISO format
    metadata: dict  # additional fields


class ContentHash(TypedDict):
    """Content hash for deduplication."""

    url: str
    hash: str  # SHA256 hash of content
    first_seen: str  # ISO format
    last_seen: str  # ISO format
    finding_ids: list[str]  # findings that referenced this content


class RunHistory(TypedDict):
    """Historical record of a run."""

    run_id: str
    timestamp: str  # ISO format
    mode: str
    findings_count: int
    digest_path: Optional[str]
    errors: list[str]


class LongTermMemory(TypedDict):
    """Structure of long-term memory JSON file."""

    seen_arxiv_ids: list[str]
    seen_urls: list[str]
    content_hashes: list[ContentHash]
    entity_profiles: list[EntityProfile]
    run_history: list[RunHistory]
    trend_baselines: dict  # baseline metrics for trend detection
