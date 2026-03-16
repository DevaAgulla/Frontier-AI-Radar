"""
Chat persistence layer — sessions, messages, and answer cache.

Three-tier lookup for every incoming question:
  L1  Redis exact-match   (question_hash)         ~0.5 ms, free
  L2  DB    exact-match   (question_hash)          ~5 ms,  free
  L3  DB    semantic      (cosine via Python)       ~20 ms, free
  L4  LLM   live call     (OpenRouter / Gemini)     3-8 s,  costs money

TODO [PRODUCTION — pgvector]:
  Once DevOps allowlists 'vector' in Azure Portal
  (Settings → Server parameters → azure.extensions → add VECTOR),
  replace cache_lookup_semantic() with a single SQL query:
      SELECT id, answer_text, sources, tool_calls_used,
             1 - (question_embedding <=> CAST(:emb AS vector)) AS sim
      FROM   ai_radar.chat_answer_cache
      WHERE  run_id = :rid
      ORDER  BY question_embedding <=> CAST(:emb AS vector)
      LIMIT  1
  And add the HNSW index:
      CREATE INDEX idx_cache_embedding_hnsw
          ON ai_radar.chat_answer_cache
          USING hnsw (question_embedding vector_cosine_ops)
          WITH (m = 16, ef_construction = 64);
  This drops semantic lookup from ~20 ms (Python loop) to ~2 ms (SQL).
"""

from __future__ import annotations

import hashlib
import json
import structlog
from typing import Any, Optional

logger = structlog.get_logger()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    """SHA-256 of lowercased + stripped question — used as exact-match key."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


# ── Schema migration (idempotent) ─────────────────────────────────────────────

def ensure_chat_schema() -> None:
    """Add window_context column to chat_sessions if it doesn't exist yet.

    Safe to call on every startup — ADD COLUMN IF NOT EXISTS is idempotent.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        session.execute(text("""
            ALTER TABLE ai_radar.chat_sessions
            ADD COLUMN IF NOT EXISTS window_context TEXT
        """))
        session.commit()
    logger.info("chat_schema: window_context column ensured")


# ── Session ───────────────────────────────────────────────────────────────────

def get_or_create_session(run_id: int, user_id: Optional[int]) -> dict:
    """
    Return the most-recently-active existing chat session for (user_id, run_id)
    or create one.  Anonymous users (user_id=None) always get a fresh session.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        if user_id:
            row = session.execute(text("""
                SELECT id, message_count, created_at, last_active, window_context
                FROM   ai_radar.chat_sessions
                WHERE  user_id = :uid AND run_id = :rid
                ORDER  BY last_active DESC NULLS LAST
                LIMIT  1
            """), {"uid": user_id, "rid": run_id}).fetchone()

            if row:
                return {
                    "session_id":     str(row[0]),
                    "message_count":  row[1],
                    "created_at":     row[2].isoformat() if row[2] else None,
                    "last_active":    row[3].isoformat() if row[3] else None,
                    "window_context": row[4],
                    "is_new":         False,
                }

        result = session.execute(text("""
            INSERT INTO ai_radar.chat_sessions (user_id, run_id)
            VALUES (:uid, :rid)
            RETURNING id, created_at
        """), {"uid": user_id, "rid": run_id})
        session.commit()
        new_row = result.fetchone()
        return {
            "session_id":    str(new_row[0]),
            "message_count": 0,
            "created_at":    new_row[1].isoformat() if new_row[1] else None,
            "last_active":   new_row[1].isoformat() if new_row[1] else None,
            "is_new":        True,
        }


def load_session_messages(session_id: str, limit: int = 50) -> list[dict]:
    """Load up to `limit` messages from PostgreSQL in chronological order."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        rows = session.execute(text("""
            SELECT role, content, sources, mode, created_at
            FROM   ai_radar.chat_messages
            WHERE  session_id = :sid
            ORDER  BY created_at ASC
            LIMIT  :lim
        """), {"sid": session_id, "lim": limit}).fetchall()

    return [
        {
            "role":      r[0],
            "content":   r[1],
            "sources":   r[2] if r[2] else [],
            "mode":      r[3],
            "timestamp": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


def get_recent_messages_for_run(
    user_id: int,
    run_id: int,
    limit: int = 10,
) -> tuple[list[dict], str | None]:
    """
    Return the most-recent `limit` messages for (user_id, run_id) by JOINing
    chat_sessions → chat_messages directly.  No session_id needed by the caller.

    Returns (messages_chronological, session_id_str).
    Messages are returned oldest-first so the UI can display them top-to-bottom.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        rows = session.execute(text("""
            SELECT m.role, m.content, m.sources, m.mode, m.created_at,
                   s.id::text AS session_id
            FROM   ai_radar.chat_messages  m
            JOIN   ai_radar.chat_sessions  s ON s.id = m.session_id
            WHERE  s.user_id = :uid
              AND  s.run_id  = :rid
            ORDER  BY m.created_at DESC
            LIMIT  :lim
        """), {"uid": user_id, "rid": run_id, "lim": limit}).fetchall()

    if not rows:
        return [], None

    session_id = rows[0][5]
    # Reverse so oldest is first (chronological display order)
    messages = [
        {
            "role":      r[0],
            "content":   r[1],
            "sources":   r[2] if r[2] else [],
            "mode":      r[3],
            "timestamp": r[4].isoformat() if r[4] else None,
        }
        for r in reversed(rows)
    ]
    return messages, session_id


def save_message(
    session_id: str,
    role: str,
    content: str,
    sources: Optional[list] = None,
    mode: str = "text",
    tool_calls: Optional[list] = None,
) -> int:
    """Persist one message turn and bump session.message_count + last_active.

    Returns the updated message_count so the caller can trigger summarization
    when count % 5 == 0.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        session.execute(text("""
            INSERT INTO ai_radar.chat_messages
                (session_id, role, content, sources, tool_calls, mode)
            VALUES (:sid, :role, :content,
                    CAST(:sources AS jsonb),
                    CAST(:tools   AS jsonb),
                    :mode)
        """), {
            "sid":     session_id,
            "role":    role,
            "content": content,
            "sources": json.dumps(sources or []),
            "tools":   json.dumps(tool_calls or []),
            "mode":    mode,
        })
        row = session.execute(text("""
            UPDATE ai_radar.chat_sessions
            SET    message_count = message_count + 1,
                   last_active   = NOW()
            WHERE  id = :sid
            RETURNING message_count
        """), {"sid": session_id}).fetchone()
        session.commit()
    return row[0] if row else 0


def get_recent_messages(session_id: str, limit: int = 10) -> list[dict]:
    """Return last `limit` messages in chronological order (oldest first)."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        rows = session.execute(text("""
            SELECT role, content, created_at
            FROM (
                SELECT role, content, created_at
                FROM   ai_radar.chat_messages
                WHERE  session_id = :sid
                ORDER  BY created_at DESC
                LIMIT  :lim
            ) sub
            ORDER BY created_at ASC
        """), {"sid": session_id, "lim": limit}).fetchall()

    return [{"role": r[0], "content": r[1]} for r in rows]


def update_window_context(session_id: str, summary: str) -> None:
    """Persist the rolling conversation summary into chat_sessions."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        session.execute(text("""
            UPDATE ai_radar.chat_sessions
            SET    window_context = :summary
            WHERE  id = :sid
        """), {"sid": session_id, "summary": summary})
        session.commit()


# ── Answer Cache ──────────────────────────────────────────────────────────────

def cache_lookup_exact(run_id: int, question: str) -> Optional[dict]:
    """
    DB exact-match lookup (L2).  L1 (Redis) is checked by the caller first.
    Returns answer dict or None.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    qhash = _hash(question)
    with db_session() as session:
        row = session.execute(text("""
            SELECT answer_text, sources, tool_calls_used
            FROM   ai_radar.chat_answer_cache
            WHERE  run_id = :rid AND question_hash = :qh
            LIMIT  1
        """), {"rid": run_id, "qh": qhash}).fetchone()

        if not row:
            return None

        session.execute(text("""
            UPDATE ai_radar.chat_answer_cache
            SET    hit_count  = hit_count + 1,
                   last_hit_at = NOW()
            WHERE  run_id = :rid AND question_hash = :qh
        """), {"rid": run_id, "qh": qhash})
        session.commit()

    return {
        "answer":          row[0],
        "sources":         row[1] if row[1] else [],
        "tool_calls_used": row[2] if row[2] else [],
        "cache_hit":       "exact_db",
    }


def cache_lookup_semantic(
    run_id: int,
    question: str,
    threshold: float = 0.92,
) -> Optional[dict]:
    """
    Semantic similarity lookup (L3) — Python cosine over top-200 candidates.

    TODO [PRODUCTION — pgvector]: Replace body with single SQL query using
    the <=> operator and HNSW index.  See module docstring for the exact SQL.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    try:
        import numpy as np
        from core.embedder import embed_text

        q_emb  = np.array(embed_text(question), dtype=np.float32)
        q_norm = float(np.linalg.norm(q_emb))
        if q_norm == 0:
            return None

        with db_session() as session:
            rows = session.execute(text("""
                SELECT id, answer_text, sources, tool_calls_used, question_embedding
                FROM   ai_radar.chat_answer_cache
                WHERE  run_id = :rid
                  AND  question_embedding IS NOT NULL
                ORDER  BY hit_count DESC
                LIMIT  200
            """), {"rid": run_id}).fetchall()

        best_sim, best_row = 0.0, None
        for row in rows:
            if not row[4]:
                continue
            c_emb  = np.array(row[4], dtype=np.float32)
            c_norm = float(np.linalg.norm(c_emb))
            if c_norm == 0:
                continue
            sim = float(np.dot(q_emb, c_emb) / (q_norm * c_norm))
            if sim > best_sim:
                best_sim, best_row = sim, row

        if best_row is None or best_sim < threshold:
            return None

        with db_session() as session:
            session.execute(text("""
                UPDATE ai_radar.chat_answer_cache
                SET    hit_count  = hit_count + 1,
                       last_hit_at = NOW()
                WHERE  id = :id
            """), {"id": best_row[0]})
            session.commit()

        return {
            "answer":          best_row[1],
            "sources":         best_row[2] if best_row[2] else [],
            "tool_calls_used": best_row[3] if best_row[3] else [],
            "cache_hit":       f"semantic:{best_sim:.3f}",
        }

    except Exception as exc:
        logger.warning("semantic_cache_lookup_failed", error=str(exc))
        return None


def cache_save(
    run_id: int,
    question: str,
    answer: str,
    sources: Optional[list] = None,
    tool_calls_used: Optional[list] = None,
    mode: str = "text",
) -> None:
    """Persist a Q&A pair with embedding.  ON CONFLICT DO NOTHING (idempotent)."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    try:
        from core.embedder import embed_text
        embedding = embed_text(question)
    except Exception:
        embedding = None

    qhash = _hash(question)

    with db_session() as session:
        session.execute(text("""
            INSERT INTO ai_radar.chat_answer_cache
                (run_id, question_text, question_hash, question_embedding,
                 answer_text, sources, tool_calls_used, mode)
            VALUES
                (:rid, :qtxt, :qhash, :qemb, :atxt,
                 CAST(:src AS jsonb), CAST(:tc AS jsonb), :mode)
            ON CONFLICT (run_id, question_hash) DO NOTHING
        """), {
            "rid":   run_id,
            "qtxt":  question.strip(),
            "qhash": qhash,
            "qemb":  embedding,
            "atxt":  answer,
            "src":   json.dumps(sources or []),
            "tc":    json.dumps(tool_calls_used or []),
            "mode":  mode,
        })
        session.commit()


def load_voice_history(session_id: str, limit: int = 150) -> list[dict]:
    """Return voice-mode messages for a session in chronological order.

    Returns each message with its DB id (used as the IndexedDB audio key base),
    role, content, and created_at timestamp.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        rows = session.execute(text("""
            SELECT id, role, content, created_at
            FROM   ai_radar.chat_messages
            WHERE  session_id = :sid AND mode = 'voice'
            ORDER  BY created_at ASC
            LIMIT  :lim
        """), {"sid": str(session_id), "lim": limit}).fetchall()

    return [
        {
            "id":         r[0],
            "role":       r[1],
            "content":    r[2],
            "created_at": r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]


def get_popular_questions(run_id: int, limit: int = 5) -> list[dict]:
    """Top-N most-asked cached questions for a digest — drives dynamic quick prompts."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        rows = session.execute(text("""
            SELECT question_text, hit_count
            FROM   ai_radar.chat_answer_cache
            WHERE  run_id = :rid AND hit_count > 0
            ORDER  BY hit_count DESC
            LIMIT  :lim
        """), {"rid": run_id, "lim": limit}).fetchall()

    return [{"question": r[0], "hit_count": r[1]} for r in rows]
