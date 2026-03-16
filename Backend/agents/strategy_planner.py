"""Strategy Planner Agent — LangGraph-native ReAct agent (Layer 2).

Takes the mission goal from the Mission Controller and creates a detailed
execution strategy: which agents run, in what order, and with what parameters.
"""

from langchain_core.messages import HumanMessage

from pipeline.state import RadarState
from agents.base_agent import (
    build_react_agent,
    get_recursion_limit,
    extract_agent_output,
    parse_json_object,
    handle_agent_error,
)
from core.tools import read_memory, write_memory, search_entity_memory
from agents.schemas import StrategyPlanOutput
from config.settings import settings, load_sources_config
import json
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

STRATEGY_PLANNER_SYSTEM_PROMPT = """You are the Strategy Planner Agent for Frontier AI Radar.

GOAL: Translate the mission goal into a concrete execution plan for all
downstream agents.  You decide focus areas, search queries, and priorities.

TOOLS YOU CAN CALL:
- read_memory: Read past strategy plans to learn what worked well.
- search_entity_memory: Check entity profiles to refine search queries.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. Read the mission goal provided.
2. Optionally read past strategies from memory.
3. Optionally check entity memory for tracked orgs/models.
4. Create a detailed strategy plan.
5. Emit the strategy as JSON.

OUTPUT FORMAT: Return ONLY a valid JSON object:
{
    "focus_keywords": "<optimised search query for intelligence agents>",
    "priority_areas": ["area1", "area2", ...],
    "agent_instructions": {
        "research_intel": "<specific guidance>",
        "competitor_intel": "<specific guidance>",
        "model_intel": "<specific guidance>",
        "benchmark_intel": "<specific guidance>"
    },
    "reasoning": "<why this strategy>"
}

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

STRATEGY_PLANNER_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        read_memory,
        search_entity_memory,
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": STRATEGY_PLANNER_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,          # reads: mission_goal, strategy_plan
                                  # writes: strategy_plan (enriched)

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": 2,
    },
}


# ── BUILD THE REACT AGENT ─────────────────────────────────────────────────
# write_memory is NOT given to the ReAct agent — it runs in Phase 4.

_optional_tools = [read_memory, search_entity_memory]

_react_agent = build_react_agent(
    system_prompt=STRATEGY_PLANNER_CONFIG["system_prompt"],
    tools=_optional_tools,
    response_format=StrategyPlanOutput,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def strategy_planner_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Strategy Planner Agent.

    Takes the mission_goal set by Mission Controller and creates a detailed
    execution plan for all intelligence agents.
    """
    try:
        logger.info("Strategy Planner: starting")

        mission_goal = state.get("mission_goal", "")
        current_strategy = state.get("strategy_plan", {})
        run_mode = state.get("run_mode", "full")

        # Load configured sources for context
        sources_config = load_sources_config()
        user_prompt = (
            f"Mission goal: {mission_goal}\n"
            f"Run mode: {run_mode}\n"
            f"Current strategy: {json.dumps(current_strategy)}\n"
            f"Configured sources: {json.dumps(sources_config, default=str)}\n\n"
            "Create a detailed execution strategy. "
            "Optionally call read_memory to check past strategies. "
            "Then emit the strategy plan JSON."
        )
        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                STRATEGY_PLANNER_CONFIG["config"]["max_iterations"]
            )},
        )
        structured = result.get("structured_response")
        if structured is not None:
            plan = structured.model_dump()
        else:
            final_text = extract_agent_output(result["messages"])
            plan = parse_json_object(final_text)
        logger.info("Strategy Planner: complete")

        # Merge new strategy into existing, preserving mission controller values
        enriched_strategy = {
            **current_strategy,
            **plan,
        }
        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_strategy_planner_plan",
            "value": json.dumps(enriched_strategy),
        })
        return {
            "strategy_plan": enriched_strategy,
        }
    except Exception as e:
        logger.exception("Strategy Planner error", error=str(e))
        return handle_agent_error("strategy_planner", e)
