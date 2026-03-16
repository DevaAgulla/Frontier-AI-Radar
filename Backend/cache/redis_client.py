"""
Redis client singleton for Frontier AI Radar.
Uses Azure Cache for Redis (rediss:// TLS).

All operations degrade gracefully — if Redis is down or unavailable,
every function returns None/no-ops so callers fall back to PostgreSQL
without any crash or exception propagating outward.

Key namespaces:
  chat:session:{session_id}:messages   → JSON list, last 50 msgs    TTL 48h
  chat:user:{user_id}:run:{run_id}     → session_id string           TTL 7d
  digest:context:{run_id}              → pre-built markdown context  TTL 7d
  digest:run:{run_id}                  → full digest payload         TTL 25h
  digest:latest                        → latest digest payload       TTL 25h
  cache:exact:{run_id}:{q_hash}        → full answer JSON            TTL 7d
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── TTLs ──────────────────────────────────────────────────────────────────────
TTL_SESSION        = 48 * 3600        # 48 h  — active conversation window
TTL_SESSION_LOOKUP = 7  * 24 * 3600  # 7 d   — user→session reverse index
TTL_DIGEST_CTX     = 7  * 24 * 3600  # 7 d   — digest context (rarely changes)
TTL_ANSWER         = 7  * 24 * 3600  # 7 d   — cached Q&A pairs

_client = None  # lazy singleton
_unavailable = False  # flip True after first connection failure to skip retries


def _get_client():
    global _client, _unavailable
    if _unavailable:
        return None
    if _client is not None:
        return _client
    try:
        from config.settings import settings
        if not settings.redis_url:
            _unavailable = True
            return None
        import redis as redis_lib
        _client = redis_lib.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )
        _client.ping()
        logger.info("Redis connected successfully")
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}) — running in DB-only mode")
        _unavailable = True
        _client = None
    return _client


# ── Generic get / set ─────────────────────────────────────────────────────────

def rget(key: str) -> Optional[Any]:
    """Get a JSON-decoded value. Returns None on miss or error."""
    try:
        r = _get_client()
        if r is None:
            return None
        raw = r.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        return None


def rset(key: str, value: Any, ttl: int) -> None:
    """Set a JSON-encoded value with TTL seconds. Silent on error."""
    try:
        r = _get_client()
        if r is None:
            return
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def rdelete(key: str) -> None:
    try:
        r = _get_client()
        if r is None:
            return
        r.delete(key)
    except Exception:
        pass


# ── Session message list ──────────────────────────────────────────────────────

def rappend_message(session_id: str, message: dict, max_len: int = 50) -> None:
    """Append one message dict to the right of the session list; trim to max_len."""
    try:
        r = _get_client()
        if r is None:
            return
        key = f"chat:session:{session_id}:messages"
        r.rpush(key, json.dumps(message, default=str))
        r.ltrim(key, -max_len, -1)
        r.expire(key, TTL_SESSION)
    except Exception:
        pass


def rget_messages(session_id: str) -> Optional[list]:
    """Return all cached messages for a session, or None on miss/error."""
    try:
        r = _get_client()
        if r is None:
            return None
        key = f"chat:session:{session_id}:messages"
        raw_list = r.lrange(key, 0, -1)
        if not raw_list:
            return None
        return [json.loads(m) for m in raw_list]
    except Exception:
        return None


def rwarm_messages(session_id: str, messages: list) -> None:
    """Bulk-load a message list into Redis (called after DB load on cache miss)."""
    try:
        r = _get_client()
        if r is None:
            return
        key = f"chat:session:{session_id}:messages"
        pipe = r.pipeline()
        pipe.delete(key)
        for msg in messages[-50:]:
            pipe.rpush(key, json.dumps(msg, default=str))
        pipe.expire(key, TTL_SESSION)
        pipe.execute()
    except Exception:
        pass


# ── Digest context cache ──────────────────────────────────────────────────────

def get_digest_context(run_id: int) -> Optional[str]:
    return rget(f"digest:context:{run_id}")


def set_digest_context(run_id: int, context: str) -> None:
    rset(f"digest:context:{run_id}", context, TTL_DIGEST_CTX)


# ── Exact-match answer cache (L1 Redis layer) ─────────────────────────────────

def get_cached_answer(run_id: int, question_hash: str) -> Optional[dict]:
    return rget(f"cache:exact:{run_id}:{question_hash}")


def set_cached_answer(run_id: int, question_hash: str, answer_payload: dict) -> None:
    rset(f"cache:exact:{run_id}:{question_hash}", answer_payload, TTL_ANSWER)


# ── Digest result cache (written by Celery worker, read by API pods) ──────────
# TTL_DIGEST = 25 h so it survives until the next scheduled run.

TTL_DIGEST = 25 * 3600


def get_digest_cache(run_id: int) -> Optional[dict]:
    """Return the cached digest payload for a specific run, or None on miss."""
    return rget(f"digest:run:{run_id}")


def get_latest_digest_cache() -> Optional[dict]:
    """Return the latest completed digest payload, or None on miss."""
    return rget("digest:latest")


def invalidate_digest_cache(run_id: int) -> None:
    """Remove stale cache entries (call before re-running a digest)."""
    rdelete(f"digest:run:{run_id}")
    rdelete("digest:latest")
