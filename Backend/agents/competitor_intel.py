"""Competitor Intelligence Agent — LangGraph-native ReAct agent.

Monitors competitor product blogs, changelogs, and documentation pages.
Detects real changes (GA releases, pricing shifts, API changes) and
generates structured findings.
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
    crawl_page,
    fetch_rss_feed,
    fetch_headless,
    diff_content,
    read_memory,
    write_memory,
    search_entity_memory,
    search_web,
)
from agents.schemas import FindingsOutput
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

COMPETITOR_INTEL_SYSTEM_PROMPT = """You are the Competitor Intelligence Agent for Frontier AI Radar.

GOAL: Monitor competitor product releases, changelog updates, pricing changes,
and API updates from configured sources.  Detect what ACTUALLY changed — not
just "new page exists" but substantive product or business changes.

TOOLS YOU CAN CALL:
- fetch_headless: Use for JavaScript-rendered pages that crawl_page cannot handle.
- diff_content: Compare old content hash with new content to confirm real changes.
- search_entity_memory: Get context about known competitors.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. Review the crawled pages and RSS entries provided from Phase 1.
2. For each page, check if content actually changed using diff_content.
3. For JS-rendered pages that have empty content, use fetch_headless.
4. Extract structured changes: what changed, when, business impact.
5. Check entity memory for competitor context to improve analysis.
6. Emit findings as JSON array.

RANKING GUIDANCE:
- GA product releases → HIGH priority
- Pricing changes → HIGH priority
- New API endpoints/features → MEDIUM priority
- Documentation updates → LOW priority
- Blog posts with no product changes → SKIP

OUTPUT FORMAT: Return ONLY a valid JSON array of Finding objects.
Each Finding must have:
  id, title, source_url, publisher, date_detected, category, what_changed,
  why_it_matters, confidence, actionability, novelty, credibility, relevance,
  impact_score (0.0), entities, evidence_snippet, needs_verification (false),
  tags, markdown_summary, agent_source ("competitor_intel").

DATE RULE: You must ONLY emit findings where date_detected >= the "Since date" provided.
Do NOT surface content older than the since date. If a page has no date, use today.
Set date_detected to the actual published/detected date in ISO format (YYYY-MM-DD).

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

COMPETITOR_INTEL_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        crawl_page,            # mandatory — crawl configured URLs
        fetch_rss_feed,        # mandatory — check configured RSS feeds
        fetch_headless,        # optional — JS-rendered fallback
        diff_content,          # optional — detect real changes
        read_memory,           # mandatory — previous content hashes
        search_entity_memory,  # optional — competitor context
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": COMPETITOR_INTEL_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,       # writes: competitor_findings[]

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": settings.max_iterations_competitor,
    },
}

_optional_tools = [fetch_headless, diff_content, search_entity_memory, search_web]

_react_agent = build_react_agent(
    system_prompt=COMPETITOR_INTEL_CONFIG["system_prompt"],
    tools=_optional_tools,
    response_format=FindingsOutput,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def competitor_intel_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Competitor Intelligence Agent.

    Phase 1: crawl_page + fetch_rss_feed + read_memory (mandatory)
    Phase 2-3: Claude detects real changes via ReAct
    Phase 4: Write competitor findings to state
    """
    try:
        # Run-mode guard: skip if not relevant
        run_mode = state.get("run_mode", "full")
        if run_mode != "full" and "competitor" not in run_mode.split(","):
            logger.info("Competitor Intel: skipped (run_mode=%s)", run_mode)
            return {}

        url_mode = state.get("url_mode", "default")
        custom_urls = state.get("custom_urls", [])
        since = state.get("since_timestamp", "")
        since_date = since[:10] if since else ""
        logger.info("Competitor Intel: Phase 1 — crawling sources",
                     url_mode=url_mode, custom_urls_count=len(custom_urls),
                     since_date=since_date)

        page_results = []
        page_hashes: dict = {}

        # ── Default / Append: crawl DB sources ────────────────────────
        if url_mode in ("default", "append"):
            from db.persist import get_competitors
            competitor_sources = get_competitors()

            for src in competitor_sources:
                if src.get("type") == "rss":
                    entries = await fetch_rss_feed.ainvoke({
                        "url": src["url"],
                        "since_date": since_date,
                    })
                    if isinstance(entries, list):
                        page_results.extend(entries)
                elif src.get("type") == "webpage":
                    page = await crawl_page.ainvoke({"url": src["url"]})
                    if isinstance(page, dict):
                        page_results.append(page)

        # ── Append / Custom: crawl user-provided URLs ─────────────────
        if url_mode in ("append", "custom") and custom_urls:
            for url in custom_urls:
                logger.info("Competitor Intel: crawling custom URL", url=url)
                page = await crawl_page.ainvoke({"url": url})
                if isinstance(page, dict):
                    # Auto-fallback to headless if blocked
                    status = page.get("status_code", 0)
                    content_len = page.get("content_length", 0)
                    content = page.get("content", "")
                    if (status == 403 or status == 0 or content_len < 100
                            or ("javascript" in content.lower() and content_len < 200)):
                        logger.info("Competitor Intel: headless fallback", url=url)
                        page = await fetch_headless.ainvoke({"url": url})
                    if isinstance(page, dict):
                        page_results.append(page)

        # ── Tavily web search supplement (fills gaps for blocked sites) ─
        _search_names = ["OpenAI", "Anthropic", "Google DeepMind"]
        for name in _search_names[:3]:
            query = f"{name} product release announcement {since_date}"
            try:
                results = await search_web.ainvoke({"query": query})
                if isinstance(results, list):
                    for r in results:
                        if r.get("url"):
                            page_results.append({
                                "url": r.get("url", ""),
                                "title": r.get("title", ""),
                                "content": r.get("snippet", ""),
                                "date": since_date,
                                "source": "tavily_search",
                            })
            except Exception as exc:
                logger.warning("Competitor Intel: search_web failed", name=name, error=str(exc))

        # Collect SHA-256 content hashes for all crawled pages (Fix 3)
        import hashlib as _hashlib
        for item in page_results:
            url = item.get("url") or item.get("link", "")
            content = item.get("content") or item.get("summary", "")
            if url and content:
                page_hashes[url] = _hashlib.sha256(content.encode()).hexdigest()

        # Mandatory: read_memory (previous content hashes)
        prev_hashes = await read_memory.ainvoke({
            "type": "long_term",
            "key": "competitor_content_hashes",
        })

        logger.info("Competitor Intel: Phase 2-3 — Claude reasoning", sources=len(page_results))

        strategy = state.get("strategy_plan", {})

        user_prompt = (
            f"Crawled competitor sources ({len(page_results)} pages/feeds):\n"
            f"{json.dumps(page_results, indent=2)}\n\n"
            f"Previous content hashes: {json.dumps(prev_hashes)}\n"
            f"Since date: {since_date}\n"
            f"Only emit findings where the content was published on or after {since_date}.\n"
            f"Strategy guidance: {json.dumps(strategy.get('agent_instructions', {}).get('competitor_intel', ''))}\n\n"
            "Analyze each source for real product/business changes. "
            "Use diff_content to confirm changes. Use fetch_headless for JS pages. "
            "Use search_web for targeted follow-up searches if needed. "
            "Check entity memory for context. "
            "Emit the JSON array of competitor Finding objects."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                COMPETITOR_INTEL_CONFIG["config"]["max_iterations"]
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
                f["agent_source"] = "competitor_intel"
            if not f.get("impact_score"):
                f["impact_score"] = 0.0

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_competitor_intel_findings",
            "value": json.dumps(findings),
        })
        # Store real SHA-256 content hashes (not finding IDs) so diff_content
        # has valid old_hash values on the next run.
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "competitor_content_hashes",
            "value": json.dumps(page_hashes),
        })

        logger.info("Competitor Intel: Phase 4 — writing findings", count=len(findings))
        return {"competitor_findings": findings}

    except Exception as e:
        logger.exception("Competitor Intel error", error=str(e))
        return handle_agent_error("competitor_intel", e)
