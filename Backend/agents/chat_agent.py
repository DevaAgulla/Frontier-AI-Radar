"""Chat Intelligence Agent — LangGraph ReAct agent for interactive Q&A over radar digests.

Architecture
------------
This agent is built with the same ``build_react_agent`` factory used by every other
agent in the system (research_intel, competitor_intel, etc.).  It is intentionally a
**separate graph** from the digest pipeline — this is LangGraph's recommended
multi-agent pattern, not a two-system split:

  Digest graph  (thread_id = "run_{run_db_id}")
      Runs ONCE per schedule/trigger.
      Full RadarState checkpointed to PostgreSQL after every node.

  Chat graph    (thread_id = "chat_{session_id}")
      Runs per user message, in real-time.
      Uses the SAME AsyncPostgresSaver — reads digest state via tool.
      Conversation turns checkpointed automatically — no separate DB/Redis needed.

Cross-graph state access
------------------------
``query_digest_state(run_db_id)`` reads from the digest graph's checkpoint using
``aget_state(thread_id="run_{run_db_id}")``.  This is the explicit, tool-mediated
link between the two graphs — the multi-agent handshake.

Tools
-----
1. query_digest_state(run_db_id) — loads ranked_findings from LangGraph checkpoint;
                                    falls back to DB query if checkpoint unavailable.
2. search_web(query)             — Tavily web search for out-of-digest questions;
                                    called only when LLM decides digest lacks the answer.

Conversation memory
-------------------
LangGraph AsyncPostgresSaver checkpoints the full MessagesState after every turn.
Loading prior conversation = ``chat_agent.aget_state(thread_id="chat_{session_id}")``.
No separate chat_messages table writes are needed — LangGraph is the source of truth.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import structlog
from langchain_core.tools import tool

from agents.base_agent import build_react_agent
from config.settings import settings

logger = structlog.get_logger()


# ── System prompts ─────────────────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = """\
You are Radar, a sharp and friendly AI analyst built into Centific's Frontier AI Radar \
platform. You help COO, CEO, Sales, and Account Management teams stay on top of AI \
developments — but you're also just a good conversational partner.

Personality:
- Warm, direct, and engaging — like a knowledgeable colleague, not a corporate system.
- Use natural language. Say "Here's what I found" not "Based on the analysis provided".
- Match the user's energy — casual question gets a casual answer, detailed question gets depth.
- Remember things the user tells you (like their name) and use them naturally.

How to decide what to do:
- Greetings, personal questions, chitchat → just respond naturally, no tools needed.
- Questions about AI news, models, companies, benchmarks, strategy → call query_digest_state \
  first to check the digest, then answer. If the digest doesn't cover it, call search_web.
- General knowledge questions unrelated to AI → answer from your own knowledge, no tools needed.

Tool usage:
- query_digest_state: Call this when the question is about AI/tech topics — pass the \
  run_db_id from the user message. Only call it ONCE per response.
- search_web: Call this only when the digest doesn't have the answer and you need \
  current information. Don't call it for conversational or general questions.

Formatting:
- Short answers for simple questions. Deeper answers for complex ones.
- Use **bold** for company names, model names, and key numbers.
- Use bullet points only when listing 3+ items — not for everything.
- Never start with "Certainly!", "Of course!", "I apologize" or similar filler phrases.
- Cite digest findings as [Finding N] when referencing them.
"""

VOICE_SYSTEM_PROMPT = """\
You are Radar, a friendly AI analyst for Centific's Frontier AI Radar, speaking \
directly to a senior executive via voice. You ARE a voice agent — the user's speech \
is transcribed by Deepgram STT and your response is read aloud by ElevenLabs TTS. \
Never say "I'm a text-based AI" or "I can't hear you" — you are operating in a \
fully voice-enabled pipeline.

CRITICAL — your response will be read aloud by a text-to-speech engine. Follow these rules absolutely:
- Write ONLY natural spoken English sentences. No lists, no structure, no formatting whatsoever.
- NEVER use asterisks (*), hashes (#), dashes (-), brackets ([]), underscores (_), or any symbol.
- NEVER use numbered lists (1. 2. 3.) or bullet points.
- NEVER say "Finding 3" or "[Finding N]" — just describe it naturally.
- NEVER end with "Would you like me to..." offer menus or options.
- Speak in flowing paragraphs as if talking to a colleague face-to-face.
- 3 to 5 conversational sentences. Start directly with the key insight.
- For AI/tech questions: call query_digest_state first, then answer naturally.
- For greetings or personal questions: just respond naturally, no tools needed.

Example good response: "Today's digest has three standout papers. The most interesting is XSkill, which lets AI agents learn continuously from both experience and skills without needing parameter updates. There's also CLASP, a security system that protects hybrid language models from hidden state poisoning using an XGBoost classifier. Finally, LabShield introduces a safety benchmark for lab robotics with 164 tasks focused on preventing irreversible errors."
"""


# ── Module-level singletons (set once by create_chat_agent) ───────────────────

_checkpointer = None       # AsyncPostgresSaver shared with digest pipeline
_digest_graph  = None      # created lazily for aget_state calls in query_digest_state


async def _get_digest_graph():
    """Lazy-create a read-only instance of the digest graph for aget_state calls."""
    global _digest_graph, _checkpointer
    if _digest_graph is None:
        from pipeline.graph import create_radar_graph
        _digest_graph = create_radar_graph(checkpointer=_checkpointer)
    return _digest_graph


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
async def query_digest_state(run_db_id: int) -> str:
    """Load the full Frontier AI Radar intelligence brief for a completed digest run.

    Call this when the question is about AI news, models, companies, benchmarks,
    or strategy. Returns numbered findings with titles, impact scores, what changed,
    why it matters, and source URLs.

    Do NOT call this for greetings, personal questions, or general knowledge topics.

    Args:
        run_db_id: The integer digest run ID provided in the system context message.
    """
    global _checkpointer

    logger.info("chat_query_digest_start", run_db_id=run_db_id)
    findings: list = []
    digest_markdown: str = ""

    # ── Primary path: LangGraph cross-graph state access ──────────────────────
    # Reads from the digest run's checkpoint (thread_id = "run_{run_db_id}").
    # This is the designed link between the two graphs — no extra DB hit needed
    # after the first run, because the full RadarState is already persisted.
    if _checkpointer is not None:
        try:
            digest_graph = await _get_digest_graph()
            snap = await digest_graph.aget_state(
                {"configurable": {"thread_id": f"run_{run_db_id}"}}
            )
            if snap and snap.values:
                findings       = snap.values.get("ranked_findings", [])
                digest_markdown = snap.values.get("digest_markdown", "")
                logger.info(
                    "chat_digest_from_checkpoint",
                    run_db_id=run_db_id,
                    findings_count=len(findings),
                )
        except Exception as exc:
            logger.warning("chat_checkpoint_load_failed", run_db_id=run_db_id, error=str(exc))

    # ── Fallback: DB query if checkpoint unavailable or empty ─────────────────
    # Happens when: checkpointer is None, checkpoint tables not yet created,
    # or the run pre-dates the LangGraph migration.
    if not findings and not digest_markdown:
        try:
            from db.connection import get_session as db_session
            from db.models import Finding as DBFinding, Run

            with db_session() as session:
                run = session.get(Run, run_db_id)
                if not run:
                    return f"No radar run found with ID {run_db_id}."

                db_findings = (
                    session.query(DBFinding)
                    .filter(DBFinding.run_id == run_db_id)
                    .order_by(
                        DBFinding.rank.asc().nullslast(),
                        DBFinding.impact_score.desc(),
                    )
                    .limit(30)
                    .all()
                )
                logger.info(
                    "chat_digest_from_db",
                    run_db_id=run_db_id,
                    findings_count=len(db_findings),
                )
                return _format_db_findings(run, db_findings)

        except Exception as exc:
            logger.error("chat_db_fallback_failed", run_db_id=run_db_id, error=str(exc))
            return f"Could not load digest for run {run_db_id}: {exc}"

    return _format_state_findings(run_db_id, findings, digest_markdown)


@tool
async def search_web(query: str) -> str:
    """Search the internet for current AI news, model releases, benchmark results,
    or company announcements NOT covered in the digest brief.

    Call this ONLY when query_digest_state confirmed the topic is not in the digest.

    Args:
        query: A specific, targeted search query (not the user's raw question).
    """
    if not settings.tavily_api_key:
        logger.warning("chat_search_web_skipped", reason="TAVILY_API_KEY not set")
        return "Web search is not available — TAVILY_API_KEY is not configured."
    try:
        from tavily import AsyncTavilyClient  # type: ignore

        logger.info("chat_search_web_start", query=query)
        client  = AsyncTavilyClient(api_key=settings.tavily_api_key)
        results = await client.search(query, max_results=5)
        hits    = results.get("results", [])
        if not hits:
            logger.info("chat_search_web_empty", query=query)
            return "No relevant results found for that query."

        logger.info("chat_search_web_done", query=query, hits=len(hits))
        clean_urls: list[str] = []
        lines = ["**Live web search results:**"]
        for r in hits[:5]:
            # Sanitise content — strip any embedded "Source:" lines to avoid
            # the backend regex capturing false URLs from the snippet text.
            content = r.get("content", "")[:350]
            content = "\n".join(
                ln for ln in content.splitlines()
                if not ln.strip().lower().startswith("source:")
            )
            lines.append(f"- **{r.get('title', 'Untitled')}**: {content}")
            url = (r.get("url") or "").strip().rstrip(".,;:)>]\"'")
            if url:
                clean_urls.append(url)
                lines.append(f"  Source: {url}")

        # Append a machine-readable block so the backend can extract exact URLs
        # without relying on regex over potentially noisy content.
        lines.append(f"\n__SOURCES_JSON__:{json.dumps(clean_urls)}")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("chat_search_web_failed", error=str(exc))
        return f"Web search failed: {exc}"


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _format_state_findings(run_db_id: int, findings: list, digest_markdown: str) -> str:
    """Format ranked_findings TypedDict list (from RadarState) as LLM context."""
    if not findings:
        if digest_markdown:
            # Trim to avoid exceeding context limits
            return f"# Frontier AI Radar — Run {run_db_id}\n\n{digest_markdown[:8000]}"
        return f"No findings available for run {run_db_id}."

    lines = [
        f"# Frontier AI Radar Intelligence Brief — Run {run_db_id}",
        f"Total findings: {len(findings)}",
        "",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(f"## {i}. {f.get('title', 'Untitled')}")
        lines.append(
            f"Agent: {f.get('agent_source', '?')} | "
            f"Impact: {float(f.get('impact_score', 0)):.2f} | "
            f"Confidence: {f.get('confidence', 'MEDIUM')}"
        )
        if f.get("what_changed"):
            lines.append(f"**What changed**: {f['what_changed']}")
        if f.get("why_it_matters"):
            lines.append(f"**Why it matters**: {f['why_it_matters']}")
        if f.get("evidence_snippet"):
            lines.append(f"**Evidence**: {f['evidence_snippet']}")
        if f.get("source_url"):
            lines.append(f"Source: {f['source_url']}")
        lines.append("")
    return "\n".join(lines)


def _format_db_findings(run, db_findings: list) -> str:
    """Format DB Finding ORM objects as LLM context (checkpoint-unavailable fallback)."""
    date_label = run.started_at.strftime("%B %d, %Y") if run.started_at else "Unknown date"
    lines = [
        f"# Frontier AI Radar Intelligence Brief — {date_label}",
        f"Total findings: {len(db_findings)}",
        "",
    ]
    for i, f in enumerate(db_findings, 1):
        meta: dict = {}
        try:
            meta = json.loads(f.metadata_) if f.metadata_ else {}
        except Exception:
            pass
        lines.append(f"## {i}. {meta.get('title', f.title or 'Untitled')}")
        lines.append(
            f"Agent: {f.agent_name} | "
            f"Impact: {float(f.impact_score or 0):.2f} | "
            f"Confidence: {f.confidence or 'MEDIUM'}"
        )
        if f.what_changed:
            lines.append(f"**What changed**: {f.what_changed}")
        if f.why_it_matters:
            lines.append(f"**Why it matters**: {f.why_it_matters}")
        if f.evidence:
            lines.append(f"**Evidence**: {f.evidence}")
        if f.source_url:
            lines.append(f"Source: {f.source_url}")
        lines.append("")
    return "\n".join(lines)


# ── Agent factory ──────────────────────────────────────────────────────────────

def create_chat_agent(checkpointer=None):
    """Create the LangGraph ReAct chat agent for interactive digest Q&A.

    Uses the same ``build_react_agent`` factory as all other Frontier AI Radar agents.
    The agent graph uses MessagesState — LangGraph manages conversation history
    natively via the PostgreSQL checkpointer.

    Args:
        checkpointer: AsyncPostgresSaver (shared with digest pipeline).
                      Enables:
                        - Conversation history per thread_id = "chat_{session_id}"
                        - Cross-graph digest state reads via query_digest_state tool

    Returns:
        Compiled LangGraph agent ready for ainvoke / astream_events.
    """
    global _checkpointer
    _checkpointer = checkpointer  # make available to query_digest_state tool

    return build_react_agent(
        system_prompt=CHAT_SYSTEM_PROMPT,
        tools=[query_digest_state, search_web],
        checkpointer=checkpointer,
    )
