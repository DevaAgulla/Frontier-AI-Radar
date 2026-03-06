"""Long-term memory operations (JSON file storage)."""

import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime
from memory.schemas import LongTermMemory, ContentHash, EntityProfile, RunHistory
from config.settings import settings


def _get_memory_file() -> Path:
    """Get path to long-term memory JSON file."""
    memory_dir = settings.long_term_memory_path
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir / "memory.json"


def _load_memory() -> LongTermMemory:
    """Load long-term memory from JSON file."""
    memory_file = _get_memory_file()
    if not memory_file.exists():
        return {
            "seen_arxiv_ids": [],
            "seen_urls": [],
            "content_hashes": [],
            "entity_profiles": [],
            "run_history": [],
            "trend_baselines": {},
        }
    with open(memory_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_memory(memory: LongTermMemory) -> None:
    """Save long-term memory to JSON file."""
    memory_file = _get_memory_file()
    with open(memory_file, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


def read_memory(key: str, default: Any = None) -> Any:
    """Read a value from long-term memory."""
    memory = _load_memory()
    return memory.get(key, default)


def write_memory(key: str, value: Any) -> None:
    """Write a value to long-term memory."""
    memory = _load_memory()
    memory[key] = value
    _save_memory(memory)


def add_seen_arxiv_id(arxiv_id: str) -> None:
    """Mark an arXiv ID as seen."""
    memory = _load_memory()
    if arxiv_id not in memory["seen_arxiv_ids"]:
        memory["seen_arxiv_ids"].append(arxiv_id)
        _save_memory(memory)


def add_content_hash(url: str, content_hash: str, finding_id: str) -> None:
    """Add or update a content hash."""
    memory = _load_memory()
    now = datetime.utcnow().isoformat()

    # Find existing hash
    existing = next((h for h in memory["content_hashes"] if h["url"] == url), None)
    if existing:
        existing["last_seen"] = now
        if finding_id not in existing["finding_ids"]:
            existing["finding_ids"].append(finding_id)
    else:
        memory["content_hashes"].append(
            {
                "url": url,
                "hash": content_hash,
                "first_seen": now,
                "last_seen": now,
                "finding_ids": [finding_id],
            }
        )
    _save_memory(memory)


def add_entity_profile(entity: EntityProfile) -> None:
    """Add or update an entity profile."""
    memory = _load_memory()
    existing = next((e for e in memory["entity_profiles"] if e["id"] == entity["id"]), None)
    if existing:
        existing.update(entity)
        existing["last_updated"] = datetime.utcnow().isoformat()
    else:
        memory["entity_profiles"].append(entity)
    _save_memory(memory)


def add_run_history(run: RunHistory) -> None:
    """Add a run to history."""
    memory = _load_memory()
    memory["run_history"].append(run)
    _save_memory(memory)
