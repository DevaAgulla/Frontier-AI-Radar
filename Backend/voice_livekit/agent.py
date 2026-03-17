"""LiveKit Voice Agent — wraps the existing LangGraph ReAct pipeline.

Architecture:
  Browser/mobile ──WebRTC──► LiveKit Room
                                   │
                          LiveKit Worker Process (this file)
                                   │
                     ┌─────────────┴─────────────┐
                     │      AgentSession          │
                     │  STT: Deepgram nova-3      │
                     │  LLM: RadarLLMPlugin       │◄─── full ReAct graph
                     │  TTS: ElevenLabs Flash     │      + all digest tools
                     │  VAD: Deepgram/Silero      │      + context manager
                     └───────────────────────────┘

This is a PARALLEL implementation. The existing WebSocket voice endpoint
(Backend/api/voice.py) remains fully operational as fallback.

Dependencies:
    livekit-agents>=0.8.0
    livekit-agents[deepgram]
    livekit-agents[elevenlabs]

Usage:
    cd Backend
    python -m voice_livekit.entrypoint dev    # local hot-reload
    python -m voice_livekit.entrypoint start  # production

Environment variables (Backend/.env):
    LIVEKIT_URL=wss://your-project.livekit.cloud
    LIVEKIT_API_KEY=APIxxxxxxxx
    LIVEKIT_API_SECRET=your_secret
    DEEPGRAM_API_KEY=...
    ELEVENLABS_API_KEY=...
"""
from __future__ import annotations

import asyncio
import os
import json
import logging
from typing import AsyncIterable, Optional

import structlog

logger = structlog.get_logger(__name__)

# ── Register LiveKit plugins on the main thread (required by livekit-agents v1.x)
try:
    from livekit.agents import AgentSession, Agent, RoomInputOptions
    from livekit.plugins import deepgram, elevenlabs
except ImportError:
    pass  # will be caught at runtime in entrypoint if missing

# ── Voice preset map (mirrors existing VOICE_PRESETS in seed + tts_stream.py) ──

VOICE_IDS = {
    "rachel":               "21m00Tcm4TlvDq8ikWAM",   # calm, professional female (default)
    "rachel_professional":  "21m00Tcm4TlvDq8ikWAM",
    "adam":                 "pNInz6obpgDQGcFmaJgB",   # deep, authoritative male
    "adam_calm":            "pNInz6obpgDQGcFmaJgB",
    "elli":                 "MF3mGyEYCl7XYWbV9V6O",   # bright, energetic female
    "elli_energetic":       "MF3mGyEYCl7XYWbV9V6O",
}


def _resolve_elevenlabs_key() -> str:
    """Resolve ElevenLabs API key — voice/config.env takes priority."""
    from pathlib import Path
    config_env = Path(__file__).parent.parent / "voice" / "config.env"
    if config_env.exists():
        for line in config_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key and key not in ("", "your_api_key_here"):
                    return key
    # Fall back to Backend/.env (subprocess-safe)
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key and key not in ("", "your_api_key_here"):
                    return key
    return os.environ.get("ELEVENLABS_API_KEY", "")


def _resolve_deepgram_key() -> str:
    from pathlib import Path
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPGRAM_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    return key
    return os.environ.get("DEEPGRAM_API_KEY", "")


# ── Cached voice graph (same pattern as api/voice.py) ─────────────────────────

_cached_voice_graph = None

def _get_voice_graph():
    """Return a cached LangGraph graph for voice sessions.

    Building the full radar graph (importing all agents) takes 200-500ms.
    Caching it eliminates that overhead after the first connection.
    """
    global _cached_voice_graph
    if _cached_voice_graph is None:
        from pipeline.graph import create_radar_graph
        _cached_voice_graph = create_radar_graph(checkpointer=None)
        logger.info("livekit_voice_graph_cached")
    return _cached_voice_graph


# ── LiveKit LLM Plugin — wraps existing pipeline ──────────────────────────────

VOICE_IDENTITY_PREFIX = """\
IMPORTANT — YOU ARE A VOICE AGENT: The user is speaking to you via microphone. \
Deepgram speech-to-text converts their voice to text before you see it. \
Your text response will be read aloud by ElevenLabs TTS. You CAN hear the user \
(via STT). Never say "I'm a text-based AI" or "I can't hear you" — you are \
operating in a fully voice-enabled pipeline right now.

"""

VOICE_PERSONA_SUFFIX = """

Additional voice behavior rules (CRITICAL — follow absolutely):
- Write ONLY natural spoken English sentences. No lists, no structure, no markdown.
- NEVER use asterisks (*), hashes (#), dashes (-), brackets ([]), or any symbol.
- NEVER use numbered lists or bullet points.
- Keep responses to 3–4 conversational sentences. Start directly with the key insight.
- Never read out URLs, file names, timestamps, or raw numbers.
- Speak naturally — use contractions, vary sentence length, avoid robotic phrasing.
- If you don't have relevant information, say "I don't see that in today's digest" and move on.
- Never end with "Would you like me to..." or offer menus of options."""


def build_radar_llm_plugin(run_id: int, session_id: str, user_id: Optional[int] = None, room=None, persona_prompt: Optional[str] = None):
    """
    Build a LiveKit-compatible LLM plugin that proxies through the full
    LangGraph ReAct voice pipeline.

    Unlike the old prototype that bypassed the ReAct graph, this implementation:
    - Uses the same create_radar_graph() as the WebSocket voice endpoint
    - Preserves all tool calls (query_digest_state, search_web)
    - Preserves context manager (session history, digest context, persona)
    - Streams tokens back to LiveKit as they are generated

    Returns a livekit.agents.llm.LLM subclass instance.
    """
    try:
        from livekit.agents import llm as lk_llm
        from livekit.agents.llm import ChatContext, ChatMessage
    except ImportError as exc:
        raise ImportError(
            "livekit-agents not installed. "
            "Run: pip install 'livekit-agents[deepgram,elevenlabs]'"
        ) from exc

    class RadarLLMPlugin(lk_llm.LLM):
        """
        LiveKit LLM plugin backed by the Frontier AI Radar LangGraph pipeline.

        LiveKit calls chat() for each turn. This method:
        1. Extracts the latest user message from LiveKit's ChatContext
        2. Builds full context (session history + digest + persona) via build_messages()
        3. Runs the ReAct graph via astream_events()
        4. Yields LLMStream chunks back to LiveKit for TTS + transcript
        """

        def chat(
            self,
            *,
            chat_ctx: ChatContext,
            tools=None,
            conn_options=None,
            **kwargs,
        ) -> "RadarLLMStream":
            from livekit.agents import DEFAULT_API_CONNECT_OPTIONS
            return RadarLLMStream(
                chat_ctx=chat_ctx,
                tools=tools or [],
                conn_options=conn_options or DEFAULT_API_CONNECT_OPTIONS,
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                room=room,
                persona_prompt=persona_prompt,
            )

    class RadarLLMStream(lk_llm.LLMStream):
        """Async iterator that streams LangGraph tokens to LiveKit."""

        def __init__(
            self,
            *,
            chat_ctx: ChatContext,
            tools: list,
            conn_options,
            run_id: int,
            session_id: str,
            user_id: Optional[int],
            room=None,
            persona_prompt: Optional[str] = None,
        ):
            super().__init__(llm=RadarLLMPlugin(), chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
            self._run_id        = run_id
            self._session_id    = session_id
            self._user_id       = user_id
            self._room          = room
            self._persona_prompt = persona_prompt

        async def _run(self) -> None:
            """Produce LLM chunks. Called by LiveKit's internal loop."""
            from agents.chat_agent import VOICE_SYSTEM_PROMPT
            from core.context_manager import build_messages, maybe_summarise
            from db.chat import save_message
            from pipeline.runner import create_chat_initial_state
            import livekit.agents.llm as lk_llm
            import uuid

            # Helper: send a data packet to the room so the frontend can update UI
            async def _pub(data: dict) -> None:
                if not self._room:
                    return
                try:
                    payload = json.dumps(data).encode()
                    await self._room.local_participant.publish_data(payload, reliable=True)
                except Exception:
                    pass  # non-critical — UI falls back gracefully

            # Extract the latest user utterance from LiveKit's chat context
            # v1.x: messages() is a method, content is list[ChatContent] — use text_content
            user_text = ""
            for msg in reversed(self._chat_ctx.messages()):
                if msg.role == "user":
                    user_text = msg.text_content or ""
                    break

            if not user_text.strip():
                return

            # ── Utterance guard: reject VAD noise fragments.
            # With 800ms endpointing, split utterances rarely happen. But if Deepgram
            # still fires a final event for a misrecognised noise burst (e.g. "Me through",
            # "Uh", "Okay"), we drop it here rather than waste an LLM call.
            # Single meaningful words ("Hi", "Thanks", "Yes") are 1–2 words and valid.
            # Noise artifacts are typically 1–3 words with no semantic intent — a 2-word
            # minimum with a punctuation heuristic catches most of them.
            words = user_text.strip().split()
            if len(words) < 2 and not any(c in user_text for c in "?!."):
                logger.info("livekit_utterance_fragment_dropped",
                            text=user_text, run_id=self._run_id)
                return

            logger.info("livekit_llm_turn", run_id=self._run_id, session=self._session_id,
                        chars=len(user_text))

            await _pub({"type": "thinking"})

            # Build context — use persona prompt + voice identity + voice suffix if available
            effective_prompt = (
                (VOICE_IDENTITY_PREFIX + self._persona_prompt + VOICE_PERSONA_SUFFIX)
                if self._persona_prompt
                else VOICE_SYSTEM_PROMPT
            )
            messages = await build_messages(
                session_id    = self._session_id,
                run_db_id     = self._run_id,
                query         = user_text,
                mode          = "voice",
                system_prompt = effective_prompt,
            )

            chat_state = create_chat_initial_state(
                run_db_id       = self._run_id,
                chat_query      = user_text,
                chat_session_id = self._session_id,
                chat_mode       = "voice",
            )
            chat_state["messages"] = messages

            graph      = _get_voice_graph()
            invoke_cfg = {"configurable": {"thread_id": f"lk_voice_{self._session_id}"}}

            _TOOL_LABELS: dict[str, tuple[str, str]] = {
                "query_digest_state": ("Searching the digest…",  "Digest loaded"),
                "search_web":         ("Searching the web…",     "Search complete"),
            }

            full_text = ""

            try:
                async for event in graph.astream_events(chat_state, config=invoke_cfg, version="v2"):
                    evt = event["event"]

                    if evt == "on_chat_model_stream":
                        token = event["data"]["chunk"].content
                        if token:
                            full_text += token
                            # Yield chunk to LiveKit — it feeds this into TTS
                            self._event_ch.send_nowait(
                                lk_llm.ChatChunk(
                                    id=str(uuid.uuid4()),
                                    delta=lk_llm.ChoiceDelta(
                                        role="assistant",
                                        content=token,
                                    ),
                                )
                            )
                            # Fire-and-forget word token to frontend for real-time
                            # transcript sync. Text appears as LLM generates it,
                            # ~500ms ahead of TTS audio — visually synced.
                            asyncio.create_task(_pub({"type": "word_token", "text": token}))

                    elif evt == "on_tool_start":
                        tool_name = event.get("name", "")
                        label = _TOOL_LABELS.get(tool_name, (f"Using {tool_name}…", "Done"))[0]
                        await _pub({"type": "tool_status", "tool_name": tool_name, "phase": "start", "label": label})

                    elif evt == "on_tool_end":
                        tool_name = event.get("name", "")
                        label = _TOOL_LABELS.get(tool_name, ("", f"{tool_name} done"))[1]
                        await _pub({"type": "tool_status", "tool_name": tool_name, "phase": "end", "label": label})

            except asyncio.CancelledError:
                # User interrupted mid-turn — save partial response
                if full_text.strip():
                    try:
                        save_message(self._session_id, "user",      user_text,                 mode="voice")
                        save_message(self._session_id, "assistant", full_text + " [paused]",   mode="voice")
                    except Exception as save_err:
                        logger.warning("livekit_partial_save_failed", error=str(save_err))
                return

            # Persist complete turn
            try:
                save_message(self._session_id, "user",      user_text,  mode="voice")
                count = save_message(self._session_id, "assistant", full_text, mode="voice")
                if count % 5 == 0:
                    asyncio.create_task(maybe_summarise(self._session_id, count))
                # Signal turn complete to the frontend
                await _pub({"type": "turn_done", "text": full_text})
            except Exception as db_err:
                logger.warning("livekit_save_failed", error=str(db_err))

    return RadarLLMPlugin()


# ── Agent entrypoint ──────────────────────────────────────────────────────────

async def entrypoint(ctx):
    """
    Called by the LiveKit worker for each new room connection.

    Room name convention: "radar-{run_id}" or "radar-{run_id}-{user_id}"
    Room/participant metadata: voice preset name (e.g. "rachel_professional")
    """
    # Parse run_id / user_id from room name ("radar-42" or "radar-42-7")
    name_parts = ctx.room.name.replace("radar-", "").split("-")
    run_id_str = name_parts[0] if name_parts else "0"
    user_id: Optional[int] = int(name_parts[1]) if len(name_parts) > 1 else None
    run_id = int(run_id_str) if run_id_str.isdigit() else 0

    # Resolve session_id from DB (same as WebSocket voice endpoint)
    session_id = ""
    try:
        from db.chat import get_or_create_session
        info = get_or_create_session(run_id=run_id, user_id=user_id)
        session_id = info["session_id"]
        logger.info("livekit_session_resolved", session_id=session_id, run_id=run_id)
    except Exception as exc:
        logger.warning("livekit_session_error", error=str(exc))
        session_id = f"lk-{run_id}-{user_id or 0}"

    # Resolve credentials
    el_key       = _resolve_elevenlabs_key()
    deepgram_key = _resolve_deepgram_key()

    # Resolve voice preset + persona from room metadata.
    #
    # Resolution order (most-to-least reliable):
    #   1. ctx.room.metadata  — set via LiveKit Server API in the token endpoint
    #   2. First remote participant's metadata — set via AccessToken.with_metadata()
    #      (fallback: participant may join before room metadata propagates)
    #
    raw_metadata = (ctx.room.metadata or "").strip()

    if not raw_metadata:
        # Room metadata not yet propagated — check already-connected participants
        for _p in list(ctx.room.remote_participants.values()):
            if _p.metadata:
                raw_metadata = _p.metadata.strip()
                logger.info("livekit_metadata_from_participant", identity=_p.identity)
                break

    if not raw_metadata:
        # No participant in room yet — wait up to 8 s for first one to join
        try:
            _first = await asyncio.wait_for(ctx.wait_for_participant(), timeout=8.0)
            raw_metadata = (_first.metadata or "").strip()
            logger.info("livekit_metadata_from_wait", identity=_first.identity)
        except (asyncio.TimeoutError, Exception):
            pass

    try:
        meta_obj   = json.loads(raw_metadata) if raw_metadata else {}
        voice_name = meta_obj.get("voice", "rachel") or "rachel"
        persona_id = meta_obj.get("persona_id", "") or ""
    except (json.JSONDecodeError, TypeError):
        voice_name = raw_metadata or "rachel"
        persona_id = ""

    voice_id = VOICE_IDS.get(voice_name, VOICE_IDS["rachel"])

    # Load persona system prompt from DB if persona_id provided
    persona_prompt: Optional[str] = None
    if persona_id:
        try:
            from db.connection import get_session as db_session
            from sqlalchemy import text as sa_text
            with db_session() as sess:
                row = sess.execute(sa_text("""
                    SELECT digest_system_prompt
                    FROM   ai_data_radar.persona_templates
                    WHERE  persona_type = :pid AND is_system_default = TRUE
                    LIMIT  1
                """), {"pid": persona_id}).fetchone()
            if row and row[0]:
                persona_prompt = row[0]
                logger.info("livekit_persona_loaded", persona_id=persona_id)
        except Exception as exc:
            logger.warning("livekit_persona_load_failed", persona_id=persona_id, error=str(exc))

    logger.info("livekit_agent_starting",
                room=ctx.room.name, run_id=run_id, user_id=user_id,
                voice=voice_name, persona=persona_id, session=session_id)

    # Build the LLM plugin backed by our full LangGraph pipeline.
    # Pass ctx.room so the plugin can publish DataPackets (tool_status, turn_done) to the frontend.
    radar_llm = build_radar_llm_plugin(run_id=run_id, session_id=session_id, user_id=user_id, room=ctx.room, persona_prompt=persona_prompt)

    # Configure AgentSession with STT + our LLM + TTS
    # Note: deepgram.VAD was removed in livekit-agents v1.x.
    # Turn detection is handled by Deepgram STT (vad_events=True default) + AgentSession.
    session = AgentSession(
        stt=deepgram.STT(
            api_key=deepgram_key,
            model="nova-3",
            language="en-US",
            punctuate=True,
            interim_results=True,
            # ── Endpointing: wait 2500ms of silence before closing a turn.
            # Default is ~200-300ms which splits natural mid-sentence pauses
            # into separate turns → duplicate LLM calls → duplicate responses.
            # 2–3 seconds lets the user finish a full thought comfortably.
            endpointing_ms=2500,
        ),
        llm=radar_llm,
        tts=elevenlabs.TTS(
            api_key=el_key,
            voice_id=voice_id,
            model="eleven_flash_v2_5",
            encoding="mp3_44100_128",
        ),
    )

    await session.start(
        Agent(
            instructions=_build_agent_instructions(),
        ),
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )

    logger.info("livekit_agent_session_started", room=ctx.room.name)


def _build_agent_instructions() -> str:
    """Return the agent instructions (system prompt for the agent persona).

    This is the LiveKit-level persona that governs barge-in behaviour and
    turn-taking. The actual content prompt is injected by RadarLLMPlugin
    via VOICE_SYSTEM_PROMPT + context manager.
    """
    return (
        "You are Radar, the Frontier AI Radar voice assistant for Centific. "
        "You help executives and researchers understand today's AI intelligence brief. "
        "Keep responses under 4 sentences unless asked for detail. "
        "Speak naturally, conversationally, as if talking to a colleague. "
        "Never read out lists, URLs, or raw numbers. "
        "If interrupted, stop immediately and address what the user just said."
    )
