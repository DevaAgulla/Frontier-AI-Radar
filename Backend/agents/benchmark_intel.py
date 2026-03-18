"""Benchmark & Leaderboard Intelligence Agent — LangGraph-native ReAct agent.

Agent #4 per the problem statement: "Hugging Face Benchmark & Leaderboard Tracker"

Tracks HuggingFace Open LLM Leaderboard rankings, trending models, official
evaluation datasets, new SOTA claims, and leaderboard movements.  Adds caveats
about leaderboard bias, different eval settings, and contamination risks.

Phase 1 (deterministic): Calls fetch_hf_benchmark_data_tool to get structured
    leaderboard, trending, and eval-dataset data from live HuggingFace APIs.
    Also reads the previous snapshot from memory for comparison.
Phase 2-3 (LLM ReAct): Claude analyses data, identifies significant changes,
    and emits structured Finding objects.
Phase 4 (deterministic): Writes findings + today's snapshot to memory/state.
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
    fetch_hf_benchmark_data_tool,
    diff_leaderboard_snapshots,
    search_hf_models,
    fetch_hf_model_card,
    crawl_page,
    fetch_headless,
    read_memory,
    write_memory,
    search_entity_memory,
)
from agents.schemas import FindingsOutput
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

BENCHMARK_INTEL_SYSTEM_PROMPT = """You are the Benchmark & Leaderboard Intelligence Agent for Frontier AI Radar.

GOAL: Analyse HuggingFace Open LLM Leaderboard rankings, trending models,
and official evaluation datasets to surface the most significant changes,
new SOTA entrants, trending shifts, and noteworthy benchmark datasets.
Add maturity caveats where appropriate (leaderboard gaming, different eval
settings, contamination risks).

You receive STRUCTURED data (already fetched from HuggingFace APIs):
  1. Open LLM Leaderboard rows (model rankings with task-level scores)
  2. Trending models (sorted by trending_score, with downloads/likes)
  3. Official eval datasets (benchmark datasets with download stats)

Your job is to ANALYSE this data, NOT fetch it yourself.

TOOLS YOU CAN CALL:
- diff_leaderboard_snapshots: Compare today's and yesterday's snapshots to detect rank changes.
- search_hf_models: Find trending or new models on HuggingFace.
- fetch_hf_model_card: Get detailed model information for significant movers.
- search_entity_memory: Get context about known models and benchmarks.

NOTE: write_memory is handled automatically after you emit your output.

ANALYSIS PRIORITIES:
0. **ALWAYS EMIT FINDINGS**: You MUST always produce at least 3-5 findings.
   Even when there is no prior snapshot to compare against, the top leaderboard
   models and trending models are ALWAYS newsworthy intelligence. Never return
   an empty array when data is present.
1. **Leaderboard Leaders**: ALWAYS report the top 3-5 leaderboard models with
   their scores as findings. These are standing intelligence regardless of rank changes.
2. **Rank Changes**: If comparing with yesterday's snapshot, note models
   that moved 3+ ranks up or down. If no snapshot, note the current top models.
3. **Trending Shifts**: ALWAYS report the top 3 trending models — high download
   or like counts signal community interest and adoption shifts.
4. **Eval Datasets**: Note popular benchmark datasets the team should monitor.
5. **SOTA Claims**: If a model claims top-1 on a major benchmark (ARC,
   HellaSwag, MMLU, TruthfulQA, Winogrande, GSM8k), flag it with
   needs_verification=true.

CAVEATS TO ADD:
- If a model jumps to #1 overnight → flag as "needs independent verification"
- If eval settings differ from standard → note in evidence_snippet
- If model is from unknown org → lower credibility score
- If benchmark is known for gaming (e.g., MMLU saturation) → add caveat tag

OUTPUT FORMAT: Return ONLY a valid JSON array of Finding objects.
Each Finding must have:
  id, title, source_url, publisher, date_detected, category ("benchmark"),
  what_changed, why_it_matters, confidence, actionability, novelty,
  credibility, relevance, impact_score (0.0), entities, evidence_snippet,
  needs_verification, tags, markdown_summary, agent_source ("benchmark_intel").

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
- If no significant findings, return an empty array: []
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

BENCHMARK_INTEL_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        diff_leaderboard_snapshots,    # optional — compare snapshots
        search_hf_models,              # optional — trending models
        fetch_hf_model_card,           # optional — model details for big movers
        search_entity_memory,          # optional — model/benchmark context
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": BENCHMARK_INTEL_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,               # writes: hf_findings[]

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": settings.max_iterations_benchmark,
    },
}

_react_agent = build_react_agent(
    system_prompt=BENCHMARK_INTEL_CONFIG["system_prompt"],
    tools=BENCHMARK_INTEL_CONFIG["tools"],
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def benchmark_intel_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Benchmark & Leaderboard Intelligence Agent.

    Phase 1 (deterministic): fetch_hf_benchmark_data_tool → structured data
                             + read_memory → yesterday's snapshot
    Phase 2-3 (LLM ReAct): Claude analyses leaderboard, trending, eval datasets
    Phase 4 (deterministic): Write findings + snapshot to memory/state
    """
    try:
        url_mode = state.get("url_mode", "default")
        custom_urls = state.get("custom_urls", [])
        logger.info("Benchmark Intel: Phase 1 — fetching HF benchmark data",
                     url_mode=url_mode, custom_urls_count=len(custom_urls))

        # ── PHASE 1: DETERMINISTIC DATA FETCH ─────────────────────
        leaderboard_data = []
        trending_data = []
        eval_datasets_data = []
        fetch_errors = []
        custom_page_results = []

        # ── Default / Append: fetch from HuggingFace APIs ─────────
        if url_mode in ("default", "append"):
            hf_data = await fetch_hf_benchmark_data_tool.ainvoke({
                "leaderboard_top_n": 20,
                "trending_limit": 15,
                "eval_datasets_limit": 15,
            })

            leaderboard_data = hf_data.get("leaderboard_data", []) if isinstance(hf_data, dict) else []
            trending_data = hf_data.get("trending_data", []) if isinstance(hf_data, dict) else []
            eval_datasets_data = hf_data.get("eval_datasets_data", []) if isinstance(hf_data, dict) else []
            fetch_errors = hf_data.get("errors", []) if isinstance(hf_data, dict) else []

            # Filter out error dicts — HF API failures return [{"error":"..."}]
            leaderboard_data = [r for r in leaderboard_data if not r.get("error")]
            trending_data = [r for r in trending_data if not r.get("error")]
            eval_datasets_data = [r for r in eval_datasets_data if not r.get("error")]

        # ── Append / Custom: crawl user-provided URLs ──────────────
        if url_mode in ("append", "custom") and custom_urls:
            for url in custom_urls:
                logger.info("Benchmark Intel: crawling custom URL", url=url)
                page = await crawl_page.ainvoke({"url": url})
                if isinstance(page, dict):
                    status = page.get("status_code", 0)
                    content_len = page.get("content_length", 0)
                    content = page.get("content", "")
                    if (status == 403 or status == 0 or content_len < 100
                            or ("javascript" in content.lower() and content_len < 200)):
                        logger.info("Benchmark Intel: headless fallback", url=url)
                        page = await fetch_headless.ainvoke({"url": url})
                    if isinstance(page, dict) and page.get("content_length", 0) > 0:
                        custom_page_results.append(page)

        logger.info(
            "Benchmark Intel: Phase 1 — data fetched",
            leaderboard_count=len(leaderboard_data),
            trending_count=len(trending_data),
            eval_datasets_count=len(eval_datasets_data),
            custom_pages=len(custom_page_results),
            errors=len(fetch_errors),
        )

        # Read previous snapshot from memory for comparison
        prev_snapshot = await read_memory.ainvoke({
            "type": "long_term",
            "key": "hf_leaderboard_snapshots",
        })
        prev_data = prev_snapshot.get("value", {}) if isinstance(prev_snapshot, dict) else {}

        # If no data at all, emit empty findings
        total_items = len(leaderboard_data) + len(trending_data) + len(eval_datasets_data) + len(custom_page_results)
        if total_items == 0:
            logger.info("Benchmark Intel: no data fetched, emitting empty findings")
            await write_memory.ainvoke({
                "type": "long_term",
                "key": "last_benchmark_intel_findings",
                "value": json.dumps([]),
            })
            return {"hf_findings": []}

        # ── PHASE 2-3: LLM REASONING ─────────────────────────────
        logger.info("Benchmark Intel: Phase 2-3 — Claude analysing data")

        since = state.get("since_timestamp", "")
        strategy = state.get("strategy_plan", {})

        # Build compact summaries for the prompt
        leaderboard_for_prompt = leaderboard_data[:20]
        trending_for_prompt = []
        for t in trending_data[:15]:
            trending_for_prompt.append({
                "id": t.get("id"),
                "downloads": t.get("downloads"),
                "likes": t.get("likes"),
                "pipeline_tag": t.get("pipeline_tag"),
                "trending_score": t.get("trending_score"),
            })

        eval_for_prompt = []
        for e in eval_datasets_data[:15]:
            eval_for_prompt.append({
                "id": e.get("id"),
                "downloads": e.get("downloads"),
                "likes": e.get("likes"),
                "tags": (e.get("tags") or [])[:5],
            })

        # Build custom pages section for the prompt (if any)
        custom_pages_section = ""
        if custom_page_results:
            custom_summaries = []
            for pg in custom_page_results:
                custom_summaries.append({
                    "url": pg.get("url", ""),
                    "title": pg.get("title", ""),
                    "content": pg.get("content", "")[:2000],
                })
            custom_pages_section = (
                f"--- CUSTOM URL PAGES ({len(custom_summaries)} pages) ---\n"
                f"{json.dumps(custom_summaries, indent=2, default=str)}\n"
                f"--- END CUSTOM PAGES ---\n\n"
            )

        user_prompt = (
            f"Analyse the following HuggingFace benchmark data.\n\n"
            f"--- OPEN LLM LEADERBOARD (top {len(leaderboard_for_prompt)} models) ---\n"
            f"{json.dumps(leaderboard_for_prompt, indent=2, default=str)}\n"
            f"--- END LEADERBOARD ---\n\n"
            f"--- TRENDING MODELS ({len(trending_for_prompt)} models) ---\n"
            f"{json.dumps(trending_for_prompt, indent=2, default=str)}\n"
            f"--- END TRENDING ---\n\n"
            f"--- EVAL DATASETS ({len(eval_for_prompt)} datasets) ---\n"
            f"{json.dumps(eval_for_prompt, indent=2, default=str)}\n"
            f"--- END EVAL DATASETS ---\n\n"
            f"{custom_pages_section}"
            f"Previous snapshot: {json.dumps(prev_data, default=str)}\n"
            f"Since date: {since}\n"
            f"Strategy guidance: {json.dumps(strategy.get('agent_instructions', {}).get('benchmark_intel', ''))}\n\n"
            f"Fetch errors (if any): {fetch_errors}\n\n"
            "IMPORTANT: You MUST produce findings. Do NOT return an empty array when data is present.\n"
            "Report the top leaderboard models, top trending models, and noteworthy eval datasets "
            "as findings. If a previous snapshot is available, also note rank changes. "
            "Flag any SOTA claims with needs_verification=true.\n"
            "Emit the JSON array of Finding objects — aim for at least 3-5 findings."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                BENCHMARK_INTEL_CONFIG["config"]["max_iterations"]
            )},
        )

        structured = result.get("structured_response")
        if structured is not None:
            findings = [f.model_dump() for f in structured.findings]
        else:
            final_text = extract_agent_output(result["messages"])
            findings = parse_json_output(final_text)

        # Validate findings
        for f in findings:
            if not f.get("id"):
                f["id"] = str(uuid.uuid4())
            if not f.get("agent_source"):
                f["agent_source"] = "benchmark_intel"
            if not f.get("impact_score"):
                f["impact_score"] = 0.0

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_benchmark_intel_findings",
            "value": json.dumps(findings),
        })
        # Save current snapshot for next-run comparison
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "hf_leaderboard_snapshots",
            "value": json.dumps({
                "leaderboard_top5": [
                    r.get("model") or r.get(list(r.keys())[0] if r else "")
                    for r in leaderboard_data[:5]
                ] if leaderboard_data else [],
                "trending_top5": [t.get("id") for t in trending_data[:5]],
            }, default=str),
        })

        logger.info("Benchmark Intel: Phase 4 — writing findings", count=len(findings))
        return {"hf_findings": findings}

    except Exception as e:
        logger.exception("Benchmark Intel error", error=str(e))
        return handle_agent_error("benchmark_intel", e)
