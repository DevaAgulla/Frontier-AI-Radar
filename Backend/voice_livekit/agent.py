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

# ── LiveKit core imports (always available if livekit-agents is installed) ──────
from livekit.agents import AgentSession, Agent
from livekit.agents.voice.room_io import RoomOptions

# ── Plugin imports — done at module level so the IPC worker subprocess has them
# available. If these fail the worker logs a clear ImportError rather than a
# silent NameError at runtime.
from livekit.plugins import deepgram, elevenlabs

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
    # ── Per-session debounce lock ─────────────────────────────────────────────
    # Deepgram can fire two SpeechFinalEvents for a single natural-speech
    # utterance that has a mid-sentence pause (e.g. "about [pause] the update").
    # Both events cause AgentSession to call llm.chat() → _run() → LangGraph
    # twice, producing duplicate responses.
    # This lock prevents concurrent _run() calls for the same session. If a
    # turn is already in progress when a new chat() arrives, the new _run()
    # will see the lock and drop the fragment as a duplicate.
    _turn_lock = asyncio.Lock()
    try:
        from livekit.agents import llm as lk_llm
        from livekit.agents.llm import ChatContext
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
                turn_lock=_turn_lock,
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
            turn_lock: asyncio.Lock,
        ):
            super().__init__(llm=RadarLLMPlugin(), chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
            self._run_id        = run_id
            self._session_id    = session_id
            self._user_id       = user_id
            self._room          = room
            self._persona_prompt = persona_prompt
            self._turn_lock     = turn_lock

        async def _run(self) -> None:
            """Produce LLM chunks. Called by LiveKit's internal loop."""
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

            # ── Debounce: drop duplicate turns from split utterances.
            # Deepgram can fire two SpeechFinalEvents for one natural sentence that
            # has a mid-sentence pause (e.g. "about [pause] the update"). Both events
            # cause AgentSession to call _run() concurrently. The lock ensures only
            # ONE turn runs at a time; the second call sees the lock is taken and drops
            # itself as a fragment rather than issuing a duplicate LLM call.
            if self._turn_lock.locked():
                logger.info("livekit_utterance_fragment_dropped_busy",
                            text=user_text[:60], run_id=self._run_id)
                return

            async with self._turn_lock:
                await self._run_locked(user_text, _pub)

        async def _run_locked(self, user_text: str, _pub) -> None:
            """Inner body of _run — executes only when the per-session turn lock is held."""
            from agents.chat_agent import VOICE_SYSTEM_PROMPT
            from core.context_manager import build_messages, maybe_summarise
            from db.chat import save_message
            from pipeline.runner import create_chat_initial_state
            import livekit.agents.llm as lk_llm
            import uuid

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
    # Connect to the room and subscribe to audio tracks.
    # This MUST be called before accessing ctx.room.remote_participants or
    # publishing local tracks. Without it, RoomIO cannot set up the audio
    # pipeline and TTS audio will never reach the participant.
    from livekit.agents import AutoSubscribe
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

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

    # Guard: warn loudly if ElevenLabs key is missing — this causes silent TTS
    # failure (AgentSession swallows the 401 if no "error" listener is attached).
    if not el_key:
        logger.error("livekit_elevenlabs_key_missing",
                     detail="ELEVENLABS_API_KEY not found — TTS will fail silently")

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
            # ── Endpointing: 1200ms gives room for natural mid-sentence pauses
            # (e.g. "about [pause] the update"). 800ms was too aggressive —
            # a 300-500ms hesitation pause split the utterance into two turns.
            # utterance_end_ms does not exist in this plugin version — omitted.
            endpointing_ms=1200,
            # smart_format helps Deepgram recognise incomplete sentences and
            # avoid premature endpointing on short unfinished phrases.
            smart_format=True,
            # Filler words (um/uh/ah) reset the silence timer — disable them
            # so they don't delay endpointing or create spurious utterances.
            filler_words=False,
        ),
        llm=radar_llm,
        tts=elevenlabs.TTS(
            # api_key: only pass if non-empty — if empty, plugin reads
            # ELEVENLABS_API_KEY env var. Passing "" explicitly causes a
            # 401 that is swallowed silently → text shows but no audio.
            **({"api_key": el_key} if el_key else {}),
            voice_id=voice_id,
            model="eleven_flash_v2_5",
            # PCM bypasses the MP3 decode step inside AudioByteStream.
            # MP3 transcoding in the LiveKit pipeline is a common silent
            # failure point; PCM is raw samples that feed directly into
            # the AudioSource with no intermediate decode step.
            encoding="pcm_16000",
            # Lower streaming latency + smaller first TTS chunk → first
            # audio arrives ~200ms sooner after LLM generation ends.
            streaming_latency=3,
            chunk_length_schedule=[50, 120, 200, 260],
        ),
        # ── Bug 2 fix: explicit turn-detection and interruption parameters.
        # min_endpointing_delay=0.5 — 500ms natural pause before agent replies (default).
        # allow_interruptions=True  — user can interrupt mid-response (default).
        # min_interruption_duration=0.5 — user must speak 500ms to count as interrupt (default).
        # min_interruption_words=2  — user must say ≥2 words; prevents single-word
        #   noise ("uh", "mm") from cancelling the agent's reply.
        min_endpointing_delay=0.5,
        allow_interruptions=True,
        min_interruption_duration=0.5,
        min_interruption_words=2,
    )

    # ── Bug 3 fix: audio-text sync via agent_state_changed events.
    # The LLM streams tokens ~500ms ahead of TTS audio. Without this, frontend
    # text appears before the voice starts — they are out of sync.
    # Solution: emit tts_started when AgentState transitions to "speaking"
    # (i.e., when ElevenLabs audio actually begins playing in the room) and
    # tts_stopped when it transitions away from "speaking".
    # The frontend buffers word_token packets until tts_started fires, then
    # flushes the buffer — text appears exactly when the voice begins.
    @session.on("agent_state_changed")
    def on_agent_state_changed(ev) -> None:
        if ev.new_state == "speaking":
            payload = json.dumps({"type": "tts_started"}).encode()
            asyncio.create_task(
                ctx.room.local_participant.publish_data(payload, reliable=True)
            )
        elif ev.old_state == "speaking":
            payload = json.dumps({"type": "tts_stopped"}).encode()
            asyncio.create_task(
                ctx.room.local_participant.publish_data(payload, reliable=True)
            )

    # Surface TTS / STT / LLM errors that AgentSession would otherwise swallow.
    # Without this, a 401 from ElevenLabs (bad API key) or a Deepgram disconnect
    # produces no log output and the agent appears to work (text shows) but
    # audio is completely silent.
    @session.on("error")
    def on_session_error(ev) -> None:
        logger.error("livekit_agent_error",
                     error=str(ev.error),
                     source=type(ev.source).__name__)

    await session.start(
        Agent(
            instructions=_build_agent_instructions(),
        ),
        room=ctx.room,
        room_options=RoomOptions(),
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
