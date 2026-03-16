"""Uvicorn launcher — sets Windows-compatible event loop policy before startup.

On Windows, Python defaults to ProactorEventLoop which is incompatible with
psycopg v3 (used by LangGraph AsyncPostgresSaver checkpointer).
WindowsSelectorEventLoopPolicy must be set BEFORE uvicorn creates its loop —
setting it inside main.py is too late because uvicorn initialises the loop
during CLI startup, before any app module is imported.

Usage (replaces `uvicorn api.main:app --reload`):
    python run.py
    python run.py --port 8080
    python run.py --no-reload
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",     default="0.0.0.0")
    parser.add_argument("--port",     type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    # reload=True spawns a subprocess on Windows — that subprocess starts fresh
    # without our WindowsSelectorEventLoopPolicy, so psycopg v3 gets ProactorEventLoop.
    # Reload is a dev convenience only; run without it (single process = policy sticks).
    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=False,
        loop="none",   # prevent uvicorn from overriding WindowsSelectorEventLoopPolicy
    )
