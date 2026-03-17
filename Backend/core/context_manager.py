"""Context Manager for Frontier AI Radar — text chat and voice agent.

Two distinct context-assembly paths
─────────────────────────────────────
  VOICE fast-path   (<10 ms)
    System prompt + digest (Redis/DB, no embedding) + recent window
    Semantic search is NEVER on the voice hot-path. Voice needs TTS to
    start within ~2 s of the user finishing speech. Any CPU/DB work that
    can be skipped without degrading the answer quality must be skipped.

  TEXT full-path    (200–500 ms acceptable)
    System prompt + semantic digest (pgvector) + window summary +
    semantic history (pgvector) + recent window
    All embedding runs in the pre-warmed ThreadPoolExecutor via
    core.embedding_executor — never blocks the event loop.

Context token budget (shared)
──────────────────────────────
  1. System prompt       ~400 t  static, compiled once
  2. Digest knowledge   ~1500 t  per-run, Redis-cached 7 days
  3. Window summary      ~400 t  rolling LLM-generated summary, DB-persisted
  4. Semantic history    ~300 t  text-mode only — deduplicated prior exchanges
  5. Recent window       ~800 t  last RECENT_WINDOW turns verbatim
  6. Current query       ~100 t
                        ──────
  Total budget          ~3500 t  (leaves ~600 t for the LLM response)
"""
from __future__ import annotations

import asyncio
import structlog
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = structlog.get_logger()

# ── Tuning knobs ───────────────────────────────────────────────────────────────

RECENT_WINDOW    = 6      # verbatim turns to include
SUMMARY_EVERY    = 5      # summarise after every N new turns
MAX_DIGEST_CHARS = 6000   # ~1500 tokens of digest context


# ── Public API ─────────────────────────────────────────────────────────────────

async def build_messages(
    *,
    session_id:  str,
    run_db_id:   int,
    query:       str,
    mode:        str = "text",   # "text" | "voice"
    system_prompt: str,
    user_id:     Optional[int] = None,
    persona_id:  str = "",
) -> list:
    """Assemble the full message list to send to the LLM.

    Dispatches to the appropriate pipeline based on mode:
      voice → _build_voice_messages()   (<10 ms, no embedding)
      text  → _build_text_messages()    (full semantic pipeline)
    """
    if mode == "voice":
        return await _build_voice_messages(
            session_id=session_id,
            run_db_id=run_db_id,
            query=query,
            system_prompt=system_prompt,
        )
    return await _build_text_messages(
        session_id=session_id,
        run_db_id=run_db_id,
        query=query,
        system_prompt=system_prompt,
        user_id=user_id,
        persona_id=persona_id,
    )


async def maybe_summarise(session_id: str, message_count: int) -> None:
    """Trigger a rolling summary when message_count is a multiple of SUMMARY_EVERY.

    Summarises the oldest messages outside the recent window so the verbatim
    window is always preserved. Safe to call from a background asyncio.Task.
    """
    if message_count % SUMMARY_EVERY != 0:
        return

    try:
        from db.chat import load_session_messages, update_window_context
        from config.settings import settings

        all_msgs = load_session_messages(session_id, limit=RECENT_WINDOW + SUMMARY_EVERY)
        if len(all_msgs) <= RECENT_WINDOW:
            return

        older = all_msgs[:-RECENT_WINDOW]
        convo = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}" for m in older
        )
        prompt = (
            "Summarise the following conversation turns concisely. "
            "Preserve: user's name (if mentioned), key questions asked, "
            "key answers given, any facts the user stated about themselves. "
            "Keep it under 150 words.\n\n" + convo
        )

        llm = _get_summary_llm(settings)
        result = await llm.ainvoke(prompt)
        summary_text = result.content.strip()

        existing = _get_window_summary(session_id)
        if existing:
            merge_prompt = (
                "Merge these two conversation summaries into one coherent summary "
                f"(under 200 words):\n\nEARLIER:\n{existing}\n\nNEWER:\n{summary_text}"
            )
            merged = await llm.ainvoke(merge_prompt)
            summary_text = merged.content.strip()

        update_window_context(session_id, summary_text)
        logger.info("context_summary_updated", session_id=session_id, length=len(summary_text))

    except Exception as exc:
        logger.warning("context_summarise_failed", session_id=session_id, error=str(exc))


# ── Voice fast-path ────────────────────────────────────────────────────────────

async def _build_voice_messages(
    *,
    session_id:    str,
    run_db_id:     int,
    query:         str,
    system_prompt: str,
) -> list:
    """Voice context assembly — strictly no embedding, target <10 ms.

    Pipeline:
      1. System prompt
      2. Digest from Redis/DB (no vector search — Redis hit is ~1 ms)
      3. Rolling summary (single DB row lookup)
      4. Run-ID hint
      5. Recent RECENT_WINDOW turns (single indexed DB query)
      6. Current utterance
    """
    messages: list = []

    # 1. System prompt
    messages.append(SystemMessage(content=system_prompt))

    # 2. Digest — Redis only (no embedding, no pgvector)
    digest_ctx = await _get_digest_context_fast(run_db_id)
    if digest_ctx:
        messages.append(SystemMessage(
            content=f"=== Frontier AI Radar Intelligence Brief ===\n{digest_ctx}"
        ))

    # 3. Run-ID hint
    messages.append(SystemMessage(content=(
        f"Active digest run ID: {run_db_id}. "
        "Call query_digest_state for AI/tech questions. "
        "For greetings or general questions respond naturally."
    )))

    # 4. Rolling window summary
    summary = _get_window_summary(session_id)
    if summary:
        messages.append(SystemMessage(
            content=f"=== Earlier conversation summary ===\n{summary}"
        ))

    # 5. Recent verbatim turns
    from db.chat import get_recent_messages
    for m in get_recent_messages(session_id, limit=RECENT_WINDOW):
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            messages.append(AIMessage(content=m["content"]))

    # 6. Current utterance
    messages.append(HumanMessage(content=query))

    logger.debug(
        "context_built",
        session_id=session_id, run_db_id=run_db_id, mode="voice",
        total_messages=len(messages),
        has_digest=bool(digest_ctx), has_summary=bool(summary),
    )
    return messages


# ── Text full-path ─────────────────────────────────────────────────────────────

async def _build_text_messages(
    *,
    session_id:    str,
    run_db_id:     int,
    query:         str,
    system_prompt: str,
    user_id:       Optional[int],
    persona_id:    str,
) -> list:
    """Text context assembly — full semantic pipeline via pre-warmed executor.

    Pipeline:
      1. System prompt
      2. Digest (semantic L0 → Redis L1 → DB L3)
      3. Run-ID hint
      4. Rolling summary
      5. Semantic history (pgvector, executor, circuit-breaker timeout)
      6. Recent RECENT_WINDOW turns
      7. Current query
    """
    from core.embedding_executor import TEXT_TIMEOUT

    messages: list = []

    # 1. System prompt
    messages.append(SystemMessage(content=system_prompt))

    # 2. Digest — semantic-aware (runs embed in executor, falls back to Redis/DB)
    digest_ctx = await _get_digest_context_semantic(run_db_id, query)
    if digest_ctx:
        messages.append(SystemMessage(
            content=f"=== Frontier AI Radar Intelligence Brief ===\n{digest_ctx}"
        ))

    # 3. Run-ID hint
    messages.append(SystemMessage(content=(
        f"Active digest run ID: {run_db_id}. "
        "Call query_digest_state for AI/tech questions. "
        "For greetings or general questions respond naturally."
    )))

    # 4. Rolling summary
    summary = _get_window_summary(session_id)
    if summary:
        messages.append(SystemMessage(
            content=f"=== Earlier conversation summary ===\n{summary}"
        ))

    # 5. Recent turns (needed for deduplication in step 6)
    from db.chat import get_recent_messages
    recent = get_recent_messages(session_id, limit=RECENT_WINDOW)

    # 6. Semantic history — circuit-breaker: skip gracefully on timeout/error
    if user_id and persona_id:
        try:
            from core.embedding_executor import embed_async

            q_emb = await embed_async(query, timeout=TEXT_TIMEOUT)

            def _search() -> list:
                vec_str = "[" + ",".join(map(str, q_emb)) + "]"
                return _semantic_search_with_vec(vec_str, user_id, persona_id, run_db_id)

            relevant = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, _search),
                timeout=1.0,
            )
            recent_contents = {m["content"][:100] for m in recent}
            unique = [r for r in relevant if r["content"][:100] not in recent_contents]
            if unique:
                rel_text = "\n".join(
                    f"{r['role'].upper()}: {r['content'][:300]}" for r in unique
                )
                messages.append(SystemMessage(
                    content=f"=== Related prior exchanges ===\n{rel_text}"
                ))
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("semantic_history_skipped", reason=str(exc)[:60])

    # 7. Recent verbatim turns
    for m in recent:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            messages.append(AIMessage(content=m["content"]))

    # 8. Current query
    messages.append(HumanMessage(content=query))

    logger.debug(
        "context_built",
        session_id=session_id, run_db_id=run_db_id, mode="text",
        total_messages=len(messages), recent_turns=len(recent),
        has_digest=bool(digest_ctx), has_summary=bool(summary),
    )
    return messages


# ── Digest context helpers ─────────────────────────────────────────────────────

async def _get_digest_context_fast(run_db_id: int) -> str:
    """Voice-safe digest loader — Redis/DB only, no embedding, target <5 ms."""
    # L1: Redis pre-built context string
    try:
        from cache.redis_client import get_digest_context
        cached = get_digest_context(run_db_id)
        if cached:
            return cached[:MAX_DIGEST_CHARS]
    except Exception:
        pass

    # L2: Redis full digest payload
    try:
        from cache.redis_client import get_digest_cache
        payload = get_digest_cache(run_db_id)
        if payload:
            return _format_digest_payload(payload, run_db_id)
    except Exception:
        pass

    # L3: DB fallback
    return _load_digest_from_db(run_db_id)


async def _get_digest_context_semantic(run_db_id: int, query: str) -> str:
    """Text-mode digest loader — semantic L0 first, then fast fallbacks."""
    # L0: Semantic search over pre-embedded digest sections
    if query:
        try:
            from core.embedding_executor import embed_async, TEXT_TIMEOUT
            from db.connection import get_session as db_session
            from sqlalchemy import text

            q_emb   = await embed_async(query, timeout=TEXT_TIMEOUT)
            vec_str = "[" + ",".join(map(str, q_emb)) + "]"

            def _sem_digest() -> str:
                with db_session() as sess:
                    rows = sess.execute(text("""
                        SELECT section, content
                        FROM   ai_radar.digest_cache
                        WHERE  run_id   = :rid
                          AND  embedding IS NOT NULL
                        ORDER  BY embedding <=> CAST(:emb AS vector)
                        LIMIT  6
                    """), {"rid": run_db_id, "emb": vec_str}).fetchall()
                if not rows:
                    return ""
                lines = [f"[{r[0]}] {r[1][:500]}" if r[0] else r[1][:500] for r in rows]
                return "\n\n".join(lines)

            sem_ctx = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, _sem_digest),
                timeout=2.0,
            )
            if sem_ctx:
                return sem_ctx[:MAX_DIGEST_CHARS]
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("semantic_digest_skipped", reason=str(exc)[:60])

    # Fallback to fast path (Redis/DB)
    return await _get_digest_context_fast(run_db_id)


# ── Internal utilities ─────────────────────────────────────────────────────────

def _format_digest_payload(payload: dict, run_db_id: int) -> str:
    findings = payload.get("ranked_findings", [])
    lines = [f"Total findings: {len(findings)}", ""]
    for i, f in enumerate(findings[:20], 1):
        lines.append(f"{i}. {f.get('title', 'Untitled')}")
        if f.get("why_it_matters"):
            lines.append(f"   Why it matters: {f['why_it_matters']}")
        if f.get("source_url"):
            lines.append(f"   Source: {f['source_url']}")
    ctx = "\n".join(lines)
    try:
        from cache.redis_client import set_digest_context
        set_digest_context(run_db_id, ctx)
    except Exception:
        pass
    return ctx[:MAX_DIGEST_CHARS]


def _load_digest_from_db(run_db_id: int) -> str:
    try:
        from db.connection import get_session as db_session
        from db.models import Finding
        with db_session() as sess:
            rows = (
                sess.query(Finding)
                .filter(Finding.run_id == run_db_id)
                .order_by(Finding.rank.asc().nullslast(), Finding.impact_score.desc())
                .limit(20)
                .all()
            )
        if rows:
            lines = [f"Total findings: {len(rows)}", ""]
            for i, f in enumerate(rows, 1):
                lines.append(f"{i}. {f.title or 'Untitled'}")
                if f.why_it_matters:
                    lines.append(f"   Why it matters: {f.why_it_matters}")
            return "\n".join(lines)[:MAX_DIGEST_CHARS]
    except Exception:
        pass
    return ""


def _semantic_search_with_vec(vec_str: str, user_id: int, persona_id: str, run_id: int, limit: int = 4, threshold: float = 0.75) -> list:
    """Run pgvector semantic search with a pre-computed embedding vector string."""
    from db.connection import get_session as db_session
    from sqlalchemy import text
    params: dict = {
        "uid": user_id, "pid": persona_id, "emb": vec_str,
        "lim": limit, "thr": 1.0 - threshold,
    }
    run_filter = "AND run_id = :rid" if run_id else ""
    if run_id:
        params["rid"] = run_id
    with db_session() as sess:
        rows = sess.execute(text(f"""
            SELECT role, content,
                   embedding <=> CAST(:emb AS vector) AS dist
            FROM   ai_radar.conversation_embeddings
            WHERE  user_id    = :uid
              AND  persona_id = :pid
              {run_filter}
              AND  embedding  IS NOT NULL
            ORDER  BY embedding <=> CAST(:emb AS vector)
            LIMIT  :lim
        """), params).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows if r[2] <= params["thr"]]


def _get_window_summary(session_id: str) -> Optional[str]:
    try:
        from db.connection import get_session as db_session
        from sqlalchemy import text
        with db_session() as sess:
            row = sess.execute(
                text("SELECT window_context FROM ai_data_radar.chat_sessions WHERE id = CAST(:sid AS uuid)"),
                {"sid": session_id}
            ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _get_summary_llm(settings):
    try:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            max_tokens=256,
            temperature=0.3,
        )
    except Exception:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=settings.gemini_api_key,
            max_output_tokens=256,
        )
