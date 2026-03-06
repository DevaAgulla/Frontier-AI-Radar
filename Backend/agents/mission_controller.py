"""Mission Controller Agent — LangGraph-native ReAct agent (Layer 1).

Sets the mission goal, determines which agents should run, and establishes
the overall focus for this radar run.
"""

import json
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
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

MISSION_CONTROLLER_SYSTEM_PROMPT = """You are the Mission Controller Agent for Frontier AI Radar.

GOAL: Determine today's mission — what the radar run should focus on,
which agents to activate, and what priority areas matter most right now.

TOOLS YOU CAN CALL:
- read_memory: Read yesterday's run summary to understand what was already covered.
- search_entity_memory: Check known entities to inform focus priorities.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. Read yesterday's run summary via read_memory to avoid duplicating effort.
2. Check entity memory for tracked organisations/models to set priorities.
3. Decide which agents should run (all for "full" mode, or subset).
4. Emit the mission plan as JSON.

OUTPUT FORMAT: Return ONLY a valid JSON object:
{
    "mission_goal": "<one-sentence mission statement for today>",
    "selected_agents": ["agent_name", ...],
    "focus_keywords": "<search keywords for intelligence agents>",
    "priority_areas": ["area1", "area2", ...],
    "reasoning": "<why you chose this focus>"
}

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

MISSION_CONTROLLER_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        read_memory,               # Claude reads yesterday's run context
        search_entity_memory,      # Claude checks tracked entities
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": MISSION_CONTROLLER_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,           # writes: mission_goal, strategy_plan, selected_agents

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": 2,
    },
}


# ── BUILD THE REACT AGENT ─────────────────────────────────────────────────
# write_memory is NOT given to the ReAct agent — it runs in Phase 4.

_optional_tools = [read_memory, search_entity_memory]

_react_agent = build_react_agent(
    system_prompt=MISSION_CONTROLLER_CONFIG["system_prompt"],
    tools=_optional_tools,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def mission_controller_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Mission Controller Agent.

    Fully agentic — Claude decides what to read from memory, reasons about
    today's priorities, and emits a mission plan.
    """
    try:
        logger.info("Mission Controller: starting")

        run_mode = state.get("run_mode", "full")
        since = state.get("since_timestamp", "")

        user_prompt = (
            f"Run mode: {run_mode}\n"
            f"Since: {since}\n\n"
            "1. Call read_memory to check yesterday's run summary.\n"
            "2. Call search_entity_memory to review tracked entities.\n"
            "3. Based on what you find, decide today's mission focus.\n"
            "4. Emit the mission plan JSON."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                MISSION_CONTROLLER_CONFIG["config"]["max_iterations"]
            )},
        )
        final_text = extract_agent_output(result["messages"])
        plan = parse_json_object(final_text)
        logger.info("Mission Controller: complete", plan_keys=list(plan.keys()))

        return {
            "mission_goal": plan.get("mission_goal", "Monitor AI ecosystem for relevant updates"),
            "strategy_plan": {
                "focus_keywords": plan.get(
                    "focus_keywords",
                    "evaluation OR benchmark OR data curation OR agentic OR multimodal OR safety",
                ),
                "priority_areas": plan.get("priority_areas", []),
                "reasoning": plan.get("reasoning", ""),
            },
            "selected_agents": plan.get("selected_agents", []),
        }

    except Exception as e:
        logger.exception("Mission Controller error", error=str(e))
        # Fallback: set sensible defaults so downstream agents can still run
        return {
            "mission_goal": "Monitor AI ecosystem for relevant updates",
            "strategy_plan": {
                "focus_keywords": "evaluation OR benchmark OR data curation OR agentic OR multimodal OR safety",
            },
            "selected_agents": [],
            "errors": [{"agent_name": "mission_controller", "error_type": type(e).__name__,
                        "error_message": str(e), "timestamp": "", "context": {}}],
        }
