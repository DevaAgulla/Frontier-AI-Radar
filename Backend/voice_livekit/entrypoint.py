"""LiveKit worker process entrypoint — STANDALONE fallback.

NOTE: The LiveKit worker is now embedded inside FastAPI's lifespan event
(api/main.py). You do NOT need to run this file separately.

This file only exists as a standalone fallback for debugging the worker
in isolation, without starting the full FastAPI server.

Usage (standalone debug only):
    cd Backend
    python -m voice_livekit.entrypoint dev    # hot-reload for development
    python -m voice_livekit.entrypoint start  # production

Required environment variables (Backend/.env):
    LIVEKIT_URL=wss://your-project.livekit.cloud
    LIVEKIT_API_KEY=APIxxxxxxxx
    LIVEKIT_API_SECRET=your_secret
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# ── path setup: make Backend the import root ───────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load Backend/.env before anything else
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def main() -> None:
    try:
        from livekit.agents import WorkerOptions, cli
    except ImportError:
        print(
            "\nERROR: LiveKit Agents not installed.\n"
            "Run:  pip install 'livekit-agents[deepgram,elevenlabs]' livekit-plugins-langchain\n"
        )
        sys.exit(1)

    from voice_livekit.agent import entrypoint

    livekit_url    = os.environ.get("LIVEKIT_URL", "")
    livekit_api_key = os.environ.get("LIVEKIT_API_KEY", "")
    livekit_secret  = os.environ.get("LIVEKIT_API_SECRET", "")

    if not all([livekit_url, livekit_api_key, livekit_secret]):
        print(
            "\nERROR: Missing LiveKit credentials.\n"
            "Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in Backend/.env\n"
        )
        sys.exit(1)

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            ws_url=livekit_url,
            api_key=livekit_api_key,
            api_secret=livekit_secret,
        )
    )


if __name__ == "__main__":
    main()
