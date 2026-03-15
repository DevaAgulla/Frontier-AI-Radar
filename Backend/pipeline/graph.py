"""LangGraph state graph definition — wires all agents across the pipeline.

Every agent node is a LangGraph-native ReAct agent (built via
create_react_agent from langgraph.prebuilt).  The outer graph handles
layer sequencing, parallel fan-out/fan-in, and conditional routing.

Architecture (4 intelligence agents per problem statement):
    Layer 1 (Command)    -> Mission Controller
    Layer 2 (Planning)   -> Strategy Planner
    Layer 3 (Intel)      -> Research || Competitor || Model || Benchmark
         intel_join      -> convergence gate
    Layer 4 (Validation) -> Verification (conditional) -> Ranking
    Layer 5 (Synthesis)  -> Digest -> Report Generator -> Notification

Note: The Discovery layer (Source Scout, Feed Monitor, Trend Scout) was
removed because all Layer 3 intelligence agents fetch their own real data
deterministically, making the discovery agents redundant (they also relied
on stub tools returning mock data).
"""

from langgraph.graph import StateGraph, START, END
from pipeline.state import RadarState
from pipeline.router import route_after_intelligence, route_to_intel_agents, route_from_start

# Command
from agents.mission_controller import mission_controller_agent

# Planning
from agents.strategy_planner import strategy_planner_agent

# Intelligence (4 agents, parallel fan-out)
from agents.research_intel import research_intel_agent
from agents.competitor_intel import competitor_intel_agent
from agents.model_intel import model_intel_agent
from agents.benchmark_intel import benchmark_intel_agent

# Validation
from agents.ranking import ranking_agent
from agents.verification import verification_agent

# Synthesis & Delivery
from agents.digest import digest_agent
from agents.report_generator import report_generator_agent
from agents.notification import notification_agent

from db.persist import persist_intel_findings
import structlog

logger = structlog.get_logger()


# ── JOIN NODES (fan-in convergence points) ─────────────────────────────────

async def intel_join(state: RadarState) -> dict:
    """Pass-through node: waits for ALL intelligence agents to complete,
    persists findings + resources to the DB, then routes to validation.
    """
    logger.info("Intel Join: all intelligence agents complete")

    # ── DB: persist all findings + resources ──────────────────────────
    extraction_db_id = state.get("extraction_db_id", 0)
    run_db_id = state.get("run_db_id", 0)
    if extraction_db_id and run_db_id:
        persist_intel_findings(state, extraction_db_id, run_db_id)

    logger.info("Intel Join: routing to validation layer")
    return {}


def create_radar_graph(checkpointer=None) -> StateGraph:
    """Create the full LangGraph state graph for Frontier AI Radar.

    Architecture
    ────────────
    START
      │ route_from_start (conditional)
      ├─── chat_query set  ──► chat_agent ──► END
      └─── digest run      ──► mission_controller ──► … ──► notification ──► END

    The chat_agent node is a compiled create_react_agent subgraph.  LangGraph
    passes the shared ``messages`` key into it and merges the updated messages
    back into RadarState automatically — no wrapper function needed.  Token
    streaming works via astream_events(version="v2") on this graph.

    Every future feature (persona, alert, compare) is a new branch from START
    — added here without touching any existing node or edge.

    Args:
        checkpointer: Optional LangGraph checkpointer (AsyncPostgresSaver).
                      Shared between the digest pipeline and the chat agent so
                      query_digest_state tool can read from digest run checkpoints
                      (thread_id = "run_{run_db_id}") while the chat session is
                      checkpointed separately (thread_id = "chat_{session_id}").
    """
    from agents.chat_agent import create_chat_agent

    graph = StateGraph(RadarState)

    # ── CHAT AGENT NODE (Layer 0 — pre-digest branch) ─────────────
    # create_react_agent returns a compiled graph with MessagesState.
    # Since RadarState now has messages: Annotated[list[BaseMessage], add_messages],
    # LangGraph treats "messages" as a shared channel and passes it directly
    # into the subgraph without any wrapper.  astream_events propagates all
    # inner LLM token events through to the parent graph's stream.
    chat_agent = create_chat_agent(checkpointer=checkpointer)
    graph.add_node("chat_agent", chat_agent)
    graph.add_edge("chat_agent", END)

    # ── ADD ALL DIGEST PIPELINE NODES ─────────────────────────────
    # Layer 1
    graph.add_node("mission_controller", mission_controller_agent)
    # Layer 2
    graph.add_node("strategy_planner", strategy_planner_agent)
    # Layer 3 — Intelligence (4 agents, parallel)
    graph.add_node("research_intel", research_intel_agent)
    graph.add_node("competitor_intel", competitor_intel_agent)
    graph.add_node("model_intel", model_intel_agent)
    graph.add_node("benchmark_intel", benchmark_intel_agent)
    # Join (Layer 3 -> Layer 4 convergence)
    graph.add_node("intel_join", intel_join)
    # Layer 4 — Validation
    graph.add_node("ranking", ranking_agent)
    graph.add_node("verification", verification_agent)
    # Layer 5 — Synthesis & Delivery
    graph.add_node("digest", digest_agent)
    graph.add_node("report_generator", report_generator_agent)
    graph.add_node("notification", notification_agent)

    # ── START → conditional: chat OR digest ───────────────────────
    graph.add_conditional_edges(
        START,
        route_from_start,
        ["chat_agent", "mission_controller"],
    )

    # ── LAYER 1 -> LAYER 2 (sequential) ───────────────────────────
    graph.add_edge("mission_controller", "strategy_planner")

    # ── LAYER 2 -> LAYER 3 (conditional fan-out based on run_mode) ─
    # route_to_intel_agents reads state["run_mode"] and returns only
    # the agent(s) to activate.  Supports: "full", single agent name,
    # or comma-separated combos like "research,competitor".
    graph.add_conditional_edges(
        "strategy_planner",
        route_to_intel_agents,
        ["research_intel", "competitor_intel", "model_intel",
         "benchmark_intel"],
    )

    # ── LAYER 3 -> intel_join (fan-in: wait for all intel agents) ─
    graph.add_edge("research_intel", "intel_join")
    graph.add_edge("competitor_intel", "intel_join")
    graph.add_edge("model_intel", "intel_join")
    graph.add_edge("benchmark_intel", "intel_join")

    # ── intel_join -> VERIFICATION (conditional) -> RANKING ───────
    graph.add_conditional_edges(
        "intel_join",
        route_after_intelligence,
        {
            "verification": "verification",
            "ranking": "ranking",
        },
    )
    graph.add_edge("verification", "ranking")

    # ── LAYER 4 -> LAYER 5: RANKING -> DIGEST -> REPORT -> NOTIFY ─
    graph.add_edge("ranking", "digest")
    graph.add_edge("digest", "report_generator")
    graph.add_edge("report_generator", "notification")
    graph.add_edge("notification", END)
    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return graph.compile(**compile_kwargs)
