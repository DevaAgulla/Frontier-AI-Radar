"""ElevenLabs streaming TTS — yields audio chunks as they arrive.

Uses the ElevenLabs /stream endpoint so the first audio chunk arrives in
~150–300 ms, long before the full sentence audio is ready.

Flow:
  sentence text → POST /v1/text-to-speech/{voice_id}/stream
               → response.iter_bytes(chunk_size=CHUNK_BYTES)
               → yield bytes chunks to caller (WebSocket sender)

This module is intentionally transport-agnostic — the caller decides whether
to send chunks over a WebSocket, write to a file, or buffer them.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional

import httpx
import structlog

logger = structlog.get_logger()

# ElevenLabs streaming endpoint
_TTS_URL      = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
_CHUNK_BYTES  = 512        # smaller = lower first-byte latency
_TIMEOUT      = 15.0       # seconds — allow for slow network

# Voice settings (match existing voice/generate_voice_digest.py defaults)
_VOICE_SETTINGS = {
    "stability":         0.5,
    "similarity_boost":  0.75,
    "use_speaker_boost": True,
}


async def stream_tts(
    text: str,
    *,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_turbo_v2",   # turbo for lowest latency
    output_format: str = "mp3_22050_32", # lower bitrate = smaller chunks = lower latency
) -> AsyncGenerator[bytes, None]:
    """Yield raw audio bytes as they stream from ElevenLabs.

    Caller example (WebSocket):
        async for chunk in stream_tts(sentence, api_key=key, voice_id=vid):
            await ws.send_bytes(chunk)

    Args:
        text:          The sentence to synthesise.
        api_key:       ElevenLabs API key.
        voice_id:      ElevenLabs voice ID.
        model_id:      Model — eleven_turbo_v2 has lowest latency (~150 ms).
        output_format: Audio format string.

    Yields:
        Raw audio bytes (MP3 by default).
    """
    if not text.strip():
        return

    url = _TTS_URL.format(voice_id=voice_id)
    headers = {
        "xi-api-key":   api_key,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }
    payload = {
        "text":           text,
        "model_id":       model_id,
        "voice_settings": _VOICE_SETTINGS,
        "output_format":  output_format,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.warning(
                        "tts_stream_http_error",
                        status=resp.status_code,
                        body=body[:200],
                    )
                    return
                async for chunk in resp.aiter_bytes(_CHUNK_BYTES):
                    if chunk:
                        yield chunk
    except httpx.TimeoutException:
        logger.warning("tts_stream_timeout", text_len=len(text))
    except Exception as exc:
        logger.warning("tts_stream_failed", error=str(exc))


async def synthesise_to_bytes(
    text: str,
    *,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_turbo_v2",
) -> bytes:
    """Convenience wrapper: collect all chunks into a single bytes object.

    Use this when you need the complete audio file (e.g. voice mode REST endpoint).
    Use ``stream_tts`` directly for WebSocket streaming.
    """
    chunks: list[bytes] = []
    async for chunk in stream_tts(text, api_key=api_key, voice_id=voice_id, model_id=model_id):
        chunks.append(chunk)
    return b"".join(chunks)


def resolve_elevenlabs_key() -> Optional[str]:
    """Resolve ElevenLabs API key: voice/config.env first, then settings."""
    # 1. voice/config.env (has higher priority per existing convention)
    try:
        from pathlib import Path
        cfg_path = Path(__file__).resolve().parent.parent / "voice" / "config.env"
        if cfg_path.exists():
            for line in cfg_path.read_text().splitlines():
                if line.startswith("ELEVENLABS_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    if key:
                        return key
    except Exception:
        pass
    # 2. Pydantic settings
    try:
        from config.settings import settings
        if settings.elevenlabs_api_key:
            return settings.elevenlabs_api_key
    except Exception:
        pass
    return None


def resolve_voice_id() -> str:
    """Resolve ElevenLabs voice ID from config or settings."""
    try:
        from pathlib import Path
        cfg_path = Path(__file__).resolve().parent.parent / "voice" / "config.env"
        if cfg_path.exists():
            for line in cfg_path.read_text().splitlines():
                if line.startswith("VOICE_PRESET="):
                    preset = line.split("=", 1)[1].strip()
                    presets = {
                        "rachel": "21m00Tcm4TlvDq8ikWAM",
                        "adam":   "pNInz6obpgDQGcFmaJgB",
                    }
                    if preset in presets:
                        return presets[preset]
    except Exception:
        pass
    try:
        from config.settings import settings
        return settings.elevenlabs_voice_id
    except Exception:
        return "21m00Tcm4TlvDq8ikWAM"  # rachel — default
