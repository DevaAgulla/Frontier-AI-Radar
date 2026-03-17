"""
Dedicated thread-pool executor for CPU-bound embedding inference.

Industry pattern: isolate synchronous ML inference from the async event loop.
A fixed-size pool with `initializer` pre-loads the model in every worker thread
at pool-creation time, guaranteeing zero cold-start latency on the first request.

Architecture decisions
──────────────────────
  Pool size = 2 threads: enough for 384-dim MiniLM (≈5–15 ms/call each).
  sentence-transformers is thread-safe for inference (read-only forward pass),
  so both threads share the same in-memory model object via the singleton cache
  in core/embedder.py. No extra 90 MB per thread.

  All callers use embed_async() which submits work via loop.run_in_executor(),
  never touching the event loop from a CPU thread.

  Two timeout tiers:
    VOICE_TIMEOUT = 1.0 s  — hard budget; voice pipeline must start TTS in <2 s
    TEXT_TIMEOUT  = 3.0 s  — softer; text chat can absorb enrichment latency
  If the timeout fires, the caller skips the embedding step gracefully.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import List

import structlog

logger = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

VOICE_TIMEOUT = 1.0   # seconds — hard budget for voice hot-path
TEXT_TIMEOUT  = 3.0   # seconds — text chat budget

_POOL_WORKERS = 2

# ── Singleton pool ─────────────────────────────────────────────────────────────

_pool: concurrent.futures.ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _thread_initializer() -> None:
    """Pre-load the embedding model inside each worker thread.

    Called once per thread when the pool is created via init_pool().
    By loading here, every subsequent embed_text() call inside this thread
    hits the already-warm model — no download, no torch init, no latency spike.
    """
    try:
        from core.embedder import get_embedding_model
        get_embedding_model()
        logger.info("embedding_thread_warm")
    except Exception as exc:
        logger.warning("embedding_thread_init_failed", error=str(exc))


def init_pool() -> concurrent.futures.ThreadPoolExecutor:
    """Create (and return) the singleton embedding thread pool.

    Call once at FastAPI lifespan startup. Safe to call multiple times — idempotent.

    IMPORTANT: Python's ThreadPoolExecutor spawns threads LAZILY — the initializer
    only runs when the first task is submitted, not when the pool is created.
    We force all threads to start immediately by submitting dummy tasks so that
    _thread_initializer (which loads the 90MB SentenceTransformer model) runs
    now, not on the first user request.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                logger.info("embedding_pool_starting", workers=_POOL_WORKERS)
                _pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_POOL_WORKERS,
                    thread_name_prefix="embedder",
                    initializer=_thread_initializer,
                )
                # Force all threads to start NOW so _thread_initializer fires
                # immediately. Without this, threads are created lazily and the
                # first embed_async() call still pays the full cold-start cost.
                warmup_futs = [_pool.submit(int) for _ in range(_POOL_WORKERS)]
                concurrent.futures.wait(warmup_futs, timeout=120)
                logger.info("embedding_pool_ready", workers=_POOL_WORKERS)
    return _pool


def _pool_or_init() -> concurrent.futures.ThreadPoolExecutor:
    global _pool
    return _pool if _pool is not None else init_pool()


# ── Public API ─────────────────────────────────────────────────────────────────

async def embed_async(text: str, timeout: float = TEXT_TIMEOUT) -> List[float]:
    """Embed text asynchronously via the pre-warmed thread pool.

    Properties:
      - Never blocks the event loop (CPU work runs in executor thread)
      - Model is guaranteed warm after init_pool() — no cold-start
      - Raises asyncio.TimeoutError if embedding exceeds budget;
        callers should catch and skip the embedding step gracefully

    Args:
        text:    The text to embed.
        timeout: Max seconds to wait. Pass VOICE_TIMEOUT for voice pipeline.
    """
    loop = asyncio.get_running_loop()
    from core.embedder import embed_text
    return await asyncio.wait_for(
        loop.run_in_executor(_pool_or_init(), embed_text, text),
        timeout=timeout,
    )
