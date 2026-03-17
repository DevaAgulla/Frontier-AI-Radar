"""
Chat persistence layer — sessions, messages, and answer cache.

Three-tier lookup for every incoming question:
  L1  Redis exact-match   (question_hash)         ~0.5 ms, free
  L2  DB    exact-match   (question_hash)          ~5 ms,  free
  L3  DB    semantic      (pgvector <=> cosine)    ~2 ms,  free
  L4  LLM   live call     (OpenRouter / Gemini)     3-8 s,  costs money

pgvector is enabled — all embedding columns use vector(384) with HNSW indexes.
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
    """Run all idempotent schema migrations on startup.

    Safe to call on every startup — ADD COLUMN IF NOT EXISTS and
    CREATE TABLE IF NOT EXISTS are both idempotent.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        # Original migration: window_context on chat_sessions
        session.execute(text("""
            ALTER TABLE ai_data_radar.chat_sessions
            ADD COLUMN IF NOT EXISTS window_context TEXT
        """))

        # Add persona_id to existing chat_sessions table
        session.execute(text("""
            ALTER TABLE ai_data_radar.chat_sessions
            ADD COLUMN IF NOT EXISTS persona_id VARCHAR(64) NOT NULL DEFAULT ''
        """))

        # Migrate unique constraint to include persona_id.
        # Use SAVEPOINT so this block is isolated — if ADD CONSTRAINT fails (already
        # exists from a prior run), only this block rolls back; all other migrations
        # in this transaction remain intact.
        session.execute(text("SAVEPOINT persona_constraint_mig"))
        try:
            session.execute(text("""
                ALTER TABLE ai_data_radar.chat_sessions
                DROP CONSTRAINT IF EXISTS uq_chat_sessions_user_run
            """))
            session.execute(text("""
                ALTER TABLE ai_data_radar.chat_sessions
                ADD CONSTRAINT uq_chat_sessions_user_run_persona
                UNIQUE (user_id, run_id, persona_id)
            """))
            session.execute(text("RELEASE SAVEPOINT persona_constraint_mig"))
        except Exception:
            session.execute(text("ROLLBACK TO SAVEPOINT persona_constraint_mig"))

        # Migrate existing answer cache column to vector(384) if still FLOAT[]
        # Wrapped in savepoint — no-op if already vector type
        try:
            session.execute(text("""
                ALTER TABLE ai_data_radar.chat_answer_cache
                ALTER COLUMN question_embedding TYPE vector(384)
                USING question_embedding::vector(384)
            """))
        except Exception:
            session.rollback()
        try:
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cache_embedding_hnsw
                ON ai_data_radar.chat_answer_cache
                USING hnsw (question_embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """))
        except Exception:
            session.rollback()

        # Create conversation_embeddings table for semantic search
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_radar.conversation_embeddings (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id  UUID NOT NULL,
                message_id  BIGINT,
                user_id     INTEGER,
                persona_id  VARCHAR(64) NOT NULL DEFAULT '',
                run_id      INTEGER,
                role        VARCHAR(16) NOT NULL,
                content     TEXT NOT NULL,
                embedding   vector(384),
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_conv_emb_scope
            ON ai_radar.conversation_embeddings(user_id, persona_id, run_id)
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_conv_emb_hnsw
            ON ai_radar.conversation_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """))

        # Create digest_cache table for pre-embedded digest sections
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_radar.digest_cache (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_id     INTEGER NOT NULL,
                section    VARCHAR(128),
                content    TEXT NOT NULL,
                embedding  vector(384),
                cached_at  TIMESTAMP DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_digest_cache_run
            ON ai_radar.digest_cache(run_id)
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_digest_cache_hnsw
            ON ai_radar.digest_cache
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """))

        # Create conversation_summaries table for rolling summaries
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_radar.conversation_summaries (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id          UUID NOT NULL,
                user_id             INTEGER,
                persona_id          VARCHAR(64) NOT NULL DEFAULT '',
                run_id              INTEGER,
                summary             TEXT NOT NULL,
                embedding           vector(384),
                message_count_end   INTEGER,
                created_at          TIMESTAMP DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_conv_summaries_scope
            ON ai_radar.conversation_summaries(user_id, persona_id, run_id)
        """))

        session.commit()
    logger.info("chat_schema: all migrations ensured")


# ── Session ───────────────────────────────────────────────────────────────────

def get_or_create_session(run_id: int, user_id: Optional[int], persona_id: str = '') -> dict:
    """
    Return the most-recently-active existing chat session for (user_id, run_id, persona_id)
    or create one.  Anonymous users (user_id=None) always get a fresh session.

    persona_id='' is backward-compatible with callers that don't pass it.
    """
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        if user_id:
            row = session.execute(text("""
                SELECT id, message_count, created_at, last_active, window_context
                FROM   ai_data_radar.chat_sessions
                WHERE  user_id = :uid AND run_id = :rid AND persona_id = :pid
                ORDER  BY last_active DESC NULLS LAST
                LIMIT  1
            """), {"uid": user_id, "rid": run_id, "pid": persona_id}).fetchone()

            if row:
                return {
                    "session_id":     str(row[0]),
                    "message_count":  row[1],
                    "created_at":     row[2].isoformat() if row[2] else None,
                    "last_active":    row[3].isoformat() if row[3] else None,
                    "window_context": row[4],
                    "persona_id":     persona_id,
                    "is_new":         False,
                }

        try:
            result = session.execute(text("""
                INSERT INTO ai_data_radar.chat_sessions (user_id, run_id, persona_id)
                VALUES (:uid, :rid, :pid)
                RETURNING id, created_at
            """), {"uid": user_id, "rid": run_id, "pid": persona_id})
            session.commit()
            new_row = result.fetchone()
            return {
                "session_id":    str(new_row[0]),
                "message_count": 0,
                "created_at":    new_row[1].isoformat() if new_row[1] else None,
                "last_active":   new_row[1].isoformat() if new_row[1] else None,
                "persona_id":    persona_id,
                "is_new":        True,
            }
        except Exception:
            # Constraint violation — old DB has unique(user_id, run_id) without
            # persona_id column. Roll back and find the conflicting row by
            # (user_id, run_id) only, regardless of which persona it was created for.
            session.rollback()
            row = session.execute(text("""
                SELECT id, message_count, created_at, last_active, window_context
                FROM   ai_data_radar.chat_sessions
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
                    "persona_id":     persona_id,
                    "is_new":         False,
                }
            raise


def load_session_messages(session_id: str, limit: int = 50) -> list[dict]:
    """Load up to `limit` messages from PostgreSQL in chronological order."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    with db_session() as session:
        rows = session.execute(text("""
            SELECT role, content, sources, mode, created_at
            FROM   ai_data_radar.chat_messages
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
            FROM   ai_data_radar.chat_messages  m
            JOIN   ai_data_radar.chat_sessions  s ON s.id = m.session_id
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
            INSERT INTO ai_data_radar.chat_messages
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
            UPDATE ai_data_radar.chat_sessions
            SET    message_count = message_count + 1,
                   last_active   = NOW()
            WHERE  id = :sid
            RETURNING message_count
        """), {"sid": session_id}).fetchone()
        session.commit()

    # Append to Redis so next GET /chat/session is a pure-Redis hit
    try:
        from cache.redis_client import rappend_message
        rappend_message(session_id, {
            "role":      role,
            "content":   content,
            "sources":   sources or [],
            "mode":      mode,
            "timestamp": None,
        })
    except Exception:
        pass

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
                FROM   ai_data_radar.chat_messages
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
            UPDATE ai_data_radar.chat_sessions
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
            FROM   ai_data_radar.chat_answer_cache
            WHERE  run_id = :rid AND question_hash = :qh
            LIMIT  1
        """), {"rid": run_id, "qh": qhash}).fetchone()

        if not row:
            return None

        session.execute(text("""
            UPDATE ai_data_radar.chat_answer_cache
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
    """Semantic similarity lookup (L3) — pgvector <=> cosine via HNSW index."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    try:
        from core.embedder import embed_text

        embedding = embed_text(question)
        vec_str   = "[" + ",".join(map(str, embedding)) + "]"

        with db_session() as session:
            row = session.execute(text("""
                SELECT id, answer_text, sources, tool_calls_used,
                       1 - (question_embedding <=> CAST(:emb AS vector)) AS sim
                FROM   ai_data_radar.chat_answer_cache
                WHERE  run_id = :rid
                  AND  question_embedding IS NOT NULL
                ORDER  BY question_embedding <=> CAST(:emb AS vector)
                LIMIT  1
            """), {"rid": run_id, "emb": vec_str}).fetchone()

        if row is None or row[4] < threshold:
            return None

        with db_session() as session:
            session.execute(text("""
                UPDATE ai_data_radar.chat_answer_cache
                SET    hit_count   = hit_count + 1,
                       last_hit_at = NOW()
                WHERE  id = :id
            """), {"id": row[0]})
            session.commit()

        return {
            "answer":          row[1],
            "sources":         row[2] if row[2] else [],
            "tool_calls_used": row[3] if row[3] else [],
            "cache_hit":       f"semantic:{row[4]:.3f}",
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
        _emb    = embed_text(question)
        vec_str = "[" + ",".join(map(str, _emb)) + "]"
    except Exception:
        vec_str = None

    qhash = _hash(question)

    with db_session() as session:
        session.execute(text("""
            INSERT INTO ai_data_radar.chat_answer_cache
                (run_id, question_text, question_hash, question_embedding,
                 answer_text, sources, tool_calls_used, mode)
            VALUES
                (:rid, :qtxt, :qhash,
                 CASE WHEN :qemb IS NOT NULL THEN CAST(:qemb AS vector) ELSE NULL END,
                 :atxt, CAST(:src AS jsonb), CAST(:tc AS jsonb), :mode)
            ON CONFLICT (run_id, question_hash) DO NOTHING
        """), {
            "rid":   run_id,
            "qtxt":  question.strip(),
            "qhash": qhash,
            "qemb":  vec_str,
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
            FROM   ai_data_radar.chat_messages
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
            FROM   ai_data_radar.chat_answer_cache
            WHERE  run_id = :rid AND hit_count > 0
            ORDER  BY hit_count DESC
            LIMIT  :lim
        """), {"rid": run_id, "lim": limit}).fetchall()

    return [{"question": r[0], "hit_count": r[1]} for r in rows]


# ── Conversation Embeddings ───────────────────────────────────────────────────

def get_last_message_id(session_id: str) -> Optional[int]:
    """Return the DB id of the most recently saved message for this session."""
    from db.connection import get_session as db_session
    from sqlalchemy import text

    try:
        with db_session() as session:
            row = session.execute(text("""
                SELECT id FROM ai_data_radar.chat_messages
                WHERE session_id = :sid
                ORDER BY created_at DESC
                LIMIT 1
            """), {"sid": session_id}).fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.warning("get_last_message_id_failed", session_id=session_id, error=str(exc))
        return None


def embed_message_background(
    session_id: str,
    message_id: Optional[int],
    role: str,
    content: str,
    user_id: Optional[int],
    persona_id: str,
    run_id: Optional[int],
) -> None:
    """Embed a message and store it in ai_radar.conversation_embeddings.

    Designed to run in a thread via asyncio.to_thread() — never raises.
    """
    try:
        from core.embedder import embed_text
        from db.connection import get_session as db_session
        from sqlalchemy import text

        embedding = embed_text(content)
        vec_str   = "[" + ",".join(map(str, embedding)) + "]"

        with db_session() as session:
            session.execute(text("""
                INSERT INTO ai_radar.conversation_embeddings
                    (session_id, message_id, user_id, persona_id, run_id, role, content, embedding)
                VALUES
                    (CAST(:sid AS uuid), :mid, :uid, :pid, :rid, :role, :content,
                     CAST(:emb AS vector))
            """), {
                "sid":     session_id,
                "mid":     message_id,
                "uid":     user_id,
                "pid":     persona_id,
                "rid":     run_id,
                "role":    role,
                "content": content,
                "emb":     vec_str,
            })
            session.commit()
    except Exception as exc:
        logger.warning("embed_message_background_failed",
                       session_id=session_id, role=role, error=str(exc))


def semantic_search_history(
    query_text: str,
    user_id: int,
    persona_id: str,
    run_id: Optional[int],
    limit: int = 5,
    threshold: float = 0.75,
) -> list[dict]:
    """Semantic search over past conversation turns via pgvector <=> operator."""
    try:
        from core.embedder import embed_text
        from db.connection import get_session as db_session
        from sqlalchemy import text

        embedding = embed_text(query_text)
        vec_str   = "[" + ",".join(map(str, embedding)) + "]"

        params: dict = {"uid": user_id, "pid": persona_id, "emb": vec_str,
                        "lim": limit, "thr": 1.0 - threshold}
        run_filter = ""
        if run_id is not None:
            run_filter = "AND run_id = :rid"
            params["rid"] = run_id

        with db_session() as session:
            rows = session.execute(text(f"""
                SELECT role, content,
                       embedding <=> CAST(:emb AS vector) AS dist
                FROM   ai_radar.conversation_embeddings
                WHERE  user_id    = :uid
                  AND  persona_id = :pid
                  {run_filter}
                  AND  embedding IS NOT NULL
                ORDER  BY embedding <=> CAST(:emb AS vector)
                LIMIT  :lim
            """), params).fetchall()

        return [
            {"role": row[0], "content": row[1]}
            for row in rows
            if row[2] <= params["thr"]
        ]

    except Exception as exc:
        logger.warning("semantic_search_history_failed", error=str(exc))
        return []


def get_sessions_for_persona(
    user_id: int,
    persona_id: str,
    run_id: Optional[int] = None,
    limit: int = 10,
) -> list[dict]:
    """Return recent sessions for (user_id, persona_id), optionally scoped to run_id.

    Each item: {"session_id": str, "run_id": int, "message_count": int,
                "last_active": str, "preview": str}
    The preview is the first user message in that session, truncated to 60 chars.
    """
    try:
        from db.connection import get_session as db_session
        from sqlalchemy import text

        params: dict = {"uid": user_id, "pid": persona_id, "lim": limit}
        run_filter = ""
        if run_id is not None:
            run_filter = "AND s.run_id = :rid"
            params["rid"] = run_id

        with db_session() as session:
            rows = session.execute(text(f"""
                SELECT s.id::text,
                       s.run_id,
                       s.message_count,
                       s.last_active,
                       (
                           SELECT content
                           FROM   ai_data_radar.chat_messages
                           WHERE  session_id = s.id AND role = 'user'
                           ORDER  BY created_at ASC
                           LIMIT  1
                       ) AS first_user_msg
                FROM   ai_data_radar.chat_sessions s
                WHERE  s.user_id    = :uid
                  AND  s.persona_id = :pid
                  {run_filter}
                ORDER  BY s.last_active DESC NULLS LAST
                LIMIT  :lim
            """), params).fetchall()

        return [
            {
                "session_id":    r[0],
                "run_id":        r[1],
                "message_count": r[2],
                "last_active":   r[3].isoformat() if r[3] else None,
                "preview":       (r[4] or "")[:60],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("get_sessions_for_persona_failed", error=str(exc))
        return []


# ── Digest Cache (pre-embedded sections) ─────────────────────────────────────

def cache_digest_for_run(run_id: int, sections: list[dict]) -> None:
    """Embed each digest section and store in ai_radar.digest_cache.

    Idempotent: skips if run_id already has cached rows. Never raises.
    sections: list of {"section": str, "content": str}
    """
    try:
        from core.embedder import embed_text
        from db.connection import get_session as db_session
        from sqlalchemy import text

        with db_session() as session:
            count_row = session.execute(text("""
                SELECT COUNT(*) FROM ai_radar.digest_cache WHERE run_id = :rid
            """), {"rid": run_id}).fetchone()
            if count_row and count_row[0] > 0:
                logger.info("cache_digest_for_run_skip", run_id=run_id,
                            existing=count_row[0])
                return

        with db_session() as session:
            for sec in sections:
                content   = sec.get("content", "")
                section   = sec.get("section", "")
                if not content:
                    continue
                try:
                    embedding = embed_text(content)
                    vec_str   = "[" + ",".join(map(str, embedding)) + "]"
                except Exception:
                    vec_str = None

                session.execute(text("""
                    INSERT INTO ai_radar.digest_cache (run_id, section, content, embedding)
                    VALUES (:rid, :sec, :content,
                            CASE WHEN :emb IS NOT NULL THEN CAST(:emb AS vector) ELSE NULL END)
                """), {
                    "rid":     run_id,
                    "sec":     section,
                    "content": content,
                    "emb":     vec_str,
                })
            session.commit()
        logger.info("cache_digest_for_run_done", run_id=run_id, count=len(sections))

    except Exception as exc:
        logger.warning("cache_digest_for_run_failed", run_id=run_id, error=str(exc))


def get_semantic_digest_context(run_id: int, query_text: str, limit: int = 6) -> str:
    """Semantic search over ai_radar.digest_cache via pgvector <=> operator."""
    try:
        from core.embedder import embed_text
        from db.connection import get_session as db_session
        from sqlalchemy import text

        embedding = embed_text(query_text)
        vec_str   = "[" + ",".join(map(str, embedding)) + "]"

        with db_session() as session:
            rows = session.execute(text("""
                SELECT section, content
                FROM   ai_radar.digest_cache
                WHERE  run_id    = :rid
                  AND  embedding IS NOT NULL
                ORDER  BY embedding <=> CAST(:emb AS vector)
                LIMIT  :lim
            """), {"rid": run_id, "emb": vec_str, "lim": limit}).fetchall()

        if not rows:
            return ""

        lines = []
        for section, content in rows:
            if section:
                lines.append(f"[{section}] {content[:500]}")
            else:
                lines.append(content[:500])
        return "\n\n".join(lines)

    except Exception as exc:
        logger.warning("get_semantic_digest_context_failed", run_id=run_id, error=str(exc))
        return ""
