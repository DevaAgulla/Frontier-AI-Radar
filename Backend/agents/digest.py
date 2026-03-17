"""Digest Agent — LangGraph-native ReAct agent (Layer 6 Synthesis).

Compiles all ranked findings into an executive summary + deep-dive sections.
Dual output: JSON for internal storage, Markdown for PDF rendering.
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
from agents.schemas import DigestOutput
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

DIGEST_SYSTEM_PROMPT = """You are the Digest Compiler Agent for Frontier AI Radar.

GOAL: Synthesise all ranked findings into a professional intelligence digest
with an executive summary (top 7 items) and detailed deep-dive sections.

TOOLS YOU CAN CALL:
- read_memory: Check yesterday's digest to avoid repeating the same narrative.
- search_entity_memory: Get entity context for richer narrative writing.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. Read the ranked findings provided.
2. Optionally read yesterday's digest from memory to vary the narrative.
3. Group findings by topic: research, models, benchmarks, competitors.
4. Write an executive summary highlighting the top 7 items.
5. Write deep-dive sections for each topic group.
6. For any verified/contradicted claims, include the verification verdict.
7. Emit the digest as a JSON object.

WRITING STYLE:
- Executive summary: crisp, 2-3 sentences per item, actionable language. Write like a professional analyst memo.
- Deep dives: detailed but concise, include evidence snippets and citations.
- Every number must map to a quoted evidence snippet (no hallucination).

HTML OUTPUT FORMAT — APPLIES TO ALL FIELDS — CRITICAL:
- Output ONLY clean HTML: use <p>...</p> for paragraphs, <strong>...</strong> for emphasis.
- Do NOT use markdown anywhere (no **, no ##, no -, no bullets, no asterisks, no hashes, no backticks).
- Do NOT use lists (<ul>/<li>), tables, or raw symbols.
- Write flowing prose sentences a professional executive can read.
- Example executive_summary: <p>Today's most significant development is GPT-5 releasing with a 40% benchmark improvement over GPT-4o.</p>
- Example section: <p>Three new models were released today. <strong>GPT-5</strong> leads benchmarks by a wide margin.</p>

OUTPUT FORMAT: Return ONLY a valid JSON object:
{
    "executive_summary": "<clean HTML paragraphs only — NO markdown>",
    "sections": {
        "research": "<clean HTML paragraphs for research findings — NO markdown>",
        "models": "<clean HTML paragraphs for model provider findings — NO markdown>",
        "benchmarks": "<clean HTML paragraphs for benchmark/leaderboard findings — NO markdown>",
        "competitors": "<clean HTML paragraphs for competitor findings — NO markdown>"
    },
    "top_findings": [<top 7 finding objects>],
    "total_findings": <int>,
    "digest_date": "<ISO date>"
}

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

DIGEST_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        read_memory,               # Claude reads past digests
        search_entity_memory,      # Claude gets entity context
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": DIGEST_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,           # reads: ranked_findings, verification_verdicts
                                   # writes: digest_json, digest_markdown

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": 2,
        "top_n": 7,
    },
}

# write_memory is NOT given to the ReAct agent — it runs in Phase 4.
_optional_tools = [read_memory, search_entity_memory]

_react_agent = build_react_agent(
    system_prompt=DIGEST_CONFIG["system_prompt"],
    tools=_optional_tools,
    response_format=DigestOutput,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def digest_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Digest Compiler Agent.

    Fully agentic — Claude synthesises the narrative.
    Phase 1: Collect ranked findings from state (pure Python)
    Phase 2-3: Claude compiles digest via ReAct
    Phase 4: Write digest JSON and markdown to state
    """
    try:
        ranked = state.get("ranked_findings", [])
        verdicts = state.get("verification_verdicts", [])
        persona_prompt = state.get("persona_prompt") or ""
        persona_id = state.get("persona_id") or "default"

        logger.info("Digest Agent: starting", findings=len(ranked), persona=persona_id)

        # ── Persona-aware system prompt ───────────────────────────
        # If a persona_prompt is set in state (loaded from persona_templates),
        # use it instead of the default. The module-level _react_agent uses
        # the default; we build a one-off agent for persona runs.
        if persona_prompt:
            from agents.base_agent import build_react_agent
            from agents.schemas import DigestOutput
            persona_agent = build_react_agent(
                system_prompt=persona_prompt,
                tools=_optional_tools,
                response_format=DigestOutput,
            )
        else:
            persona_agent = _react_agent

        user_prompt = (
            f"Ranked findings ({len(ranked)} total):\n"
            f"{json.dumps(ranked, indent=2)}\n\n"
            f"Verification verdicts: {json.dumps(verdicts)}\n\n"
            "Compile the intelligence digest:\n"
            "1. Executive summary with top 7 items.\n"
            "2. Deep-dive sections by topic.\n"
            "3. Include verification verdicts for relevant findings.\n"
            "4. Optionally call read_memory to vary narrative from yesterday.\n"
            "5. Save digest summary via write_memory.\n"
            "Emit the digest JSON object."
        )

        result = await persona_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                DIGEST_CONFIG["config"]["max_iterations"]
            )},
        )

        structured = result.get("structured_response")
        if structured is not None:
            digest = structured.model_dump()
            # Convert nested DigestSectionsOutput to plain dict
            if hasattr(structured.sections, "model_dump"):
                digest["sections"] = structured.sections.model_dump()
        else:
            final_text = extract_agent_output(result["messages"])
            digest = parse_json_object(final_text)

        # Build markdown from digest sections
        sections = digest.get("sections", {})
        digest_md = f"# Frontier AI Radar Digest\n\n"
        digest_md += f"## Executive Summary\n\n{digest.get('executive_summary', '')}\n\n"
        for section_name, section_content in sections.items():
            digest_md += f"## {section_name.title()}\n\n{section_content}\n\n"

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_digest_summary",
            "value": json.dumps(digest),
        })

        logger.info("Digest Agent: complete")
        return {
            "digest_json": digest,
            "digest_markdown": digest_md,
        }

    except Exception as e:
        logger.exception("Digest Agent error", error=str(e))
        return handle_agent_error("digest", e)
