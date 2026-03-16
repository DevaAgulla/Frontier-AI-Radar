"""Simple test script to verify the pipeline runs end-to-end.

Usage:
    python test_pipeline.py                          # default: research only
    python test_pipeline.py --mode full              # all agents
    python test_pipeline.py --mode competitor        # single agent
    python test_pipeline.py --mode research,model    # two agents
"""

import argparse
import asyncio
import sys
from pathlib import Path

# psycopg v3 requires SelectorEventLoop on Windows (incompatible with ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.runner import run_radar

VALID_AGENTS = {"research", "competitor", "model", "benchmark"}

# Map of finding keys per agent, for printing summary
FINDING_KEYS = {
    "research": "research_findings",
    "competitor": "competitor_findings",
    "model": "provider_findings",
    "benchmark": "hf_findings",
}


async def test_pipeline(mode: str = "research", since_days: int = 1):
    """Test the pipeline with a given mode."""
    print("=" * 60)
    print(f"Testing Frontier AI Radar Pipeline (mode: {mode})")
    print("=" * 60)
    print()

    try:
        print("Starting pipeline run...")
        final_state = await run_radar(mode=mode, since_days=since_days)

        print("\n" + "=" * 60)
        print("Pipeline Execution Complete!")
        print("=" * 60)
        print(f"Run ID: {final_state.get('run_id')}")

        # Show findings per active agent
        active = VALID_AGENTS if mode == "full" else {m.strip() for m in mode.split(",")}
        for agent_name in sorted(active):
            key = FINDING_KEYS.get(agent_name, "")
            if key:
                count = len(final_state.get(key, []))
                print(f"  {agent_name:20s} findings: {count}")

        print(f"Ranked Findings: {len(final_state.get('ranked_findings', []))}")
        print(f"Errors: {len(final_state.get('errors', []))}")
        print(f"Email Status: {final_state.get('email_status', 'unknown')}")
        print(f"PDF Path: {final_state.get('pdf_path', 'none')}")

        if final_state.get("errors"):
            print("\nErrors encountered:")
            for error in final_state["errors"]:
                print(f"  - {error.get('agent_name')}: {error.get('error_message')}")

        print("\n✅ Pipeline test completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Pipeline test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test the Frontier AI Radar pipeline end-to-end",
        epilog=(
            "Examples:\n"
            "  python test_pipeline.py --mode full\n"
            "  python test_pipeline.py --mode competitor\n"
            "  python test_pipeline.py --mode research,competitor\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode", default="research",
        help=(
            "Run mode: 'full' or comma-separated agents. "
            "Valid: research, competitor, model, benchmark "
            "(default: research)"
        ),
    )
    parser.add_argument(
        "--since-days", type=int, default=1,
        help="How many days back to search (default: 1)",
    )
    args = parser.parse_args()

    success = asyncio.run(test_pipeline(mode=args.mode, since_days=args.since_days))
    sys.exit(0 if success else 1)
