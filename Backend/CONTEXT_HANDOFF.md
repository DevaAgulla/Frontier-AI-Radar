# Frontier AI Radar — Complete Context Handoff

**Generated:** 2026-03-05  
**Purpose:** Give a fresh AI chat session the complete state of this project so it can continue from where we left off without losing any context.

---

## 1. What Is This Project?

**Frontier AI Radar** is a daily multi-agent intelligence system built for an internal AI/ML hackathon (2-day, March 5-6, 2026). It automatically:

1. Crawls the AI ecosystem (arXiv, HuggingFace, competitor blogs, model providers, community forums)
2. Uses 14 LLM-powered agents across 6 architectural layers to discover, analyse, verify, rank, and synthesise findings
3. Generates a branded PDF digest with executive summary + deep-dive sections
4. Sends the PDF via email

**Tech stack:** Python 3.12, LangGraph, Google Gemini (gemini-2.0-flash), LangChain Core, xhtml2pdf, JSON file memory.

---

## 2. Architecture

### 2.1 Six-Layer Agent Pipeline

```
Layer 1 (Command)    -> Mission Controller  (sets mission goal)
Layer 2 (Planning)   -> Strategy Planner    (creates execution plan)
Layer 3 (Discovery)  -> Source Scout || Feed Monitor || Trend Scout  (parallel fan-out)
         discovery_join  (fan-in convergence)
Layer 4 (Intel)      -> Research || Competitor || Model || Benchmark  (parallel fan-out)
         intel_join      (fan-in convergence)
Layer 5 (Validation) -> Verification (conditional) -> Ranking
Layer 6 (Synthesis)  -> Digest -> Report Generator -> Notification
```

### 2.2 Agent Pattern

Every agent is built via `build_react_agent()` in `agents/base_agent.py`, which calls `langgraph.prebuilt.create_react_agent` with:
- A `ChatGoogleGenerativeAI` LLM (Gemini)
- A system prompt defining the agent's identity, goals, tools, reasoning steps, and output format
- A list of tools the LLM can autonomously invoke

Each agent node function follows a 4-phase pattern:
- **Phase 1:** Mandatory tools (deterministic Python — crawl data, read memory)
- **Phase 2-3:** Agentic ReAct loop (LLM reasons, optionally calls tools, emits structured output)
- **Phase 4:** Mandatory write (deterministic Python — persist to memory, write to state)

### 2.3 State Management

`pipeline/state.py` defines `RadarState` (TypedDict). Parallel agent outputs use `Annotated[list, add]` reducer to merge safely. Single-writer fields use plain types.

### 2.4 Memory

- **Short-term:** LangGraph TypedDict state (in-process, current run)
- **Long-term:** JSON file at `data/long_term/memory.json` (persists across runs)
- **Entity memory:** ChromaDB (stubbed, not yet wired)

---

## 3. File Structure (Key Files Only)

```
InternalHackathon/
├── agents/
│   ├── base_agent.py              # Agent factory + JSON parsing utilities
│   ├── layer1_mission_controller.py
│   ├── layer2_strategy_planner.py
│   ├── layer3_source_scout.py
│   ├── layer3_feed_monitor.py
│   ├── layer3_trend_scout.py
│   ├── layer4_research_intel.py   # PILOT AGENT — fully wired with real tools
│   ├── layer4_competitor_intel.py
│   ├── layer4_model_intel.py
│   ├── layer4_benchmark_intel.py
│   ├── layer5_verification.py
│   ├── layer5_ranking.py
│   ├── layer6_digest.py
│   ├── layer6_report_generator.py # Deterministic PDF generation
│   └── layer6_notification.py
├── pipeline/
│   ├── graph.py                   # LangGraph StateGraph (6 layers, fan-out/fan-in)
│   ├── state.py                   # RadarState TypedDict
│   ├── router.py                  # Conditional edge functions
│   └── runner.py                  # Entry point (argparse: --mode, --since-days, --debug)
├── core/
│   ├── tools.py                   # All 21 tools (4 real, 17 stubs)
│   └── research_crawler.py        # Real multi-source paper crawler (from teammate)
├── config/
│   ├── settings.py                # Pydantic Settings (Gemini key, paths, iteration caps)
│   ├── research_sources.py        # arXiv + HuggingFace source configs
│   ├── sources.yaml               # Agent source configs (competitor URLs, RSS feeds, etc.)
│   └── scoring.yaml               # Impact scoring weights
├── memory/
│   ├── long_term.py               # JSON file read/write operations
│   ├── schemas.py                 # Memory TypedDict schemas
│   ├── short_term.py              # (unused)
│   └── entity_store.py            # (unused — ChromaDB stub)
├── data/
│   ├── long_term/memory.json      # Persisted long-term memory
│   └── reports/                   # PDF output directory (currently empty)
├── .env                           # API keys (GEMINI_API_KEY, etc.)
├── requirements.txt               # Dependencies (CORE + PHASE 2 sections)
└── python-venv/                   # Python virtual environment
```

---

## 4. What Works Right Now (Verified)

1. **Full 6-layer pipeline executes end-to-end** — all 14 agents run in correct order with proper parallel fan-out/fan-in
2. **Real research crawler** — fetches 100 papers from arXiv + 43 from HuggingFace daily papers
3. **Real long-term memory** — JSON file storage for seen paper IDs, findings, strategy plans, etc.
4. **Research Intelligence Agent (pilot)** — fully wired with real crawl_research_sources tool
5. **Bulletproof JSON parsing** — handles Gemini's code fences, truncated JSON, array/object mismatches, extra text
6. **Gemini integration** — all agents use ChatGoogleGenerativeAI via build_react_agent factory
7. **LangGraph-native ReAct** — all agents use create_react_agent, not hand-coded loops
8. **Partial state updates** — all agents return only the keys they modify (safe for parallel execution)
9. **Debug mode** — `--debug` flag enables full HTTP trace logging
10. **Report Generator** — deterministically calls render_pdf after LLM generates HTML (does NOT rely on LLM to call the tool)

---

## 5. What Is Currently Broken (Two Known Issues)

### Issue 1: `breakpoint()` in render_pdf (BLOCKS PIPELINE)

**File:** `core/tools.py`, line 803  
**Problem:** There is a `breakpoint()` call inside the `_generate()` inner function of the `render_pdf` tool. When the pipeline reaches PDF generation, it hits this breakpoint and freezes waiting for debugger input. The terminal shows the pipeline is stuck.

**Fix:** Delete line 803 (`breakpoint()`) from `core/tools.py`.

```python
# core/tools.py, inside render_pdf -> _generate()
# CURRENT (line 801-804):
        size_bytes = os.path.getsize(pdf_path)
        # xhtml2pdf doesn't expose page count easily; estimate from file
        breakpoint()   # <-- DELETE THIS LINE
        return {
```

### Issue 2: All Papers Already Seen (0 New Papers on Re-Run)

**Problem:** The memory file (`data/long_term/memory.json`) contains all 143 paper IDs from the previous successful run. On subsequent runs, all papers are filtered out as "already seen" (`new_papers=0`). The Research Agent then asks Gemini to score an empty list, which still works but produces fewer/no meaningful findings.

**Fix (for fresh testing):** Delete or rename the memory file before running:
```powershell
Remove-Item data\long_term\memory.json -ErrorAction SilentlyContinue
```

Or increase `--since-days` to get a wider date range with new papers:
```powershell
python -m pipeline.runner --mode research --since-days 3
```

---

## 6. Tool Implementation Status

### Real Implementations (4/21)
| Tool | File | Notes |
|------|------|-------|
| `crawl_research_sources` | `core/tools.py` | Wraps `research_crawler.crawl_research_papers()` |
| `search_arxiv` | `core/tools.py` | Wraps `_fetch_arxiv()` from research crawler |
| `read_memory` | `core/tools.py` | Routes to `memory/long_term.py` for `type="long_term"` |
| `write_memory` | `core/tools.py` | Routes to `memory/long_term.py` for `type="long_term"` |
| `render_pdf` | `core/tools.py` | Real xhtml2pdf implementation (has breakpoint bug) |

### Stubs (17/21)
All other tools return mock data with correct signatures and return shapes:
`crawl_page`, `fetch_rss_feed`, `fetch_headless`, `extract_pdf_docling`, `diff_content`, `search_web`, `search_semantic_scholar`, `search_github_trending`, `search_hackernews`, `search_reddit`, `fetch_hf_leaderboard`, `search_hf_models`, `fetch_hf_model_card`, `diff_leaderboard_snapshots`, `search_entity_memory`, `flag_verification_task`, `compute_impact_score`, `send_email_mcp`

---

## 7. Configuration

### .env File
```
GEMINI_API_KEY=AIzaSyCqZI1erJ_ptblegCRz4zazjD5RvblCDew
GEMINI_MODEL=gemini-2.0-flash
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=frontier-ai-radar
TAVILY_API_KEY=
HF_API_TOKEN=
SEMANTIC_SCHOLAR_API_KEY=
EMAIL_FROM=radar@example.com
EMAIL_RECIPIENTS=team@example.com
API_SECRET_KEY=dev-secret-key-change-in-production
```

### Agent Iteration Caps (config/settings.py)
| Agent | max_iterations | recursion_limit |
|-------|---------------|-----------------|
| mission_controller | 2 | 7 |
| strategy_planner | 2 | 7 |
| source_scout | 5 | 13 |
| feed_monitor | 5 | 13 |
| trend_scout | 6 | 15 |
| research_intel | 6 (settings) | 15 |
| competitor_intel | 6 (settings) | 15 |
| model_intel | 7 (settings) | 17 |
| benchmark_intel | 6 (settings) | 15 |
| verification | 5 | 13 |
| ranking | 5 | 13 |
| digest | 2 | 7 |
| report_generator | 2 | 7 |
| notification | 3 | 9 |

Formula: `recursion_limit = (max_iterations * 2) + 3`

---

## 8. How to Run

### Prerequisites
```powershell
cd C:\Users\RathlavathRameshnaya\Videos\InternalHackathon
.\python-venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run the Pipeline
```powershell
# Research-only mode (fastest, runs only research agent in Layer 4)
python -m pipeline.runner --mode research --since-days 1

# With debug logging
python -m pipeline.runner --mode research --since-days 1 --debug

# Full mode (all agents)
python -m pipeline.runner --mode full --since-days 1

# Fresh run (clear memory first)
Remove-Item data\long_term\memory.json -ErrorAction SilentlyContinue
python -m pipeline.runner --mode research --since-days 2
```

### Expected Output Location
- PDF: `data/reports/digest-YYYYMMDD-HHMMSS.pdf`
- Memory: `data/long_term/memory.json`

---

## 9. Key Design Decisions

1. **Stubs first** — All tool functions are placeholders with correct signatures. Team provides real implementations one by one.
2. **JSON file memory** — No SqliteSaver or database. Phase 1 uses simple JSON files for long-term memory.
3. **Full pipeline always runs** — No conditional skipping of layers. Filtering happens inside each agent (run_mode guard).
4. **Gemini, not Anthropic** — Switched from Claude to Gemini due to API key availability. All functionality identical, only the LLM client changed.
5. **Deterministic PDF generation** — The Report Generator LLM only produces HTML. The `render_pdf` tool is called in Python code, not by the LLM, to guarantee PDF output.
6. **Partial state updates** — Every agent node returns only the state keys it modifies (e.g., `{"research_findings": [...]}` not `{**state, "research_findings": [...]}`). This is required for LangGraph parallel fan-in.

---

## 10. Bugs Fixed (Historical Reference)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `InvalidUpdateError` at parallel fan-in | Agents returned full state `{**state, ...}` instead of partial | Changed all 14 agents to return only modified keys |
| `GraphRecursionError` | Default max_iterations too low for multi-tool agents | Increased per-agent iteration caps |
| Gemini content blocks | `AIMessage.content` is `list[dict]` not `str` | Added block extraction in `extract_agent_output()` |
| `NoneType + list` crash | `read_memory` returns `{"value": None}` not `{"value": []}` | Changed to `(val.get("value") or [])` pattern |
| JSON parse failures | Gemini wraps JSON in code fences, truncates, adds extra text | Built bulletproof `_extract_json()` with fallbacks |
| PDF not generated | LLM skipped calling `render_pdf` tool | Made `render_pdf` call deterministic in Python code |
| `datetime.utcnow()` deprecated | Python 3.12 deprecation warning | Changed to `datetime.now(timezone.utc)` |
| `state_modifier` deprecated | LangGraph renamed parameter | Changed to `prompt=system_prompt` |
| `torch` DLL crash | `sentence-transformers` pulled in torch unnecessarily | Uninstalled torch and related packages |

---

## 11. Immediate Next Steps (Priority Order)

### Must Do Before Next Run
1. **Remove `breakpoint()` from `core/tools.py` line 803** — This is the only thing blocking PDF generation.
2. **Clear memory for fresh testing** — `Remove-Item data\long_term\memory.json`

### High-Value Improvements (Hackathon Day 2)
3. **Implement real `crawl_page` tool** — Used by 8 agents; currently returns mock data. Use httpx + BeautifulSoup.
4. **Implement real `fetch_rss_feed` tool** — Used by Feed Monitor and Competitor Intel. Use feedparser library.
5. **Implement real `search_web` tool** — Used by Source Scout. Needs Tavily API key.
6. **Implement real `fetch_hf_leaderboard` tool** — Used by Benchmark Intel. Use HuggingFace API.
7. **Implement real `compute_impact_score` tool** — Pure math, no API needed. Formula is documented.
8. **Wire email delivery** — MCP email or direct SMTP for the Notification Agent.
9. **Build Streamlit UI** — Team member is handling this separately.

---

## 12. Important Patterns to Follow

### Adding a New Real Tool Implementation
1. Edit the tool function in `core/tools.py`
2. Replace the stub body with real implementation
3. Keep the same `@tool(args_schema=...)` decorator and return type
4. Use `asyncio.get_running_loop().run_in_executor(None, sync_func)` for synchronous code
5. No changes needed in agent files — they already reference the tool by name

### Agent Node Function Template
```python
async def my_agent_node(state: RadarState) -> dict:  # returns PARTIAL state
    try:
        # Phase 1: mandatory tools (deterministic)
        data = await some_tool.ainvoke({...})
        memory = await read_memory.ainvoke({...})

        # Phase 2-3: LLM reasoning (agentic)
        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(max_iterations)},
        )
        findings = parse_json_output(extract_agent_output(result["messages"]))

        # Phase 4: mandatory write (deterministic)
        await write_memory.ainvoke({...})

        return {"my_state_key": findings}  # PARTIAL update only

    except Exception as e:
        return handle_agent_error("my_agent", e)
```

### JSON Parsing (Already Bulletproof)
- `parse_json_output(text)` -> returns `list` (for arrays of findings)
- `parse_json_object(text)` -> returns `dict` (for single objects)
- Both handle: code fences, truncation, extra text, type mismatches

---

## 13. Run Mode Behaviour

| Mode | Layer 3 | Layer 4 | Notes |
|------|---------|---------|-------|
| `full` | All 3 agents | All 4 agents | Complete pipeline |
| `research` | All 3 agents | Only Research Intel | Others return `{}` via run_mode guard |
| `competitor` | All 3 agents | Only Competitor Intel | Others return `{}` |
| `model` | All 3 agents | Only Model Intel | Others return `{}` |
| `benchmark` | All 3 agents | Only Benchmark Intel | Others return `{}` |

Layer 3 (Discovery) always runs because discovered sources feed all Layer 4 agents.

---

## 14. End-to-End Flow Walkthrough (Research Mode)

1. `runner.py` creates initial `RadarState` with `run_mode="research"`, `since_timestamp`
2. **Mission Controller** reads memory, decides focus keywords, emits mission plan
3. **Strategy Planner** refines the plan into agent-specific instructions
4. **Layer 3 fan-out** (parallel): Source Scout, Feed Monitor, Trend Scout run simultaneously
   - All return mock data (stub tools) except Feed Monitor which also uses stubs
5. **discovery_join** waits for all 3, passes through
6. **Layer 4 fan-out** (parallel): Research, Competitor, Model, Benchmark
   - Only Research Intel runs (others skip due to `run_mode="research"` guard)
   - Research Intel: Phase 1 crawls arXiv (100 papers) + HuggingFace (43 papers)
   - Research Intel: Phase 2-3 Gemini scores and selects relevant papers
   - Research Intel: Phase 4 writes findings + seen IDs to memory
7. **intel_join** waits for all 4
8. **Verification** skipped (no verification_tasks)
9. **Ranking Agent** scores and deduplicates all findings
10. **Digest Agent** compiles executive summary + section markdown
11. **Report Generator** converts markdown -> HTML (LLM) -> PDF (deterministic render_pdf)
12. **Notification Agent** composes and "sends" email (stub)
13. Pipeline complete. PDF at `data/reports/digest-{timestamp}.pdf`

---
