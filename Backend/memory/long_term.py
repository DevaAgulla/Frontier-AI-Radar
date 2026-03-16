"""Long-term memory operations (PostgreSQL memory_kv table in ai_radar schema).

Replaces the old JSON file store. All public function signatures are identical
so no other code changes are needed.

Table: ai_radar.memory_kv
  key        VARCHAR(500) PRIMARY KEY
  value      JSONB
  updated_at TIMESTAMP
"""

import json
from typing import Any, Optional
from datetime import datetime

from memory.schemas import EntityProfile, RunHistory


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_kv(key: str) -> Any:
    """Read a JSONB value from memory_kv by key. Returns None if missing."""
    from db.connection import get_engine
    from sqlalchemy import text
    try:
        with get_engine().connect() as conn:
            result = conn.execute(
                text("SELECT value FROM memory_kv WHERE key = :key"),
                {"key": key},
            )
            row = result.fetchone()
            # psycopg2 deserialises JSONB → Python object automatically
            return row[0] if row is not None else None
    except Exception:
        return None


def _write_kv(key: str, value: Any) -> None:
    """Upsert a Python value as JSONB into memory_kv."""
    from db.connection import get_engine
    from sqlalchemy import text
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO memory_kv (key, value, updated_at)
                VALUES (:key, CAST(:value AS jsonb), NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = CAST(:value AS jsonb), updated_at = NOW()
            """), {"key": key, "value": json.dumps(value)})
    except Exception:
        pass  # memory writes are non-critical — never crash the pipeline


# ---------------------------------------------------------------------------
# Public API  (signatures identical to the old JSON-file version)
# ---------------------------------------------------------------------------

def read_memory(key: str, default: Any = None) -> Any:
    """Read a value from long-term memory."""
    val = _read_kv(key)
    return val if val is not None else default


def write_memory(key: str, value: Any) -> None:
    """Write a value to long-term memory."""
    _write_kv(key, value)


def add_seen_arxiv_id(arxiv_id: str) -> None:
    """Mark an arXiv ID as seen (idempotent)."""
    seen = read_memory("seen_arxiv_ids", [])
    if arxiv_id not in seen:
        seen.append(arxiv_id)
        write_memory("seen_arxiv_ids", seen)


def add_content_hash(url: str, content_hash: str, finding_id: str) -> None:
    """Add or update a content hash."""
    hashes = read_memory("content_hashes", [])
    now = datetime.utcnow().isoformat()
    existing = next((h for h in hashes if h["url"] == url), None)
    if existing:
        existing["last_seen"] = now
        if finding_id not in existing["finding_ids"]:
            existing["finding_ids"].append(finding_id)
    else:
        hashes.append({
            "url": url,
            "hash": content_hash,
            "first_seen": now,
            "last_seen": now,
            "finding_ids": [finding_id],
        })
    write_memory("content_hashes", hashes)


def add_entity_profile(entity: EntityProfile) -> None:
    """Add or update an entity profile."""
    profiles = read_memory("entity_profiles", [])
    existing = next((e for e in profiles if e["id"] == entity["id"]), None)
    if existing:
        existing.update(entity)
        existing["last_updated"] = datetime.utcnow().isoformat()
    else:
        profiles.append(entity)
    write_memory("entity_profiles", profiles)


def add_run_history(run: RunHistory) -> None:
    """Add a run to history."""
    history = read_memory("run_history", [])
    history.append(run)
    write_memory("run_history", history)
