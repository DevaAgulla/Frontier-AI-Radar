"""Context Manager for Frontier AI Radar — text chat and voice agent.

Context hierarchy (token budget ≤ 4096)
────────────────────────────────────────
  1. System prompt       ~400 t  static, compiled once
  2. Digest knowledge   ~1500 t  per-run, Redis-cached 7 days
  3. Window summary      ~400 t  rolling LLM-generated summary, DB-persisted
  4. Recent window       ~800 t  last RECENT_WINDOW turns verbatim
  5. Current query       ~100 t
                        ──────
  Total budget          ~3200 t  (leaves ~900 t for the LLM response)

Retrieval priority
──────────────────
  Factual AI questions   → digest knowledge first, web search second
  Conversational topics  → window summary + recent window
  Greetings / chitchat   → recent window only (no tools called)
"""

from __future__ import annotations

import structlog
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = structlog.get_logger()

# ── Tuning knobs ──────────────────────────────────────────────────────────────

RECENT_WINDOW    = 6      # verbatim turns to include
SUMMARY_EVERY    = 5      # summarise after every N new turns
MAX_DIGEST_CHARS = 6000   # ~1500 tokens of digest context


# ── Public API ────────────────────────────────────────────────────────────────

async def build_messages(
    *,
    session_id: str,
    run_db_id: int,
    query: str,
    mode: str = "text",         # "text" | "voice"
    system_prompt: str,
) -> list:
    """Assemble the full message list to send to the LLM.

    Order:
      SystemMessage(system_prompt)
      SystemMessage(digest_context)      ← from Redis or DB
      SystemMessage(window_summary)      ← if exists
      SystemMessage(run_id hint)
      HumanMessage / AIMessage × RECENT_WINDOW
      HumanMessage(query)               ← current turn
    """
    messages: list = []

    # 1. System prompt (persona + behaviour rules)
    messages.append(SystemMessage(content=system_prompt))

    # 2. Digest knowledge — Redis L1, fallback to DB/checkpoint
    digest_ctx = await _get_digest_context(run_db_id)
    if digest_ctx:
        messages.append(SystemMessage(
            content=f"=== Frontier AI Radar Intelligence Brief ===\n{digest_ctx}"
        ))

    # 3. Run-ID hint (tells agent which run to load if tools are called)
    messages.append(SystemMessage(content=(
        f"Active digest run ID: {run_db_id}. "
        "Call query_digest_state({run_db_id}) for AI/tech questions. "
        "For greetings or general questions respond naturally."
    )))

    # 4. Rolling window summary (older conversation, compressed)
    summary = _get_window_summary(session_id)
    if summary:
        messages.append(SystemMessage(
            content=f"=== Earlier conversation summary ===\n{summary}"
        ))

    # 5. Recent verbatim turns
    from db.chat import get_recent_messages
    recent = get_recent_messages(session_id, limit=RECENT_WINDOW)
    for m in recent:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            messages.append(AIMessage(content=m["content"]))

    # 6. Current query (clean, no prefix)
    messages.append(HumanMessage(content=query))

    logger.debug(
        "context_built",
        session_id=session_id,
        run_db_id=run_db_id,
        total_messages=len(messages),
        recent_turns=len(recent),
        has_digest=bool(digest_ctx),
        has_summary=bool(summary),
    )
    return messages


async def maybe_summarise(session_id: str, message_count: int) -> None:
    """Trigger a rolling summary when message_count is a multiple of SUMMARY_EVERY.

    Summarises the oldest messages that are NOT in the recent window, so the
    recent window always stays verbatim. Safe to call from a background task.
    """
    if message_count % SUMMARY_EVERY != 0:
        return

    try:
        from db.chat import load_session_messages, update_window_context
        from langchain_openai import ChatOpenAI
        from config.settings import settings

        # Load more messages than the recent window to find what to summarise
        all_msgs = load_session_messages(session_id, limit=RECENT_WINDOW + SUMMARY_EVERY)
        if len(all_msgs) <= RECENT_WINDOW:
            return  # Nothing old enough to summarise yet

        older = all_msgs[:-RECENT_WINDOW]  # everything except recent window

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

        # Merge with existing summary if present
        existing = _get_window_summary(session_id)
        if existing:
            merge_prompt = (
                f"Merge these two conversation summaries into one coherent summary "
                f"(under 200 words):\n\nEARLIER:\n{existing}\n\nNEWER:\n{summary_text}"
            )
            merged = await llm.ainvoke(merge_prompt)
            summary_text = merged.content.strip()

        update_window_context(session_id, summary_text)
        logger.info("context_summary_updated", session_id=session_id, length=len(summary_text))

    except Exception as exc:
        logger.warning("context_summarise_failed", session_id=session_id, error=str(exc))


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_digest_context(run_db_id: int) -> str:
    """Return a text digest context for the LLM, sourced from Redis → DB."""
    # L1: Redis pre-built context string (set by chat_agent tools / Celery worker)
    try:
        from cache.redis_client import get_digest_context
        cached = get_digest_context(run_db_id)
        if cached:
            return cached[:MAX_DIGEST_CHARS]
    except Exception:
        pass

    # L2: Redis full digest payload (written by Celery worker after pipeline)
    try:
        from cache.redis_client import get_digest_cache
        payload = get_digest_cache(run_db_id)
        if payload:
            findings = payload.get("ranked_findings", [])
            lines = [f"Total findings: {len(findings)}", ""]
            for i, f in enumerate(findings[:20], 1):
                lines.append(f"{i}. {f.get('title', 'Untitled')}")
                if f.get("why_it_matters"):
                    lines.append(f"   Why it matters: {f['why_it_matters']}")
                if f.get("source_url"):
                    lines.append(f"   Source: {f['source_url']}")
            ctx = "\n".join(lines)
            # Cache as context string for next request
            from cache.redis_client import set_digest_context
            set_digest_context(run_db_id, ctx)
            return ctx[:MAX_DIGEST_CHARS]
    except Exception:
        pass

    # L3: DB fallback
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


def _get_window_summary(session_id: str) -> Optional[str]:
    """Load the rolling conversation summary from DB."""
    try:
        from db.connection import get_session as db_session
        from sqlalchemy import text
        with db_session() as sess:
            row = sess.execute(
                text("SELECT window_context FROM ai_radar.chat_sessions WHERE id = CAST(:sid AS uuid)"),
                {"sid": session_id}
            ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _get_summary_llm(settings):
    """Return a cheap, fast LLM for summarisation (not the main reasoning model)."""
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
