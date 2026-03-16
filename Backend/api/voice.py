"""Real-time Voice Agent — WebSocket endpoint.

WebSocket URL:  ws://host/api/v1/voice/{run_id}?user_id=<int>

Full pipeline per turn
──────────────────────
  Browser mic (PCM chunks)
    → WebSocket binary frames
    → STT session (Deepgram streaming | Whisper fallback)
    → final transcript
    → Context Manager (system + digest + summary + recent window)
    → LangGraph ReAct (VOICE_SYSTEM_PROMPT, voice-optimised)
    → token stream
    → Sentence Streamer (yield sentence by sentence)
    → ElevenLabs /stream (yield audio chunks per sentence)
    → WebSocket binary frames back to browser
    → Web Audio API queued playback

Message protocol (JSON text frames unless noted)
───────────────────────────────────────────────
  Client → Server:
    {type: "audio_chunk"}           binary frame immediately following
    {type: "interrupt"}             cancel current generation + TTS
    {type: "end_session"}           close gracefully
    (binary frame)                  raw PCM 16-bit LE 16 kHz mono

  Server → Client:
    {type: "ready"}                 session initialised
    {type: "transcript", text, is_final}   STT result
    {type: "thinking"}              LLM processing started
    {type: "text_chunk", text}      streaming LLM token (for display)
    {type: "audio_start"}           TTS sentence starting
    (binary frame)                  raw MP3 audio chunk
    {type: "audio_end"}             TTS sentence finished
    {type: "turn_done", text}       full assistant turn complete
    {type: "error", message}        non-fatal error
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = structlog.get_logger()


# ── Markdown → plain speech ───────────────────────────────────────────────────

def _strip_for_tts(text: str) -> str:
    """Remove all markdown/formatting so TTS reads clean spoken English.

    Handles: **bold**, *italic*, # headings, - bullets, 1. numbered lists,
    [Finding N], [label](url), backticks, __SOURCES_JSON__, excessive whitespace.
    """
    # Remove __SOURCES_JSON__ block
    text = re.sub(r"\n?__SOURCES_JSON__:\[.*?\]", "", text, flags=re.DOTALL)

    # Remove markdown links → keep label only: [label](url) → label
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Remove [Finding N] / [N] style brackets entirely
    text = re.sub(r"\[\s*(?:Finding\s*)?\d+\s*\]", "", text, flags=re.IGNORECASE)

    # Remove remaining square brackets content that looks like references
    text = re.sub(r"\[[^\]]{0,40}\]", "", text)

    # Bold / italic: **text** → text,  *text* → text,  __text__ → text
    text = re.sub(r"\*{1,3}([^*]+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+?)_{1,2}", r"\1", text)

    # Headings: # Heading → Heading
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Numbered list items: "1. " or "2. " → just the text
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Bullet / dash list items: "- " or "* " → just the text
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)

    # Inline code / code blocks
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)

    # Horizontal rules
    text = re.sub(r"^[-_*]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Collapse multiple blank lines / leading-trailing whitespace per line
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


# ── WebSocket handler ─────────────────────────────────────────────────────────

async def voice_session(
    websocket: WebSocket,
    run_id: int,
    user_id: Optional[int] = None,
) -> None:
    """Main entry point — manage one voice session from connect to disconnect."""
    await websocket.accept()

    session_id: Optional[str]     = None
    current_task: Optional[asyncio.Task] = None   # current generate+speak task
    interrupted  = False

    # ── Resolve session ───────────────────────────────────────────────────────
    try:
        from db.chat import get_or_create_session
        info       = get_or_create_session(run_id=run_id, user_id=user_id)
        session_id = info["session_id"]
        is_new     = info.get("is_new", False)
    except Exception as exc:
        await _send_json(websocket, {"type": "error", "message": f"Session error: {exc}"})
        await websocket.close()
        return

    await _send_json(websocket, {
        "type":       "ready",
        "session_id": session_id,
        "is_new":     is_new,
    })
    logger.info("voice_session_open", run_id=run_id, session_id=session_id)

    # ── STT callbacks ─────────────────────────────────────────────────────────
    transcript_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    def on_transcript(text: str, is_final: bool) -> None:
        asyncio.create_task(_send_json(
            websocket,
            {"type": "transcript", "text": text, "is_final": is_final},
        ))
        if is_final:
            transcript_queue.put_nowait((text, True))

    # ── STT session ───────────────────────────────────────────────────────────
    from core.stt import STTSession
    stt = await STTSession.create(on_transcript=on_transcript)

    expect_audio_binary = False  # set True after receiving audio_chunk JSON

    try:
        async for raw in _ws_iter(websocket):

            # Binary frame = PCM audio
            if isinstance(raw, bytes):
                await stt.send_audio(raw)
                continue

            # Text frame = JSON control message
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "audio_chunk":
                # Next binary frame will be audio
                expect_audio_binary = True

            elif msg_type == "user_text":
                # Browser-side STT sent the transcript directly (Web Speech API)
                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                # Cancel any ongoing generation from a previous turn
                if current_task and not current_task.done():
                    current_task.cancel()

                # Start generation + TTS pipeline
                current_task = asyncio.create_task(
                    _generate_and_speak(
                        websocket  = websocket,
                        query      = text,
                        run_db_id  = run_id,
                        session_id = session_id,
                    )
                )

            elif msg_type == "end_of_speech":
                # Legacy: server-side STT path (Deepgram / Whisper)
                await stt.finalize()
                # Wait for final transcript (max 5 s)
                try:
                    text, _ = await asyncio.wait_for(transcript_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    await _send_json(websocket, {"type": "error", "message": "STT timeout"})
                    continue

                # Cancel any ongoing generation from previous turn
                if current_task and not current_task.done():
                    current_task.cancel()

                # Start generation + TTS pipeline for this turn
                current_task = asyncio.create_task(
                    _generate_and_speak(
                        websocket   = websocket,
                        query       = text,
                        run_db_id   = run_id,
                        session_id  = session_id,
                    )
                )

            elif msg_type == "greeting":
                # Auto-greeting on new sessions — bypasses LLM for instant TTS
                if current_task and not current_task.done():
                    current_task.cancel()
                current_task = asyncio.create_task(
                    _speak_only(websocket, _GREETING_TEXT, session_id=session_id)
                )

            elif msg_type == "interrupt":
                # User interrupted — cancel ongoing speech
                if current_task and not current_task.done():
                    current_task.cancel()
                    await _send_json(websocket, {"type": "interrupted"})

            elif msg_type == "end_session":
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("voice_session_error", error=str(exc))
    finally:
        if current_task and not current_task.done():
            current_task.cancel()
        await stt.close()
        logger.info("voice_session_closed", session_id=session_id)


# ── LLM + TTS pipeline ────────────────────────────────────────────────────────

async def _generate_and_speak(
    *,
    websocket: WebSocket,
    query: str,
    run_db_id: int,
    session_id: str,
) -> None:
    """Run one complete voice turn: context → LLM → sentence stream → TTS."""
    from agents.chat_agent import VOICE_SYSTEM_PROMPT
    from core.context_manager import build_messages, maybe_summarise
    from core.sentence_streamer import SentenceStreamer
    from core.tts_stream import stream_tts, resolve_elevenlabs_key, resolve_voice_id
    from db.chat import save_message

    await _send_json(websocket, {"type": "thinking"})

    # ── Build context ─────────────────────────────────────────────────────────
    messages = await build_messages(
        session_id    = session_id,
        run_db_id     = run_db_id,
        query         = query,
        mode          = "voice",
        system_prompt = VOICE_SYSTEM_PROMPT,
    )

    # ── LLM streaming ─────────────────────────────────────────────────────────
    from pipeline.runner import create_chat_initial_state

    chat_state = create_chat_initial_state(
        run_db_id     = run_db_id,
        chat_query    = query,
        chat_session_id = session_id,
        chat_mode     = "voice",
    )
    # Inject pre-built messages (context manager output) directly
    chat_state["messages"] = messages

    graph      = _get_voice_graph()   # cached — zero rebuild cost after first call
    invoke_cfg = {"configurable": {"thread_id": f"voice_{session_id}"}}

    # ── Sentence stream → TTS ─────────────────────────────────────────────────
    from config.settings import settings as _settings
    api_key  = resolve_elevenlabs_key() if _settings.enable_elevenlabs else None
    voice_id = resolve_voice_id()

    full_text    = ""
    partial_saved = False
    streamer     = SentenceStreamer()

    # ── Tool status labels sent to the frontend during tool calls ──────────────
    _TOOL_LABELS: dict[str, tuple[str, str]] = {
        "query_digest_state": ("Searching the digest…",  "Digest loaded"),
        "search_web":         ("Searching the web…",     "Search complete"),
    }

    async def _token_gen():
        """Yield LLM tokens; emit tool_status frames as side-effects."""
        nonlocal full_text
        async for event in graph.astream_events(chat_state, config=invoke_cfg, version="v2"):
            evt = event["event"]

            if evt == "on_chat_model_stream":
                token = event["data"]["chunk"].content
                if token:
                    full_text += token
                    await _send_json(websocket, {"type": "text_chunk", "text": token})
                    yield token

            elif evt == "on_tool_start":
                tool_name = event.get("name", "")
                label     = _TOOL_LABELS.get(tool_name, (f"Using {tool_name}…", "Done"))[0]
                await _send_json(websocket, {
                    "type":      "tool_status",
                    "tool_name": tool_name,
                    "phase":     "start",
                    "label":     label,
                })

            elif evt == "on_tool_end":
                tool_name = event.get("name", "")
                label     = _TOOL_LABELS.get(tool_name, ("", f"{tool_name} done"))[1]
                await _send_json(websocket, {
                    "type":      "tool_status",
                    "tool_name": tool_name,
                    "phase":     "end",
                    "label":     label,
                })

    try:
        async for sentence in streamer.stream(_token_gen()):
            clean = _strip_for_tts(sentence)
            if not clean:
                continue

            if not api_key:
                await _send_json(websocket, {"type": "audio_sentence", "text": clean})
                continue

            await _send_json(websocket, {"type": "audio_start", "text": clean})
            try:
                async for audio_chunk in stream_tts(
                    clean,
                    api_key  = api_key,
                    voice_id = voice_id,
                ):
                    await websocket.send_bytes(audio_chunk)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("tts_chunk_failed", error=str(exc))
            await _send_json(websocket, {"type": "audio_end"})

        await _send_json(websocket, {"type": "turn_done", "text": _strip_for_tts(full_text)})

        # ── Persist complete turn ──────────────────────────────────────────────
        save_message(session_id, "user",      query,     mode="voice")
        count = save_message(session_id, "assistant", full_text, mode="voice")
        partial_saved = True
        if count % 5 == 0:
            asyncio.create_task(maybe_summarise(session_id, count))

    except asyncio.CancelledError:
        # User interrupted mid-turn — save whatever was generated so the next
        # query has context of the partial response.
        if full_text.strip() and not partial_saved:
            try:
                save_message(session_id, "user",      query,                    mode="voice")
                save_message(session_id, "assistant", full_text + " [paused]",  mode="voice")
                logger.info("voice_partial_saved", session_id=session_id, chars=len(full_text))
            except Exception as save_exc:
                logger.warning("voice_partial_save_failed", error=str(save_exc))
        raise  # re-raise so the Task cancellation propagates correctly

    except Exception as exc:
        logger.warning("voice_save_message_failed", error=str(exc))


# ── Greeting (instant TTS, no LLM) ────────────────────────────────────────────

_GREETING_TEXT = (
    "Hey! I'm Radar, your AI voice assistant. "
    "What would you like to know about today's digest?"
)


async def _speak_only(
    websocket: WebSocket,
    text: str,
    session_id: Optional[str] = None,
) -> None:
    """Speak fixed text via TTS without going through the LLM.

    Used for the auto-greeting on new sessions — delivers audio in ~300 ms
    instead of the 1-3 s a full LLM round-trip would take.

    Saves the greeting to DB so that IDB audio key indices stay consistent
    with the message count returned by load_voice_history() on reload.
    """
    from core.tts_stream import stream_tts, resolve_elevenlabs_key, resolve_voice_id

    api_key  = resolve_elevenlabs_key()
    voice_id = resolve_voice_id()

    await _send_json(websocket, {"type": "thinking"})
    await _send_json(websocket, {"type": "text_chunk", "text": text})

    if api_key:
        await _send_json(websocket, {"type": "audio_start", "text": text})
        try:
            async for chunk in stream_tts(text, api_key=api_key, voice_id=voice_id):
                await websocket.send_bytes(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("greeting_tts_failed", error=str(exc))
        await _send_json(websocket, {"type": "audio_end"})

    await _send_json(websocket, {"type": "turn_done", "text": text})

    # Persist so load_voice_history() includes it and IDB key 0 → greeting audio
    if session_id:
        try:
            from db.chat import save_message
            save_message(session_id, "assistant", text, mode="voice")
        except Exception as exc:
            logger.warning("greeting_save_failed", error=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, data: dict) -> None:
    """Send a JSON control frame; ignore errors on closed sockets."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(json.dumps(data))
    except Exception:
        pass


async def _ws_iter(ws: WebSocket):
    """Yield raw messages (str or bytes) until disconnect."""
    while True:
        try:
            data = await ws.receive()
            if "text" in data:
                yield data["text"]
            elif "bytes" in data:
                yield data["bytes"]
            elif data.get("type") == "websocket.disconnect":
                break
        except WebSocketDisconnect:
            break
        except Exception:
            break


_cached_checkpointer = None
_cached_voice_graph  = None   # graph is expensive to build — create once per process

def _get_checkpointer():
    """Return the shared LangGraph checkpointer (lazily initialised)."""
    global _cached_checkpointer
    return _cached_checkpointer

def _get_voice_graph():
    """Return a cached LangGraph graph for voice sessions.

    Creating the full radar graph (importing all 12 agents) takes 200-500 ms.
    Caching it eliminates that overhead on every voice turn.
    """
    global _cached_voice_graph
    if _cached_voice_graph is None:
        from pipeline.graph import create_radar_graph
        _cached_voice_graph = create_radar_graph(checkpointer=_get_checkpointer())
        logger.info("voice_graph_cached")
    return _cached_voice_graph
