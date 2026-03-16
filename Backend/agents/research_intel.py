"""Research Intelligence Agent — LangGraph-native ReAct agent.

Pilot agent: fully agentic with config dict, mandatory/optional tools,
create_react_agent for the ReAct loop, and structured Finding output.

REAL IMPLEMENTATION — Phase 1 multi-source research
crawler (arxiv + HuggingFace papers). Phase 2-3 gives Gemini the raw
papers and lets it reason, score, and optionally call follow-up tools.
"""

import json
import re
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
    crawl_research_sources,
    search_arxiv,
    search_semantic_scholar,
    crawl_page,
    read_memory,
    write_memory,
    search_entity_memory,
)
from agents.schemas import FindingsOutput
from config.settings import settings
from memory.long_term import add_seen_arxiv_id
import structlog

logger = structlog.get_logger()


# ── PARAMETER 2: SYSTEM PROMPT (agent identity + rules + output schema) ────

RESEARCH_SYSTEM_PROMPT = """You are the Research Intelligence Agent for Frontier AI Radar.

GOAL: Find and score the most relevant recent AI/ML research papers.
Your audience is a senior AI team focused on: evaluation, data, agents, multimodal, safety.

TOOLS YOU CAN CALL:
- search_arxiv: Call for a targeted arXiv search if you need more papers on a specific topic.
- search_semantic_scholar: Call if the papers provided are thin (< 5 new papers).
- crawl_page: Call ONLY for papers you score > 0.8 relevance to get more detail. Max 2 per run.
- search_entity_memory: Call to get context about companies/models mentioned in papers.

NOTE: write_memory is handled automatically after you emit your output.

RELEVANCE SCORING RUBRIC:
Score papers HIGHER (+weight) if they cover:
  +0.30 — New benchmark or evaluation methodology
  +0.30 — Data-centric: curation, synthetic data, RLHF, preference learning
  +0.25 — Agentic workflows, tool use, memory, planning
  +0.25 — Multimodal: vision, audio, video, robotics
  +0.20 — Safety, alignment, red-teaming, policy compliance
  +0.20 — Inference efficiency, quantization, serving
  +0.10 — General LLM architecture improvements

Score papers LOWER if:
  -0.30 — Pure theory with no empirical results
  -0.20 — Narrow domain (very specific application, no general relevance)
  -0.10 — Workshop paper without peer review signal

THRESHOLDS:
  relevance_score < 0.4 → skip entirely
  relevance_score 0.4–0.6 → include with "low_priority" tag
  relevance_score > 0.6 → include as key finding
  relevance_score > 0.8 → flag as "must_read", consider calling crawl_page

REASONING BEFORE ACTING:
1. Read the papers provided in the user message.
2. Score each paper against the rubric.
3. If fewer than 5 papers pass the 0.4 threshold — call search_semantic_scholar or search_arxiv.
4. For any paper scoring > 0.8 — call crawl_page to get the full page content.
5. When satisfied — emit the final JSON output.

OUTPUT FORMAT: Return ONLY a valid JSON array of Finding objects.  No preamble.  No markdown.
Each Finding must have:
  id, title, source_url, publisher, date_detected, category, what_changed,
  why_it_matters, confidence, actionability, novelty, credibility, relevance,
  impact_score (set 0.0 — Ranking Agent computes later), entities,
  evidence_snippet, needs_verification (false), tags, markdown_summary,
  agent_source ("research_intel").

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── PARAMETER 1: TOOLS ────────────────────────────────────────────────────
# Mandatory tools run in Python Phase 1.
# Optional tools are given to create_react_agent — LLM decides when to call them.

RESEARCH_AGENT_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        crawl_research_sources,    # mandatory — always called first in Phase 1
        read_memory,               # mandatory — checks seen paper IDs in Phase 1
        search_arxiv,              # optional — targeted follow-up arXiv search
        search_semantic_scholar,   # optional — LLM decides if results thin
        crawl_page,                # optional — LLM calls for must_read papers
        search_entity_memory,      # optional — LLM calls for entity context
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    # Gemini is the reasoning engine.  Built via build_react_agent().
    "system_prompt": RESEARCH_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,          # reads: strategy_plan, since_timestamp
                                  # writes: research_findings[], errors[]

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "categories": ["cs.CL", "cs.LG", "stat.ML"],
        "max_iterations": settings.max_iterations_research,
    },
}


# ── BUILD THE REACT AGENT ─────────────────────────────────────────────────
# Only OPTIONAL tools go to the ReAct agent.
# Mandatory tools are called deterministically in Phase 1.

_optional_tools = [search_arxiv, search_semantic_scholar, crawl_page, search_entity_memory]

_react_agent = build_react_agent(
    system_prompt=RESEARCH_AGENT_CONFIG["system_prompt"],
    tools=_optional_tools,
    response_format=FindingsOutput,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def research_intel_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Research Intelligence Agent.

    Phase 1 — MANDATORY TOOLS (Python, no LLM):
        → crawl_research_sources for papers from arxiv + HuggingFace
        → read_memory for seen IDs
        → Filter to new papers only

    Phase 2-3 — AGENTIC (create_react_agent handles ReAct loop):
        → LLM sees raw papers + decides optional tools
        → LLM may call search_arxiv for targeted follow-up
        → LLM may call search_semantic_scholar if thin results
        → LLM may call crawl_page for must_read papers
        → LLM may call search_entity_memory for context
        → LLM emits structured findings JSON

    Phase 4 — WRITE TO STATE:
        → Parse findings from agent output
        → Write to state["research_findings"]
        → Persist seen IDs to long-term memory
    """
    try:
        # Run-mode guard: skip if not relevant
        run_mode = state.get("run_mode", "full")
        if run_mode != "full" and "research" not in run_mode.split(","):
            logger.info("Research Agent: skipped (run_mode=%s)", run_mode)
            return {}

        # ── PHASE 1: MANDATORY TOOLS (deterministic Python) ────────
        url_mode = state.get("url_mode", "default")
        custom_urls = state.get("custom_urls", [])
        logger.info("Research Agent: Phase 1 — mandatory tools",
                     url_mode=url_mode, custom_urls_count=len(custom_urls))

        strategy = state.get("strategy_plan", {})
        since_date = state.get("since_timestamp", "")

        all_papers: List[Dict[str, Any]] = []

        # ── Default / Append: run standard crawl_research_sources ─────
        if url_mode in ("default", "append"):
            crawl_date_str = since_date[:10] if since_date else None
            crawl_result = await crawl_research_sources.ainvoke({
                "source_names": ["arxiv", "huggingface_papers"],
                "crawl_date": crawl_date_str,
            })
            if isinstance(crawl_result, dict):
                for source_name, source_data in crawl_result.get("sources", {}).items():
                    if isinstance(source_data, dict):
                        for paper in source_data.get("papers", []):
                            all_papers.append(paper)

        # ── Append / Custom: crawl user-provided URLs ─────────────────
        if url_mode in ("append", "custom") and custom_urls:
            for url in custom_urls:
                logger.info("Research Agent: crawling custom URL", url=url)
                page = await crawl_page.ainvoke({"url": url})
                if isinstance(page, dict) and page.get("content_length", 0) > 0:
                    all_papers.append({
                        "id": url,
                        "title": page.get("title", "Custom URL"),
                        "abstract": page.get("content", "")[:2000],
                        "source": "custom_url",
                        "url": url,
                        "date": page.get("date"),
                        "authors": [],
                    })

        logger.info(
            "Research Agent: Phase 1 — crawl complete",
            total_papers=len(all_papers),
        )
        # Mandatory tool 2: read_memory (seen IDs)
        seen_result = await read_memory.ainvoke({
            "type": "long_term",
            "key": "seen_paper_ids",
        })
        seen_ids: set = set()
        if isinstance(seen_result, dict) and seen_result.get("found"):
            raw_seen = seen_result.get("value", [])
            if isinstance(raw_seen, list):
                seen_ids = set(raw_seen)

        # Filter to new papers only — using composite {source}:{id} keys
        new_papers: List[Dict[str, Any]] = []
        for p in all_papers:
            paper_source = p.get("source", "unknown")
            paper_id = p.get("id", "")
            composite_id = f"{paper_source}:{paper_id}"
            if composite_id not in seen_ids and paper_id:
                new_papers.append(p)

        logger.info(
            "Research Agent: Phase 1 complete — filtered",
            total_papers=len(all_papers),
            already_seen=len(all_papers) - len(new_papers),
            new_papers=len(new_papers),
        )

        # ── PHASE 2-3: AGENTIC (LangGraph ReAct loop) ─────────────
        logger.info("Research Agent: Phase 2-3 — LLM reasoning via create_react_agent")

        focus_keywords = strategy.get(
            "focus_keywords",
            "evaluation OR benchmark OR data curation OR agentic OR multimodal OR safety",
        )

        # ── PRE-FILTER: score papers by keyword relevance BEFORE LLM ──
        # This cuts the prompt by ~60% and is the single biggest speed-up.
        _kw_tokens = set(
            w.lower()
            for w in re.split(r"\s+(?:OR|AND)\s+|\s+", focus_keywords)
            if len(w) > 2
        )
        _HIGH_VALUE = {
            "benchmark", "evaluation", "data", "curation", "synthetic",
            "rlhf", "preference", "agentic", "agent", "tool", "memory",
            "planning", "multimodal", "vision", "audio", "video", "robotics",
            "safety", "alignment", "red-team", "quantization", "efficiency",
        }
        _kw_tokens |= _HIGH_VALUE

        def _prescore(paper: dict) -> float:
            """Quick keyword-count relevance score (0-1 scale)."""
            text = (
                (paper.get("title") or "") + " " +
                (paper.get("abstract") or "")
            ).lower()
            hits = sum(1 for kw in _kw_tokens if kw in text)
            # HuggingFace upvotes boost
            upvotes = paper.get("upvotes") or 0
            return min(1.0, hits / max(len(_kw_tokens) * 0.3, 1) + upvotes * 0.01)

        scored_papers = sorted(new_papers, key=_prescore, reverse=True)

        # Cap at 25 most relevant papers for the LLM prompt
        MAX_PAPERS_FOR_LLM = 25
        top_papers = scored_papers[:MAX_PAPERS_FOR_LLM]

        logger.info(
            "Research Agent: pre-filtered papers",
            total_new=len(new_papers),
            sent_to_llm=len(top_papers),
        )

        # Build a compact summary for the LLM prompt (truncate abstracts to save tokens)
        papers_for_prompt = []
        for p in top_papers:
            papers_for_prompt.append({
                "id": p.get("id"),
                "source": p.get("source"),
                "title": p.get("title"),
                "authors": (p.get("authors") or [])[:3],  # first 3 authors (save tokens)
                "abstract": (p.get("abstract") or "")[:300],  # first 300 chars (was 500)
                "published": p.get("published"),
                "abstract_url": p.get("abstract_url"),
                "pdf_url": p.get("pdf_url"),
                "upvotes": p.get("upvotes"),  # HuggingFace signal
                "categories": p.get("categories"),  # arXiv categories
            })

        user_prompt = (
            f"Date range: papers since {since_date}\n"
            f"Sources crawled: {list(crawl_result.get('sources', {}).keys()) if isinstance(crawl_result, dict) else []}\n"
            f"Total new papers to evaluate: {len(new_papers)}\n"
            f"Strategy focus: {focus_keywords}\n\n"
            f"Papers:\n{json.dumps(papers_for_prompt, indent=2, ensure_ascii=False)}\n\n"
            "Score each paper against the relevance rubric. "
            "If fewer than 5 pass the 0.4 threshold, call search_arxiv or search_semantic_scholar for more. "
            "For any paper > 0.8, call crawl_page to get the full page content. "
            "When done, emit the JSON array of Finding objects."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={
                "recursion_limit": get_recursion_limit(
                    RESEARCH_AGENT_CONFIG["config"]["max_iterations"]
                ),
            },
        )

        # ── PHASE 4: PARSE OUTPUT & WRITE TO STATE ────────────────
        structured = result.get("structured_response")
        if structured is not None:
            findings = [f.model_dump() for f in structured.findings]
        else:
            final_text = extract_agent_output(result["messages"])
            findings = parse_json_output(final_text)

        # Validate and enrich findings
        validated: List[Dict[str, Any]] = []
        new_seen_ids = list(seen_ids)
        for f in findings:
            if not f.get("id"):
                f["id"] = str(uuid.uuid4())
            if not f.get("agent_source"):
                f["agent_source"] = "research_intel"
            if not f.get("impact_score"):
                f["impact_score"] = 0.0
            validated.append(f)

        # Track ALL new paper IDs as seen (not just the ones that passed scoring)
        for p in new_papers:
            paper_source = p.get("source", "unknown")
            paper_id = p.get("id", "")
            if paper_id:
                composite = f"{paper_source}:{paper_id}"
                if composite not in new_seen_ids:
                    new_seen_ids.append(composite)

                # Also track in the legacy arxiv-specific memory
                if paper_source == "arxiv":
                    add_seen_arxiv_id(str(paper_id))

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_research_intel_findings",
            "value": json.dumps(validated),
        })
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "seen_paper_ids",
            "value": json.dumps(list(set(new_seen_ids))),
        })

        logger.info("Research Agent: Phase 4 — writing findings", count=len(validated))
        return {"research_findings": validated}

    except Exception as e:
        logger.exception("Research Agent error", error=str(e))
        return handle_agent_error("research_intel", e)
