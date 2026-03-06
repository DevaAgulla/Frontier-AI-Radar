# CURSOR STRICT FIX PROMPT
## Frontier AI Radar — Full Agentic Enhancement (All Agents)

---

## CONTEXT

You have already generated the base code for the Research Intelligence Agent (`agents/layer4_research_intel.py`), the agent factory (`agents/base_agent.py`), and all tool stubs (`core/tools.py`).

The same pattern has been applied to ALL other agents in the system.

This prompt gives you **strict instructions** to fix every issue across ALL agents, implement all real tool functions, and use the **full built-in capabilities of LangGraph, LangChain Core, and the Anthropic SDK** — not manual workarounds.

Do NOT skip any instruction. Do NOT simplify. Apply every fix to EVERY agent file.

---

## STRICT RULE #1 — MANDATORY vs OPTIONAL TOOL SPLIT

### The Problem (Exists in ALL agents right now)
`write_memory` is currently in the optional tools list passed to `create_react_agent`. This means Claude can skip saving memory. This is architecturally wrong. Memory write must ALWAYS happen.

### The Fix — Apply to EVERY Agent File

**WRONG pattern (remove this from all agents):**
```python
_optional_tools = [search_semantic_scholar, crawl_page, search_entity_memory, write_memory]
```

**CORRECT pattern (apply to all agents):**
```python
# Optional tools = ONLY tools Claude decides to call based on observation
_optional_tools = [search_semantic_scholar, crawl_page, search_entity_memory]
# write_memory is NOT optional — it runs deterministically in Phase 4
```

**CORRECT Phase 4 pattern (apply to ALL agents):**
```python
# Phase 4 — MANDATORY deterministic writes (Python, no LLM decision)
await write_memory.ainvoke({
    "type": "long_term",
    "key": "last_{agent_name}_findings",
    "value": json.dumps(validated)
})
await write_memory.ainvoke({
    "type": "long_term", 
    "key": "seen_{agent_name}_ids",
    "value": json.dumps(list(set(new_seen_ids)))
})
```

---

## STRICT RULE #2 — USE LangGraph CHECKPOINTER FOR TRUE MEMORY

### The Problem
Currently memory is manual JSON files. LangGraph has a built-in checkpointer system that persists state across runs natively. Use it.

### The Fix — Implement in `pipeline/graph.py`

```python
# USE THIS — LangGraph built-in persistence
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver

# For hackathon (local SQLite — persists across runs):
checkpointer = SqliteSaver.from_conn_string("data/checkpoints/radar.db")

# Compile graph WITH checkpointer
graph = builder.compile(checkpointer=checkpointer)

# Invoke with thread_id — enables run-to-run memory natively
result = await graph.ainvoke(
    state,
    config={"configurable": {"thread_id": "daily-run"}}
)
```

**Why this matters:** With `SqliteSaver`, LangGraph automatically persists the entire `RadarState` between runs. Yesterday's findings, seen IDs, and strategy plans are available to every agent on the next run WITHOUT any manual JSON read/write. This replaces the entire `memory/long_term.py` JSON approach with LangGraph's native mechanism.

---

## STRICT RULE #3 — USE LangGraph PARALLEL EXECUTION NATIVELY

### The Problem
Layer 3 (Discovery) and Layer 4 (Intelligence) agents are currently called sequentially. LangGraph has native fan-out for parallel execution.

### The Fix — Implement in `pipeline/graph.py`

```python
from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send

# USE THIS — LangGraph native parallel fan-out
builder = StateGraph(RadarState)

# Add all agent nodes
builder.add_node("mission_controller", mission_controller_agent)
builder.add_node("strategy_planner", strategy_planner_agent)
builder.add_node("source_scout", source_scout_agent)
builder.add_node("feed_monitor", feed_monitor_agent)
builder.add_node("trend_scout", trend_scout_agent)
builder.add_node("competitor_intel", competitor_intel_agent)
builder.add_node("model_intel", model_intel_agent)
builder.add_node("research_intel", research_intel_agent)
builder.add_node("benchmark_intel", benchmark_intel_agent)
builder.add_node("verification", verification_agent)
builder.add_node("ranking", ranking_agent)
builder.add_node("digest", digest_agent)
builder.add_node("report_generator", report_generator_agent)
builder.add_node("notification", notification_agent)

# Layer 3 — TRUE PARALLEL (LangGraph fan-out)
builder.add_edge(START, "mission_controller")
builder.add_edge("mission_controller", "strategy_planner")
builder.add_edge("strategy_planner", "source_scout")    # parallel
builder.add_edge("strategy_planner", "feed_monitor")    # parallel
builder.add_edge("strategy_planner", "trend_scout")     # parallel

# Layer 4 — TRUE PARALLEL after all Layer 3 complete
# Use a join node to wait for all Layer 3 agents
builder.add_node("discovery_join", lambda state: state)  # pass-through join
builder.add_edge("source_scout", "discovery_join")
builder.add_edge("feed_monitor", "discovery_join")
builder.add_edge("trend_scout", "discovery_join")

# Layer 4 parallel fan-out from join
builder.add_edge("discovery_join", "competitor_intel")   # parallel
builder.add_edge("discovery_join", "model_intel")        # parallel
builder.add_edge("discovery_join", "research_intel")     # parallel
builder.add_edge("discovery_join", "benchmark_intel")    # parallel

# Intelligence join → conditional routing
builder.add_node("intel_join", lambda state: state)
builder.add_edge("competitor_intel", "intel_join")
builder.add_edge("model_intel", "intel_join")
builder.add_edge("research_intel", "intel_join")
builder.add_edge("benchmark_intel", "intel_join")

# Conditional: verification needed?
builder.add_conditional_edges(
    "intel_join",
    route_after_intelligence,   # checks if verification_tasks[] is non-empty
    {
        "verification": "verification",
        "ranking": "ranking",
    }
)

builder.add_edge("verification", "ranking")
builder.add_edge("ranking", "digest")
builder.add_edge("digest", "report_generator")
builder.add_edge("report_generator", "notification")
builder.add_edge("notification", END)

# Selective run mode router
builder.add_conditional_edges(
    START,
    route_by_run_mode,   # checks state["run_mode"]
    {
        "full": "mission_controller",
        "research": "research_intel",
        "competitor": "competitor_intel",
        "model": "model_intel",
        "benchmark": "benchmark_intel",
    }
)
```

---

## STRICT RULE #4 — USE LangGraph CONDITIONAL EDGES FOR ROUTING

### The Fix — Implement router functions in `pipeline/router.py`

```python
from pipeline.state import RadarState

def route_by_run_mode(state: RadarState) -> str:
    """Entry point router — full run vs selective domain run."""
    return state.get("run_mode", "full")

def route_after_intelligence(state: RadarState) -> str:
    """Route to verification if SOTA claims exist, else straight to ranking."""
    if state.get("verification_tasks"):
        return "verification"
    return "ranking"

def route_after_digest(state: RadarState) -> str:
    """Check if digest needs rewrite (reads as list not narrative)."""
    digest = state.get("digest_markdown", "")
    # Digest agent sets needs_rewrite flag if output is a plain list
    if state.get("digest_needs_rewrite", False):
        return "digest"   # loop back once
    return "report_generator"
```

---

## STRICT RULE #5 — USE LangChain Core TOOL DECORATOR CORRECTLY

### The Problem
Tools currently use basic `@tool` decorator. LangChain Core has richer tool features that make Claude's reasoning significantly better.

### The Fix — Apply to ALL 21 tools in `core/tools.py`

```python
# USE THIS — full LangChain Core tool definition
from langchain_core.tools import tool, StructuredTool
from langchain_core.tools.base import BaseTool
from pydantic import BaseModel, Field

# CORRECT pattern — Pydantic input schema + rich docstring
class SearchArxivInput(BaseModel):
    query: str = Field(description="Search query combining keywords with OR/AND operators")
    categories: list[str] = Field(
        description="arXiv categories to search. Use: ['cs.CL', 'cs.LG', 'stat.ML'] for AI/ML papers"
    )
    since_date: str = Field(
        description="ISO format date string. Only return papers published after this date."
    )

@tool(args_schema=SearchArxivInput)
async def search_arxiv(query: str, categories: list[str], since_date: str) -> list[dict]:
    """
    Search arXiv for recent AI/ML research papers using the official arXiv Python library.

    USE THIS FOR: Primary method for finding recent research papers. Always call this first.
    DO NOT USE FOR: Non-academic content. Use search_web for general web content.
    FALLBACK: If fewer than 5 papers returned, call search_semantic_scholar next.

    RETURNS: List of papers with arxiv_id, title, authors, abstract, published date, pdf_url.
    """
    import arxiv
    import asyncio
    from datetime import datetime

    client = arxiv.Client(num_retries=3, delay_seconds=3)  # built-in rate limiting
    
    category_filter = " OR ".join([f"cat:{c}" for c in categories])
    full_query = f"({query}) AND ({category_filter})"
    
    search = arxiv.Search(
        query=full_query,
        max_results=20,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    
    results = []
    since = datetime.fromisoformat(since_date.replace("Z", "+00:00")) if since_date else None
    
    for paper in client.results(search):
        if since and paper.published.replace(tzinfo=None) < since.replace(tzinfo=None):
            break
        results.append({
            "arxiv_id": paper.entry_id.split("/abs/")[-1],
            "title": paper.title,
            "authors": [a.name for a in paper.authors],
            "abstract": paper.summary,
            "published": paper.published.isoformat(),
            "categories": paper.categories,
            "pdf_url": paper.pdf_url,
            "source_url": paper.entry_id,
        })
    
    return results
```

**Apply this Pydantic input schema pattern to ALL 21 tools.** Every tool must have:
1. A `BaseModel` input schema with `Field(description=...)` for every parameter
2. `@tool(args_schema=YourInputSchema)` decorator
3. Full docstring: what, use for, do not use for, fallback, returns

---

## STRICT RULE #6 — IMPLEMENT ALL REAL TOOL FUNCTIONS

Replace every stub with real implementation. Here are all implementations:

### `read_memory` and `write_memory` — Real Implementation

```python
# memory/long_term.py
import json
import os
from pathlib import Path
from config.settings import settings

MEMORY_PATH = Path(settings.long_term_memory_path)
MEMORY_PATH.mkdir(parents=True, exist_ok=True)

def _get_path(key: str) -> Path:
    safe_key = key.replace("/", "_").replace(":", "_")
    return MEMORY_PATH / f"{safe_key}.json"

async def _read(key: str) -> dict:
    path = _get_path(key)
    if not path.exists():
        return {"found": False, "value": None}
    try:
        with open(path) as f:
            return {"found": True, "value": json.load(f)}
    except Exception:
        return {"found": False, "value": None}

async def _write(key: str, value: str) -> bool:
    path = _get_path(key)
    try:
        with open(path, "w") as f:
            # value is always a JSON string — deserialize then re-serialize for clean storage
            json.dump(json.loads(value) if isinstance(value, str) else value, f, indent=2)
        return True
    except Exception:
        return False

# Then in core/tools.py:
class ReadMemoryInput(BaseModel):
    type: str = Field(description="Memory type: 'long_term' | 'short_term' | 'entity'")
    key: str = Field(description="Memory key to read. Use snake_case. E.g. 'seen_arxiv_ids'")

@tool(args_schema=ReadMemoryInput)
async def read_memory(type: str, key: str) -> dict:
    """Read from memory. Always call at start of agent to check seen IDs and entity context."""
    from memory.long_term import _read
    result = await _read(key)
    return {"type": type, "key": key, **result}

class WriteMemoryInput(BaseModel):
    type: str = Field(description="Memory type: 'long_term' | 'short_term' | 'entity'")
    key: str = Field(description="Memory key to write. Use snake_case.")
    value: str = Field(description="JSON-serialized string value to store.")

@tool(args_schema=WriteMemoryInput)
async def write_memory(type: str, key: str, value: str) -> dict:
    """Write to memory. Always call in Phase 4 after emitting findings."""
    from memory.long_term import _write
    success = await _write(key, value)
    return {"type": type, "key": key, "success": success}
```

### `crawl_page` — Real Implementation

```python
import httpx
from bs4 import BeautifulSoup
from config.settings import settings

class CrawlPageInput(BaseModel):
    url: str = Field(description="Full URL to fetch. Must start with http:// or https://")

@tool(args_schema=CrawlPageInput)
async def crawl_page(url: str) -> dict:
    """
    Fetch and parse HTML from any URL. Headless fallback built-in when content < 300 chars.
    USE THIS FOR: All HTML pages — blogs, changelogs, docs, release notes.
    DO NOT USE FOR: RSS feeds (use fetch_rss_feed). PDFs (use extract_pdf_docling).
    """
    headers = {"User-Agent": "FrontierAIRadar/1.0 (research intelligence bot)"}
    
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
                tag.decompose()
            content = soup.get_text(separator="\n", strip=True)
            title = soup.title.string.strip() if soup.title else ""
            
            # Built-in headless fallback
            if len(content) < 300:
                return await fetch_headless.ainvoke({"url": url})
            
            return {
                "url": url, "title": title, "content": content[:6000],
                "content_length": len(content), "status_code": r.status_code,
                "date": None,
            }
        except Exception as e:
            return {"url": url, "title": "", "content": "", 
                    "content_length": 0, "status_code": 0, "error": str(e)}
```

### `fetch_rss_feed` — Real Implementation

```python
import feedparser

@tool(args_schema=...)
async def fetch_rss_feed(url: str) -> list[dict]:
    """Parse RSS/Atom feed. Always prefer this over crawl_page when RSS URL is available."""
    import asyncio
    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(None, feedparser.parse, url)
    
    return [
        {
            "title": e.get("title", ""),
            "link": e.get("link", ""),
            "published": e.get("published", ""),
            "summary": e.get("summary", "")[:500],
            "author": e.get("author", ""),
        }
        for e in feed.entries[:20]
    ]
```

### `fetch_headless` — Real Implementation

```python
from playwright.async_api import async_playwright

@tool(args_schema=...)
async def fetch_headless(url: str) -> dict:
    """Playwright headless browser. Only for JS-rendered pages. Slower than crawl_page."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            content = await page.inner_text("body")
            title = await page.title()
            return {"url": url, "title": title, "content": content[:6000],
                    "content_length": len(content), "status_code": 200}
        except Exception as e:
            return {"url": url, "title": "", "content": "", 
                    "content_length": 0, "status_code": 0, "error": str(e)}
        finally:
            await browser.close()
```

### `search_semantic_scholar` — Real Implementation

```python
@tool(args_schema=...)
async def search_semantic_scholar(query: str) -> list[dict]:
    """Semantic Scholar fallback. Call when arXiv returns fewer than 5 relevant papers."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": 10,
        "fields": "title,authors,abstract,year,citationCount,externalIds,url",
    }
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    
    return [
        {
            "paper_id": p.get("paperId", ""),
            "title": p.get("title", ""),
            "authors": [a["name"] for a in p.get("authors", [])],
            "abstract": p.get("abstract", ""),
            "year": p.get("year"),
            "citation_count": p.get("citationCount", 0),
            "url": p.get("url", ""),
            