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
from typing import Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = structlog.get_logger()


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
    except Exception as exc:
        await _send_json(websocket, {"type": "error", "message": f"Session error: {exc}"})
        await websocket.close()
        return

    await _send_json(websocket, {"type": "ready", "session_id": session_id})
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

            elif msg_type == "end_of_speech":
                # User finished speaking — finalise STT
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
    from agents.chat_agent import VOICE_SYSTEM_PROMPT, query_digest_state, search_web
    from agents.base_agent import build_react_agent
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
    # Use a minimal graph invocation — voice just needs the chat agent
    from pipeline.runner import create_chat_initial_state
    from pipeline.graph import create_radar_graph

    chat_state = create_chat_initial_state(
        run_db_id     = run_db_id,
        chat_query    = query,
        chat_session_id = session_id,
        chat_mode     = "voice",
    )
    # Inject pre-built messages (context manager output) directly
    chat_state["messages"] = messages

    checkpointer = _get_checkpointer()
    graph        = create_radar_graph(checkpointer=checkpointer)
    invoke_cfg   = {"configurable": {"thread_id": f"voice_{session_id}"}}

    # ── Sentence stream → TTS ─────────────────────────────────────────────────
    api_key  = resolve_elevenlabs_key()
    voice_id = resolve_voice_id()

    full_text  = ""
    streamer   = SentenceStreamer()

    async def _token_gen():
        """Yield tokens from LangGraph astream_events."""
        nonlocal full_text
        async for event in graph.astream_events(chat_state, config=invoke_cfg, version="v2"):
            if event["event"] == "on_chat_model_stream":
                token = event["data"]["chunk"].content
                if token:
                    full_text += token
                    # Send text chunk to UI for display alongside voice
                    await _send_json(websocket, {"type": "text_chunk", "text": token})
                    yield token

    async for sentence in streamer.stream(_token_gen()):
        if not api_key:
            # No TTS key — just send text
            await _send_json(websocket, {"type": "audio_sentence", "text": sentence})
            continue

        await _send_json(websocket, {"type": "audio_start", "text": sentence})
        try:
            async for audio_chunk in stream_tts(
                sentence,
                api_key  = api_key,
                voice_id = voice_id,
            ):
                await websocket.send_bytes(audio_chunk)
        except asyncio.CancelledError:
            raise   # propagate cancellation (user interrupted)
        except Exception as exc:
            logger.warning("tts_chunk_failed", error=str(exc))
        await _send_json(websocket, {"type": "audio_end"})

    await _send_json(websocket, {"type": "turn_done", "text": full_text})

    # ── Persist messages ──────────────────────────────────────────────────────
    try:
        save_message(session_id, "user",      query,     mode="voice")
        count = save_message(session_id, "assistant", full_text, mode="voice")
        if count % 5 == 0:
            asyncio.create_task(maybe_summarise(session_id, count))
    except Exception as exc:
        logger.warning("voice_save_message_failed", error=str(exc))


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

def _get_checkpointer():
    """Return the shared LangGraph checkpointer (lazily initialised)."""
    global _cached_checkpointer
    # The voice module reuses whatever checkpointer the API has already built.
    # In practice, main.py's _get_chat_graph() sets this up at startup.
    return _cached_checkpointer
