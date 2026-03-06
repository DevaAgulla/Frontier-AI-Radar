"""Model Intelligence Agent — LangGraph-native ReAct agent.

Monitors foundation model providers (OpenAI, Anthropic, Google, Meta, Mistral,
HuggingFace, GitHub) for new releases, API changes, pricing shifts, and
benchmark claims.

Phase 1 (deterministic): Calls fetch_foundation_model_releases_tool to get
    structured release data from 12+ real provider sources (RSS, APIs, sitemaps).
Phase 2-3 (LLM ReAct): Claude analyzes releases, flags SOTA claims.
Phase 4 (deterministic): Writes findings + verification tasks to state.
"""

import json
import uuid
from typing import List, Dict, Any
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
    fetch_foundation_model_releases_tool,
    crawl_page,
    fetch_headless,
    diff_content,
    read_memory,
    write_memory,
    search_entity_memory,
    flag_verification_task,
)
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

MODEL_INTEL_SYSTEM_PROMPT = """You are the Model Intelligence Agent for Frontier AI Radar.

GOAL: Analyze foundation model provider releases and updates — new model releases,
API changes, pricing shifts, context window updates, and benchmark claims.

You receive STRUCTURED release data (already fetched from 12+ provider sources
including HuggingFace, OpenAI, Anthropic, Google DeepMind, and GitHub). Your job
is to analyze this data, NOT fetch it yourself.

CRITICAL BEHAVIOUR: If a provider claims SOTA on any benchmark, you MUST call
flag_verification_task to create a verification task. The Verification Agent
will independently check HuggingFace leaderboards to confirm or contradict.

TOOLS YOU CAN CALL:
- search_entity_memory: Get context about known models and providers.
- flag_verification_task: MUST call when a SOTA/benchmark claim is detected.
- diff_content: Detect real changes compared to previous snapshots.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. Review the structured release records provided to you.
2. Use search_entity_memory to check if any releases are genuinely NEW vs already known.
3. For each significant release, extract: model name, provider, modalities, context window, pricing.
4. If ANY benchmark claim or SOTA claim is found -> call flag_verification_task.
5. Emit findings as a JSON array.

EXTRACTION FOCUS:
- Model name and version
- Context window size
- Pricing (per 1M tokens, input vs output)
- Claimed benchmark scores (and which benchmarks)
- API changes (new endpoints, deprecations)
- Modalities supported (text, vision, audio, video)
- Availability (preview, GA, regions)

OUTPUT FORMAT: Return ONLY a valid JSON array of Finding objects.
Each Finding must have:
  id, title, source_url, publisher, date_detected, category, what_changed,
  why_it_matters, confidence, actionability, novelty, credibility, relevance,
  impact_score (0.0), entities, evidence_snippet, needs_verification,
  tags, markdown_summary, agent_source ("model_intel").

Set needs_verification=true for ANY finding containing benchmark claims.

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
- If no releases are found, return an empty array: []
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

MODEL_INTEL_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        search_entity_memory,      # context about known models/providers
        flag_verification_task,    # flag SOTA claims for verification
        diff_content,              # detect real changes vs previous snapshots
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": MODEL_INTEL_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,           # writes: provider_findings[], verification_tasks[]

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": settings.max_iterations_model,
    },
}

_react_agent = build_react_agent(
    system_prompt=MODEL_INTEL_CONFIG["system_prompt"],
    tools=MODEL_INTEL_CONFIG["tools"],
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def model_intel_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Model Intelligence Agent.

    Phase 1 (deterministic): fetch_foundation_model_releases_tool -> structured data
    Phase 2-3 (LLM ReAct): Claude analyzes releases, flags SOTA claims
    Phase 4 (deterministic): Write provider findings + verification tasks to state
    """
    try:
        # Run-mode guard: skip if not relevant
        run_mode = state.get("run_mode", "full")
        if run_mode != "full" and "model" not in run_mode.split(","):
            logger.info("Model Intel: skipped (run_mode=%s)", run_mode)
            return {}

        url_mode = state.get("url_mode", "default")
        custom_urls = state.get("custom_urls", [])
        logger.info("Model Intel: Phase 1 — fetching foundation model releases",
                     url_mode=url_mode, custom_urls_count=len(custom_urls))

        # ── PHASE 1: DETERMINISTIC DATA FETCH ─────────────────────
        releases = []

        # ── Default / Append: fetch from standard 12+ provider sources ─
        if url_mode in ("default", "append"):
            releases = await fetch_foundation_model_releases_tool.ainvoke(
                {"target_date": ""}  # defaults to today
            )
            if not isinstance(releases, list):
                releases = []

        # ── Append / Custom: crawl user-provided URLs ──────────────────
        if url_mode in ("append", "custom") and custom_urls:
            for url in custom_urls:
                logger.info("Model Intel: crawling custom URL", url=url)
                page = await crawl_page.ainvoke({"url": url})
                if isinstance(page, dict):
                    # Auto-fallback to headless if blocked
                    status = page.get("status_code", 0)
                    content_len = page.get("content_length", 0)
                    content = page.get("content", "")
                    if (status == 403 or status == 0 or content_len < 100
                            or ("javascript" in content.lower() and content_len < 200)):
                        logger.info("Model Intel: headless fallback", url=url)
                        page = await fetch_headless.ainvoke({"url": url})
                    if isinstance(page, dict) and page.get("content_length", 0) > 0:
                        releases.append({
                            "model_name": page.get("title", "Unknown"),
                            "provider": "custom_url",
                            "release_date": page.get("date", ""),
                            "model_details": page.get("content", "")[:2000],
                            "source": url,
                        })

        logger.info(
            "Model Intel: Phase 1 complete — releases fetched",
            num_releases=len(releases),
        )

        # Read previous snapshots from memory for diff context
        prev_snapshots = await read_memory.ainvoke({
            "type": "long_term",
            "key": "model_provider_snapshots",
        })

        # If no releases found, still produce a minimal output
        if not releases or (isinstance(releases, list) and len(releases) == 0):
            logger.info("Model Intel: No releases found for today, emitting empty findings")
            await write_memory.ainvoke({
                "type": "long_term",
                "key": "last_model_intel_findings",
                "value": json.dumps([]),
            })
            return {"provider_findings": [], "verification_tasks": []}

        # ── PHASE 2-3: LLM REASONING ─────────────────────────────
        logger.info("Model Intel: Phase 2-3 — Claude analyzing %d releases", len(releases))

        since = state.get("since_timestamp", "")
        strategy = state.get("strategy_plan", {})

        # Build a compact summary for the prompt (truncate details to save tokens)
        releases_for_prompt = []
        for r in releases[:30]:  # Cap at 30 most relevant releases
            releases_for_prompt.append({
                "model_name": r.get("model_name"),
                "provider": r.get("provider"),
                "release_date": r.get("release_date"),
                "model_details": (r.get("model_details") or "")[:300],
                "modalities": r.get("modalities", []),
                "context_length": r.get("context_length"),
                "benchmarks": r.get("benchmarks", {}),
                "pricing": r.get("pricing"),
                "model_page": r.get("model_page"),
                "github_repo": r.get("github_repo"),
                "source": r.get("source"),
            })

        user_prompt = (
            f"Analyze these {len(releases_for_prompt)} foundation model releases "
            f"detected today from provider sources:\n\n"
            f"--- RELEASES JSON ---\n{json.dumps(releases_for_prompt, indent=2)}\n--- END ---\n\n"
            f"Previous known models snapshot: {json.dumps(prev_snapshots)}\n"
            f"Since date: {since}\n"
            f"Strategy guidance: {json.dumps(strategy.get('agent_instructions', {}).get('model_intel', ''))}\n\n"
            "IMPORTANT: If ANY provider claims SOTA on a benchmark, you MUST call "
            "flag_verification_task with the claim details.\n\n"
            "Analyze the significance of each release. Identify genuinely new models vs updates. "
            "Flag SOTA claims. Emit the JSON array of Finding objects."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                MODEL_INTEL_CONFIG["config"]["max_iterations"]
            )},
        )

        final_text = extract_agent_output(result["messages"])
        findings = parse_json_output(final_text)

        # Validate findings + extract verification tasks
        verification_tasks = []
        for f in findings:
            if not f.get("id"):
                f["id"] = str(uuid.uuid4())
            if not f.get("agent_source"):
                f["agent_source"] = "model_intel"
            if not f.get("impact_score"):
                f["impact_score"] = 0.0
            # If finding is flagged for verification, create task
            if f.get("needs_verification"):
                verification_tasks.append({
                    "claim": f.get("what_changed", ""),
                    "model": ", ".join(f.get("entities", [])),
                    "benchmark": "",
                    "source_url": f.get("source_url", ""),
                    "finding_id": f["id"],
                })

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_model_intel_findings",
            "value": json.dumps(findings),
        })
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "model_provider_snapshots",
            "value": json.dumps({
                r.get("model_name", ""): r.get("release_date", "")
                for r in releases
            }),
        })

        logger.info(
            "Model Intel: Phase 4 — writing findings",
            findings=len(findings),
            verification_tasks=len(verification_tasks),
        )
        return {
            "provider_findings": findings,
            "verification_tasks": verification_tasks,
        }

    except Exception as e:
        logger.exception("Model Intel error", error=str(e))
        return handle_agent_error("model_intel", e)
