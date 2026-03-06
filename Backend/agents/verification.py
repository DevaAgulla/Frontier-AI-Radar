"""Verification Agent — LangGraph-native ReAct agent (Layer 5 Validation).

Independently verifies SOTA/benchmark claims flagged by the Model Intelligence
Agent.  Checks HuggingFace leaderboards and model cards for evidence.
"""

import json
from langchain_core.messages import HumanMessage

from pipeline.state import RadarState
from agents.base_agent import (
    build_react_agent,
    get_recursion_limit,
    extract_agent_output,
    parse_json_output,
    handle_agent_error,
)
from core.tools import (
    fetch_hf_leaderboard,
    fetch_hf_model_card,
    search_hf_models,
    crawl_page,
    read_memory,
    write_memory,  # used in Phase 4 (mandatory)
)
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

VERIFICATION_SYSTEM_PROMPT = """You are the Verification Agent for Frontier AI Radar.

GOAL: Independently verify SOTA and benchmark claims flagged by the Model
Intelligence Agent.  For each verification task, check HuggingFace leaderboards
and model cards to confirm or contradict the claim.

TOOLS YOU CAN CALL:
- fetch_hf_leaderboard: Get current leaderboard data to check rankings.
- fetch_hf_model_card: Get detailed model info to verify claimed scores.
- search_hf_models: Search for the claimed model on HuggingFace.
- crawl_page: Fetch the original claim source for evidence comparison.
- read_memory: Check if this claim was previously verified.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. For each verification task, understand the claim being made.
2. Fetch the relevant HF leaderboard to check actual rankings.
3. If the model exists on HF, get its model card for claimed scores.
4. Compare the claimed scores with actual leaderboard data.
5. Render a verdict: "confirmed", "contradicted", or "unclear".
6. Emit verification verdicts as JSON array.

VERDICT CRITERIA:
- "confirmed" → Leaderboard data matches or supports the claim
- "contradicted" → Leaderboard data shows different rankings/scores
- "unclear" → Model not found on leaderboard, or data is ambiguous

OUTPUT FORMAT: Return ONLY a valid JSON array of verdict objects:
[
    {
        "task_id": "<from verification task>",
        "finding_id": "<from verification task>",
        "verified": true/false,
        "verdict": "confirmed|contradicted|unclear",
        "evidence_url": "<HF leaderboard or model card URL>",
        "notes": "<detailed explanation of verdict>",
        "actual_score": null or float,
        "claimed_score": null or float
    }
]

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

VERIFICATION_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        fetch_hf_leaderboard,     # Claude calls to check current rankings
        fetch_hf_model_card,      # Claude calls for model details
        search_hf_models,         # Claude searches for claimed model
        crawl_page,               # Claude may check original claim source
        read_memory,              # Claude checks past verifications
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": VERIFICATION_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,          # reads: verification_tasks[]
                                  # writes: verification_verdicts[]

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": 5,
    },
}

# write_memory is NOT given to the ReAct agent — it runs in Phase 4.
_optional_tools = [
    fetch_hf_leaderboard, fetch_hf_model_card,
    search_hf_models, crawl_page, read_memory,
]

_react_agent = build_react_agent(
    system_prompt=VERIFICATION_CONFIG["system_prompt"],
    tools=_optional_tools,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def verification_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Verification Agent.

    Fully agentic — Claude reads verification tasks from state,
    autonomously checks HF leaderboards, and emits verdicts.
    No mandatory Phase 1 — all tool decisions are Claude's.
    """
    try:
        verification_tasks = state.get("verification_tasks", [])

        if not verification_tasks:
            logger.info("Verification Agent: no tasks to verify")
            return {}

        logger.info("Verification Agent: starting", task_count=len(verification_tasks))

        user_prompt = (
            f"Verification tasks to check ({len(verification_tasks)}):\n"
            f"{json.dumps(verification_tasks, indent=2)}\n\n"
            "For each task:\n"
            "1. Call fetch_hf_leaderboard to get current data.\n"
            "2. Call fetch_hf_model_card or search_hf_models if needed.\n"
            "3. Compare claimed scores with actual data.\n"
            "4. Render verdict: confirmed / contradicted / unclear.\n"
            "5. Emit the JSON array of verdict objects."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                VERIFICATION_CONFIG["config"]["max_iterations"]
            )},
        )

        final_text = extract_agent_output(result["messages"])
        verdicts = parse_json_output(final_text)

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_verification_verdicts",
            "value": json.dumps(verdicts),
        })

        logger.info("Verification Agent: complete", verdicts=len(verdicts))
        return {"verification_verdicts": verdicts}

    except Exception as e:
        logger.exception("Verification Agent error", error=str(e))
        return handle_agent_error("verification", e)
