"""LiveKit Voice Agent — wraps the existing LangGraph ReAct pipeline.

This is a *parallel prototype* — it does NOT replace the existing WebSocket
voice endpoint (Backend/api/voice.py). Both can run simultaneously so you can
A/B test latency and reliability.

Architecture:
  Browser/mobile ──WebRTC──► LiveKit Room
                                  │
                         LiveKit Worker Process (this file)
                                  │
                    ┌─────────────┴─────────────┐
                    │      AgentSession          │
                    │  STT: Deepgram nova-3      │
                    │  LLM: LangGraphAdapter     │◄─── existing ReAct graph
                    │  TTS: ElevenLabs Flash/v2  │         + all digest tools
                    │  Turn: Deepgram VAD        │
                    └───────────────────────────┘

Dependencies (add to requirements.txt before running):
    livekit-agents>=0.8.0
    livekit-agents[deepgram]
    livekit-agents[elevenlabs]
    livekit-plugins-langchain>=0.1.0   # LangGraphAdapter

Usage:
    cd Backend
    python -m voice_livekit.entrypoint dev    # local hot-reload
    python -m voice_livekit.entrypoint start  # production

Environment variables required (add to Backend/.env):
    LIVEKIT_URL=wss://your-project.livekit.cloud
    LIVEKIT_API_KEY=APIxxxxxxxx
    LIVEKIT_API_SECRET=your_secret
    DEEPGRAM_API_KEY=...          (already used by existing voice agent)
    ELEVENLABS_API_KEY=...        (already in voice/config.env)
"""
from __future__ import annotations

import asyncio
import os
import logging
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ── Voice ID map (mirrors existing VOICE_PRESETS) ─────────────────────────────
VOICE_IDS = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",   # calm, professional female (default)
    "adam":   "pNInz6obpgDQGcFmaJgB",   # deep, authoritative male
    "elli":   "MF3mGyEYCl7XYWbV9V6O",   # bright, energetic female
}


def _resolve_elevenlabs_key() -> str:
    """Resolve ElevenLabs API key — voice/config.env takes priority over env."""
    from pathlib import Path
    config_env = Path(__file__).parent.parent / "voice" / "config.env"
    if config_env.exists():
        for line in config_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key and key not in ("", "your_api_key_here"):
                    return key
    return os.environ.get("ELEVENLABS_API_KEY", "")


def _resolve_deepgram_key() -> str:
    return os.environ.get("DEEPGRAM_API_KEY", "")


# ── LangGraph adapter ─────────────────────────────────────────────────────────

def build_langchain_llm(run_id: str, user_id: Optional[int] = None):
    """
    Returns a LangChain-compatible LLM that proxies through the existing
    LangGraph ReAct voice pipeline (context manager + digest tools + memory).

    LiveKit's LangGraphAdapter wraps this compiled graph as an LLM plugin,
    preserving all tool calls, RAG, and session memory.
    """
    from context.context_manager import ContextManager
    from core.llm_client import build_llm

    # Build the context-aware chat callable that the existing voice agent uses.
    # This reuses all existing business logic: persona, digest context, memory.
    ctx_mgr = ContextManager(run_id=int(run_id), user_id=user_id)

    llm = build_llm(streaming=True)

    # Wrap as a simple LangChain Runnable — LiveKit LangGraphAdapter calls .ainvoke()
    from langchain_core.runnables import RunnableLambda

    async def _voice_chain(messages, **kwargs):
        """Route through context manager → LLM, mirroring the WS voice pipeline."""
        # Extract the latest user message
        user_text = ""
        for m in reversed(messages):
            role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else None)
            if role in ("human", "user"):
                user_text = getattr(m, "content", None) or (m.get("content", "") if isinstance(m, dict) else "")
                break

        system_prompt, history = await ctx_mgr.build_context(user_text)
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        full_messages = [SystemMessage(content=system_prompt)] + history + [HumanMessage(content=user_text)]
        response = await llm.ainvoke(full_messages)
        await ctx_mgr.save_turn(user_text, response.content)
        return response

    return RunnableLambda(_voice_chain)


# ── Agent entrypoint ──────────────────────────────────────────────────────────

async def entrypoint(ctx):
    """
    Called by the LiveKit worker for each new room connection.

    ctx.room.name is expected to be:  "radar-<run_id>[-<user_id>]"
    e.g.  "radar-42"  or  "radar-42-7"
    """
    try:
        from livekit.agents import AgentSession, Agent
        from livekit.plugins import deepgram, elevenlabs
        from livekit.plugins.langchain import LLMAdapter
    except ImportError as exc:
        logger.error(
            "LiveKit packages not installed. "
            "Run: pip install 'livekit-agents[deepgram,elevenlabs]' livekit-plugins-langchain",
            error=str(exc),
        )
        return

    # Parse run_id / user_id from room name
    parts = ctx.room.name.replace("radar-", "").split("-")
    run_id  = parts[0] if parts else "0"
    user_id: Optional[int] = int(parts[1]) if len(parts) > 1 else None

    logger.info("LiveKit agent starting", room=ctx.room.name, run_id=run_id, user_id=user_id)

    # Resolve credentials
    el_key      = _resolve_elevenlabs_key()
    deepgram_key = _resolve_deepgram_key()

    # Voice preset — default rachel; room metadata can override
    voice_name = (ctx.room.metadata or "rachel").strip() or "rachel"
    voice_id   = VOICE_IDS.get(voice_name, VOICE_IDS["rachel"])

    # Build LLM adapter around existing pipeline
    langchain_runnable = build_langchain_llm(run_id, user_id)
    llm = LLMAdapter(langchain_runnable)

    # Configure the LiveKit AgentSession with STT + LLM + TTS
    session = AgentSession(
        stt=deepgram.STT(
            api_key=deepgram_key,
            model="nova-3",
            language="en-US",
        ),
        llm=llm,
        tts=elevenlabs.TTS(
            api_key=el_key,
            voice_id=voice_id,
            model="eleven_turbo_v2",          # lowest latency
            encoding="mp3_44100_128",
        ),
        # Deepgram VAD for reliable turn detection (replaces Web Speech API barge-in)
        vad=deepgram.VAD(api_key=deepgram_key),
    )

    await session.start(ctx.room, agent=Agent(instructions=(
        "You are the Frontier AI Radar voice assistant. "
        "Answer questions about today's AI intelligence brief concisely and professionally. "
        "Keep responses under 3 sentences unless the user asks for detail."
    )))
    logger.info("LiveKit agent session started", room=ctx.room.name)
