"""Sentence boundary streamer — enables TTS to start before LLM finishes.

Problem
───────
ElevenLabs TTS requires complete text to generate audio.  If we wait for the
full LLM response, the user waits 3–8 seconds before hearing anything.

Solution
────────
Buffer LLM tokens as they stream in. Whenever we detect a sentence boundary
(. ! ? followed by whitespace, or a long clause ending in , ; :), yield the
buffered text immediately so TTS can start speaking it while the LLM is still
generating the rest.

Latency impact
──────────────
  Without sentence streaming: first audio after full LLM response  ~4–8 s
  With sentence streaming:    first audio after first sentence       ~1–2 s

Usage
─────
    streamer = SentenceStreamer()
    async for sentence in streamer.stream(llm_token_generator):
        audio_chunk = await tts.synthesize(sentence)
        await websocket.send_bytes(audio_chunk)
"""

from __future__ import annotations

import re
import asyncio
from typing import AsyncGenerator, AsyncIterator

# Sentence endings: ., !, ? followed by space or end-of-string
# Also yield on long pauses: ... or — (em-dash)
_HARD_BOUNDARY = re.compile(r'(?<=[.!?])\s+')
_SOFT_BOUNDARY = re.compile(r'(?<=[\,;:])\s{2,}')   # double space after comma
_MIN_CHARS      = 40    # don't emit very short fragments (e.g. "Hi.")
_MAX_CHARS      = 300   # force-flush long buffers even without a boundary


class SentenceStreamer:
    """Consume an async token stream and yield complete sentences."""

    def __init__(
        self,
        min_chars: int = _MIN_CHARS,
        max_chars: int = _MAX_CHARS,
    ):
        self._min  = min_chars
        self._max  = max_chars
        self._buf  = ""

    async def stream(
        self,
        tokens: AsyncIterator[str],
    ) -> AsyncGenerator[str, None]:
        """Yield sentences as they become complete.

        Args:
            tokens: async generator of raw LLM token strings

        Yields:
            Complete sentences / clauses ready for TTS synthesis.
        """
        self._buf = ""

        async for token in tokens:
            self._buf += token

            # Try hard boundary first (sentence-ending punctuation + space)
            if len(self._buf) >= self._min:
                parts = _HARD_BOUNDARY.split(self._buf)
                if len(parts) > 1:
                    # Yield all complete sentences; keep last fragment in buffer
                    for sentence in parts[:-1]:
                        s = sentence.strip()
                        if s:
                            yield s
                    self._buf = parts[-1]
                    continue

            # Force-flush if buffer is very long (no sentence boundary found)
            if len(self._buf) >= self._max:
                # Try to split at a soft boundary (comma/semicolon)
                parts = _SOFT_BOUNDARY.split(self._buf, maxsplit=1)
                if len(parts) == 2:
                    yield parts[0].strip()
                    self._buf = parts[1]
                else:
                    # No clean split — yield whole buffer
                    yield self._buf.strip()
                    self._buf = ""

        # Flush remaining buffer
        if self._buf.strip():
            yield self._buf.strip()
            self._buf = ""


async def collect_full_text(
    sentences: AsyncGenerator[str, None],
) -> tuple[str, list[str]]:
    """Helper: drain the sentence generator and return (full_text, sentence_list).

    Useful for saving the complete response to DB while TTS streams in parallel.
    """
    sentence_list: list[str] = []
    async for s in sentences:
        sentence_list.append(s)
    return " ".join(sentence_list), sentence_list
