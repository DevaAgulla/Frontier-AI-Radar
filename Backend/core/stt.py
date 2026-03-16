"""Speech-to-Text abstraction layer.

Supports two providers with automatic fallback:

  1. Deepgram (streaming WebSocket) — PRIMARY
     - ~200 ms to first partial transcript
     - True streaming: words arrive as user speaks
     - Requires DEEPGRAM_API_KEY in .env

  2. OpenAI Whisper via OpenRouter — FALLBACK
     - Non-streaming: buffers audio then transcribes
     - ~800 ms latency
     - Uses existing OPENROUTER_API_KEY

Provider selection:
  - If DEEPGRAM_API_KEY is set → Deepgram
  - Otherwise → Whisper (buffered, higher latency)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from typing import AsyncGenerator, Callable, Optional

import structlog

logger = structlog.get_logger()


# ── Public interface ──────────────────────────────────────────────────────────

class STTSession:
    """Manages an STT session for one voice interaction turn.

    Usage (Deepgram):
        session = await STTSession.create(on_transcript=handler)
        await session.send_audio(pcm_bytes)
        await session.finalize()          # signals end of speech
        await session.close()

    on_transcript(text, is_final) is called for every recognised segment.
    """

    def __init__(self, on_transcript: Callable[[str, bool], None]):
        self._on_transcript = on_transcript
        self._provider: Optional[str] = None
        self._dg_ws    = None        # Deepgram WebSocket
        self._buf      = bytearray() # audio buffer for Whisper fallback
        self._closed   = False

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        on_transcript: Callable[[str, bool], None],
        sample_rate: int = 16000,
        language: str = "en",
    ) -> "STTSession":
        session = cls(on_transcript)
        await session._init(sample_rate=sample_rate, language=language)
        return session

    async def _init(self, sample_rate: int, language: str) -> None:
        """Try Deepgram first; fall back to Whisper."""
        from config.settings import settings
        dg_key = getattr(settings, "deepgram_api_key", None)

        if dg_key:
            try:
                await self._init_deepgram(dg_key, sample_rate, language)
                self._provider = "deepgram"
                logger.info("stt_provider_deepgram")
                return
            except Exception as exc:
                logger.warning("deepgram_init_failed", error=str(exc))

        # Whisper fallback — no init needed; buffer accumulates audio
        self._provider = "whisper"
        logger.info("stt_provider_whisper_fallback")

    # ── Audio input ───────────────────────────────────────────────────────────

    async def send_audio(self, raw_bytes: bytes) -> None:
        """Send a chunk of raw PCM/WebM audio."""
        if self._closed:
            return
        if self._provider == "deepgram" and self._dg_ws:
            await self._dg_send(raw_bytes)
        else:
            self._buf.extend(raw_bytes)

    async def finalize(self) -> None:
        """Signal end-of-speech; blocks until final transcript arrives."""
        if self._closed:
            return
        if self._provider == "deepgram" and self._dg_ws:
            await self._dg_finalize()
        else:
            # Whisper: transcribe the entire buffer now
            if self._buf:
                transcript = await _whisper_transcribe(bytes(self._buf))
                if transcript:
                    self._on_transcript(transcript, True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._dg_ws:
            try:
                await self._dg_ws.close()
            except Exception:
                pass
            self._dg_ws = None

    # ── Deepgram internals ────────────────────────────────────────────────────

    async def _init_deepgram(self, api_key: str, sample_rate: int, language: str) -> None:
        import websockets
        url = (
            f"wss://api.deepgram.com/v1/listen"
            f"?model=nova-2"
            f"&language={language}"
            f"&sample_rate={sample_rate}"
            f"&encoding=linear16"
            f"&channels=1"
            f"&interim_results=true"
            f"&endpointing=300"      # ms of silence = end of utterance
            f"&smart_format=true"
        )
        headers = {"Authorization": f"Token {api_key}"}
        self._dg_ws = await websockets.connect(url, extra_headers=headers)
        # Start background task to read transcripts
        asyncio.create_task(self._dg_recv_loop())

    async def _dg_send(self, audio: bytes) -> None:
        try:
            await self._dg_ws.send(audio)
        except Exception as exc:
            logger.warning("deepgram_send_failed", error=str(exc))

    async def _dg_finalize(self) -> None:
        """Send CloseStream message and wait for final transcript."""
        try:
            await self._dg_ws.send(json.dumps({"type": "CloseStream"}))
            # Give Deepgram 3 s to send the final result
            await asyncio.sleep(3)
        except Exception:
            pass

    async def _dg_recv_loop(self) -> None:
        """Background loop: receive Deepgram results and call on_transcript."""
        try:
            async for raw in self._dg_ws:
                try:
                    msg = json.loads(raw)
                    alt = (msg.get("channel", {})
                               .get("alternatives", [{}])[0])
                    text     = alt.get("transcript", "").strip()
                    is_final = msg.get("is_final", False)
                    if text:
                        self._on_transcript(text, is_final)
                except Exception:
                    pass
        except Exception:
            pass  # connection closed normally


# ── Whisper fallback ──────────────────────────────────────────────────────────

async def _whisper_transcribe(audio_bytes: bytes) -> str:
    """Transcribe buffered audio using OpenAI Whisper via OpenRouter."""
    try:
        import httpx
        from config.settings import settings

        # Build minimal WAV wrapper around raw PCM for Whisper
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)   # 16-bit PCM
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)
        wav_io.seek(0)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                files={"file": ("audio.wav", wav_io, "audio/wav")},
                data={"model": "whisper-1"},
            )
        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
        logger.warning("whisper_failed", status=resp.status_code)
        return ""
    except Exception as exc:
        logger.warning("whisper_exception", error=str(exc))
        return ""
