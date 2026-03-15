"""Conditional routing functions for LangGraph.

These are used as edge condition functions in the state graph.
Each function inspects the current RadarState and returns the
name of the next node(s) to execute.
"""

from typing import Literal
from pipeline.state import RadarState
import structlog

logger = structlog.get_logger()


# ── ENTRY ROUTING — chat vs digest ────────────────────────────────────────────

def route_from_start(state: RadarState) -> str:
    """Route at START: chat request → chat_agent; digest run → mission_controller.

    The presence of ``chat_query`` in state is the signal set by the API layer
    when a user sends a message.  All digest pipeline runs leave it None.
    This is the extensibility gate — every new top-level feature (persona, compare,
    alert) can be added here as a new conditional branch without touching any
    existing agent.
    """
    if state.get("chat_query"):
        logger.info("route_from_start → chat_agent")
        return "chat_agent"
    logger.info("route_from_start → mission_controller (digest run)")
    return "mission_controller"


# ── INTELLIGENCE AGENT ROUTING (mode-based) ──────────────────────────────

ALL_INTEL_AGENTS = [
    "research_intel",
    "competitor_intel",
    "model_intel",
    "benchmark_intel",
]

# Maps a single mode keyword to its agent node name
_MODE_TO_AGENT = {
    "research": "research_intel",
    "competitor": "competitor_intel",
    "model": "model_intel",
    "benchmark": "benchmark_intel",
}


def route_to_intel_agents(state: RadarState) -> list[str]:
    """Route from strategy_planner to the correct intel agent(s).

    Reads ``run_mode`` from state:
    - ``"full"``  → activate ALL 4 intel agents in parallel
    - single name (e.g. ``"competitor"``) → activate only that agent
    - comma-separated (e.g. ``"research,competitor"``) → activate those agents

    LangGraph fan-in at ``intel_join`` automatically waits only for the
    agents that were actually activated.
    """
    mode = state.get("run_mode", "full")

    if mode == "full":
        logger.info("Routing: full mode -> all intel agents")
        return ALL_INTEL_AGENTS

    # Support comma-separated: "research,competitor" → ["research_intel", "competitor_intel"]
    requested = [m.strip() for m in mode.split(",")]
    agents = [_MODE_TO_AGENT[m] for m in requested if m in _MODE_TO_AGENT]

    if not agents:
        logger.warning("Routing: unknown mode %s, falling back to full", mode)
        return ALL_INTEL_AGENTS

    logger.info("Routing: mode=%s -> agents=%s", mode, agents)
    return agents


def route_after_intelligence(state: RadarState) -> Literal["verification", "ranking"]:
    """Route after intel_join: run verification if tasks exist, else skip to ranking.

    Called as a conditional edge from intel_join.  Checks whether any Layer 4
    agent flagged a SOTA claim that needs independent verification.
    """
    verification_tasks = state.get("verification_tasks", [])
    if verification_tasks:
        return "verification"
    return "ranking"


def route_after_digest(state: RadarState) -> Literal["digest", "report_generator"]:
    """Route after digest: retry digest if self-correction flag is set.

    Allows the Digest Agent to request a rewrite by setting
    digest_needs_rewrite=True in state.  If set, loops back to digest.
    Otherwise, proceeds to report_generator.
    """
    if state.get("digest_needs_rewrite", False):
        return "digest"
    return "report_generator"
