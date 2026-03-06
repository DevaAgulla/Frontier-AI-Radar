# CURSOR PROMPT — FRONTIER AI RADAR
## Complete Implementation Guide (Copy this entire prompt into Cursor)

---

## ROLE & MODEL

You are an **expert AI systems architect and senior Python engineer** building a production-grade, fully agentic multi-agent intelligence system.

- Model in use: **Claude Opus 4.6** (`claude-opus-4-6`)
- Framework: **LangGraph** for agent orchestration
- Follow **industry-grade enterprise Python repo structure** throughout
- Every decision must follow **100% agentic principles** as defined below

---

## PROJECT OVERVIEW

**System Name:** Frontier AI Radar  
**Goal:** A fully autonomous daily intelligence system that monitors the global AI ecosystem and delivers a structured PDF digest via email.

**What it tracks:**
- Competitor product releases (blogs, changelogs, docs)
- Foundation model provider updates (model launches, API changes, pricing, benchmark claims)
- Latest AI/ML research publications (arXiv, Semantic Scholar, OpenReview)
- HuggingFace benchmarking results (leaderboards, SOTA shifts, trending models)

**Final output:** Branded PDF digest + email delivery + web dashboard

---

## THE 5 AGENTIC PROPERTIES — NON-NEGOTIABLE

Every agent in this system MUST satisfy all 5 properties. Do not build any agent that violates these:

1. **Goal-Driven** — Every agent has an explicit goal stated in its system prompt
2. **Autonomous Decision Making** — Claude (not hardcoded logic) decides what tool to call next based on observations
3. **Tool Usage** — Agents act through defined Python tool functions passed to Claude via the Anthropic tools API
4. **Memory / Context** — Every agent reads from memory before acting and writes to memory after emitting
5. **Reasoning Before Acting** — ReAct loop enforced: Observe → Read Memory → Reason → Select Tool → Act → Evaluate → Write Memory → Decide: Loop / Emit / Escalate

**The Golden Rule:**  
> Python tools COLLECT data. Claude THINKS about data. Never the other way around.  
> Mandatory tools always execute first (no LLM decision). Claude then decides whether to call optional tools or emit.

---

## THE REACT LOOP — HOW EVERY AGENT WORKS

```
Phase 1: MANDATORY TOOLS RUN FIRST (Pure Python, No LLM)
  → All required data collection tools execute unconditionally
  → Raw data gathered

Phase 2: CLAUDE OBSERVES + REASONS (First LLM Call)
  → Claude receives all collected raw data
  → Claude reasons: "Is this enough? What's missing? Which optional tool do I need?"

Phase 3: CLAUDE ACTS — OPTIONAL TOOL OR EMIT (Decision Point)
  → If more data needed: Claude calls one optional tool → loop back to Phase 2
  → If data sufficient: Claude emits structured finding → exit loop

Phase 4: WRITE TO STATE + MEMORY (Always)
  → Structured finding written to LangGraph shared state
  → Memory updated for next run

LOOP CAP: Maximum 3 iterations per agent per source. Hard cap. No exceptions.
LOOP TRIGGER: Content length < 300 chars (thin page) — NOT confidence score
CONFIDENCE: Assigned once at emit time as output label only (HIGH/MEDIUM/LOW). Never used as loop controller.
```

---

## CONFIDENCE SCORE RULE — CRITICAL

**DO NOT** use confidence score to control the ReAct loop. This causes infinite loops.

**CORRECT approach:**
- Confidence is an **output metadata label** only
- Assigned by Claude **once** at emit time using these rules:
  - `HIGH` → Official primary source + clear date + concrete change
  - `MEDIUM` → Secondary source OR unclear date OR implied change
  - `LOW` → Third-party repost / scraped summary / no direct evidence
- Loop is controlled by: content length check + hard iteration cap (max 3)

---

## COMPLETE SYSTEM ARCHITECTURE

### 6 Layers, 12 Agents

```
Layer 1 — Mission Control    : Mission Controller
Layer 2 — Planning           : Strategy Planner  
Layer 3 — Discovery (parallel): Source Scout, Feed Monitor, Trend Scout
Layer 4 — Intelligence (parallel): Competitor Intel, Model Intel, Research Intel, Benchmark Intel
Layer 5 — Validation         : Verification Agent, Ranking Agent
Layer 6 — Synthesis/Delivery : Digest Agent, Report Generator, Notification Agent (MCP)
```

### LangGraph Shared State

```python
class RadarState(TypedDict):
    run_id: str
    run_mode: str                    # "full" | "competitor" | "research" | "model" | "benchmark"
    selected_agents: list[str]
    mission_goal: str
    strategy_plan: dict
    since_timestamp: str
    config: dict

    # Discovery outputs
    discovered_sources: Annotated[list[dict], operator.add]
    trend_signals: Annotated[list[dict], operator.add]

    # Intelligence outputs (each agent writes to its slice)
    competitor_findings: Annotated[list[Finding], operator.add]
    provider_findings: Annotated[list[Finding], operator.add]
    research_findings: Annotated[list[Finding], operator.add]
    hf_findings: Annotated[list[Finding], operator.add]

    # Cross-agent communication
    verification_tasks: Annotated[list[VerificationTask], operator.add]
    verification_verdicts: Annotated[list[VerificationVerdict], operator.add]

    # Post-processing
    merged_findings: list[Finding]
    ranked_findings: list[Finding]

    # Final outputs
    digest_json: dict
    digest_markdown: str
    pdf_path: str
    email_status: str
    errors: Annotated[list[AgentError], operator.add]

    # ReAct loop tracking
    agent_iterations: dict          # {agent_name: current_iteration}
```

### Run Modes (Selective Agent Execution)

The system supports two run modes — controlled by `run_mode` in state:

1. **Full Daily Run** — All 12 agents execute (triggered by scheduler or "Run All" in UI)
2. **Selective Domain Run** — User picks domain in UI → only that agent + downstream (Verification → Ranking → Digest → PDF → Notify)

UI triggers:
- "Check Competitors Now" → Competitor Intel → Ranking → Digest → PDF → Notify
- "Check Model Providers Now" → Model Intel → Verification → Ranking → Digest → PDF → Notify
- "Check Research Now" → Research Intel → Ranking → Digest → PDF → Notify
- "Check HF Benchmarks Now" → Benchmark Intel → Verification → Ranking → Digest → PDF → Notify

---

## MEMORY ARCHITECTURE — 3 LAYERS

### Layer 1: Short-Term Memory (In-process)
- **What:** Findings, tool results, observations from the current run only
- **Implementation:** LangGraph TypedDict State (in-memory, zero latency)
- **Cleared:** After each run completes
- **Used by:** All agents — read before acting, write after emitting

### Layer 2: Long-Term Memory (Persistent)
- **What:** Historical findings, past digests, content hashes, trend baselines across runs
- **Implementation:** Local JSON files (Phase 1 hackathon) → ChromaDB (Phase 2)
- **Location:** `data/long_term/` directory
- **Used by:** Strategy Planner (read yesterday's summary), Digest Agent (what changed since yesterday), all agents (novelty check)

### Layer 3: Entity Memory (Vector Store)
- **What:** Known organizations, AI models, benchmarks, papers as embeddings
- **Implementation:** Local ChromaDB instance with `sentence-transformers/all-MiniLM-L6-v2`
- **Location:** `data/entity_store/` directory
- **Used by:** Every agent reads entity context before summarizing — enables awareness like "This is OpenAI's 5th model release this year"

### Memory Tool Interface (used by all agents)
```python
read_memory(type: str, key: str) -> dict     # type: "short_term" | "long_term" | "entity"
write_memory(type: str, key: str, value: any) -> bool
search_entity_memory(query: str, top_k: int) -> list[dict]
```

**Phase 1 (Hackathon):** Long-term = local JSON files in `data/long_term/`  
**Phase 2 (Post-hackathon):** Upgrade to ChromaDB + PostgreSQL — pluggable, no agent code change

---

## TOOL ARCHITECTURE — HOW TOOLS WORK

### Tool Definition Pattern (ALL tools follow this exactly)
```python
# core/tools.py
from langchain_core.tools import tool

@tool
async def tool_name(param: type) -> return_type:
    """
    ONE LINE: What this tool does.
    USE THIS FOR: specific scenarios.
    DO NOT USE FOR: cases where other tools are better.
    RETURNS: exact description of return format.
    """
    # implementation
```

**Why docstrings matter:** Claude reads the docstring to decide whether to call this tool. Write it like you're explaining to a smart colleague what the tool does and when to use it.

### Tool Split Per Agent
Every agent has:
- **Mandatory tools** → Always run first in Python before any LLM call. No Claude decision needed.
- **Optional tools** → Claude decides to call these based on what mandatory tools returned.

### The 21 Tools

**Web Fetching:**
- `crawl_page(url)` — httpx + BeautifulSoup. Primary for all HTML. Headless fallback built-in when content < 300 chars.
- `fetch_rss_feed(url)` — feedparser. RSS/Atom parsing.
- `fetch_headless(url)` — Playwright. JS-rendered pages. Only called by crawl_page internally.
- `extract_pdf_docling(url)` — Docling. Structured PDF extraction (tables, sections, figures as JSON). **Built but OFF by default. Activated via `enable_pdf: true` in agent config.**
- `diff_content(old_hash, new_content)` — hashlib + difflib. Detect real content changes.

**Search & Discovery:**
- `search_web(query)` — Tavily API. General web search. Fallback + discovery.
- `search_arxiv(query, categories, since_date)` — arxiv Python library. Official arXiv API. Rate: 1 req/3s built-in.
- `search_semantic_scholar(query)` — S2 REST API. Citation-rich academic search.
- `search_github_trending()` — httpx + GitHub REST API. Trending AI repos.
- `search_hackernews(query)` — HN Firebase API. Top AI stories.
- `search_reddit(subreddit, query)` — Reddit JSON API (no auth). Community signals.

**HuggingFace:**
- `fetch_hf_leaderboard(leaderboard_name)` — HF Datasets API. Structured leaderboard data.
- `search_hf_models(query, sort)` — HF API. Trending/recent models.
- `fetch_hf_model_card(model_id)` — HF API. Full model details.
- `diff_leaderboard_snapshots(today, yesterday)` — Pure Python dict comparison. Rank movements.

**Memory:**
- `read_memory(type, key)` — reads from appropriate memory layer
- `write_memory(type, key, value)` — writes to appropriate memory layer
- `search_entity_memory(query, top_k)` — ChromaDB semantic search

**Cross-Agent:**
- `flag_verification_task(claim, model, benchmark, source_url)` — Writes to verification_tasks[] in state

**Scoring & Delivery:**
- `compute_impact_score(finding)` — 0.35×Relevance + 0.25×Novelty + 0.20×Credibility + 0.20×Actionability
- `render_pdf(html_content)` — WeasyPrint HTML→PDF
- `send_email_mcp(to, subject, body, pdf_path)` — **MCP-based email delivery (see MCP section below)**

---

## MCP INTEGRATION — NOTIFICATION AGENT

The Notification Agent uses **Model Context Protocol (MCP)** for email delivery instead of direct SMTP.

### Why MCP for Email
- Standardized tool interface — swappable email provider with no code change
- Works with Gmail MCP server, SendGrid MCP, or any MCP-compatible email service
- Consistent with the agentic architecture — agent calls a tool, tool handles protocol

### MCP Email Tool Setup
```python
# The Notification Agent's email tool uses MCP
# Configure in .env: MCP_EMAIL_SERVER_URL, MCP_EMAIL_API_KEY

@tool
async def send_email_mcp(to: list[str], subject: str, body: str, pdf_path: str) -> dict:
    """
    Send email with PDF attachment using MCP email server.
    USE THIS FOR: all email delivery in the notification agent.
    RETURNS: {status: "sent"|"failed", message_id: str, error: str|None}
    """
    # MCP client call to configured email MCP server
```

### MCP Server Options (configure one in .env)
- Gmail MCP: `MCP_SERVER=gmail`
- SendGrid MCP: `MCP_SERVER=sendgrid`  
- SMTP MCP: `MCP_SERVER=smtp`

---

## IMPACT SCORING FORMULA

```
Impact Score = 0.35 × Relevance
             + 0.25 × Novelty
             + 0.20 × Credibility
             + 0.20 × Actionability
```

- **Relevance (0-1):** Claude scores — does this match tracked entities + org priorities (eval, agents, safety, multimodal)?
- **Novelty (0-1):** Python computes — days since similar finding last seen in long-term memory
- **Credibility (0-1):** Rule-based — official primary source=1.0, official secondary=0.7, repost=0.3
- **Actionability (0-1):** Claude scores — does this include concrete change (API/pricing/eval/code)?

---

## FINDING SCHEMA (Output of every intelligence agent)

```python
class Finding(TypedDict):
    id: str                    # uuid
    title: str
    source_url: str
    publisher: str
    date_detected: str         # ISO format
    category: str              # "release"|"research"|"benchmark"|"pricing"|"safety"|"tooling"
    what_changed: str          # max 50 words
    why_it_matters: str        # max 60 words
    confidence: str            # "HIGH"|"MEDIUM"|"LOW" — output label only, never loop controller
    actionability: float       # 0.0-1.0
    novelty: float             # 0.0-1.0
    credibility: float         # 0.0-1.0
    relevance: float           # 0.0-1.0
    impact_score: float        # computed by Ranking Agent
    entities: list[str]        # companies, models, datasets mentioned
    evidence_snippet: str      # direct quote from source, max 40 words
    needs_verification: bool   # True if SOTA/benchmark claim detected
    tags: list[str]
    markdown_summary: str      # formatted for PDF rendering
    agent_source: str          # which agent produced this finding
```

---

## ENTERPRISE REPO STRUCTURE

```
frontier-ai-radar/
│
├── 📁 agents/
│   ├── __init__.py
│   ├── base_agent.py              # Abstract base: run(state) -> state
│   ├── layer1_mission_controller.py
│   ├── layer2_strategy_planner.py
│   ├── layer3_source_scout.py
│   ├── layer3_feed_monitor.py
│   ├── layer3_trend_scout.py
│   ├── layer4_competitor_intel.py
│   ├── layer4_model_intel.py
│   ├── layer4_research_intel.py   # ← BUILD THIS FIRST (pilot agent)
│   ├── layer4_benchmark_intel.py
│   ├── layer5_verification.py
│   ├── layer5_ranking.py
│   ├── layer6_digest.py
│   ├── layer6_report_generator.py
│   └── layer6_notification.py    # Uses MCP for email
│
├── 📁 core/
│   ├── __init__.py
│   ├── tools.py                   # ALL 21 tool definitions
│   ├── fetcher.py                 # HTTP + headless browser internals
│   ├── extractor.py               # HTML→text, RSS parser, Docling PDF
│   ├── change_detector.py         # Content fingerprinting + diff
│   ├── summarizer.py              # Claude API call patterns
│   ├── ranker.py                  # Impact score computation
│   └── embedder.py                # Sentence transformer + ChromaDB ops
│
├── 📁 memory/
│   ├── __init__.py
│   ├── short_term.py              # LangGraph state operations
│   ├── long_term.py               # Local JSON read/write (Phase 1)
│   ├── entity_store.py            # ChromaDB vector store operations
│   └── schemas.py                 # Memory data models
│
├── 📁 pipeline/
│   ├── __init__.py
│   ├── state.py                   # RadarState TypedDict definition
│   ├── graph.py                   # LangGraph StateGraph definition
│   ├── router.py                  # Conditional edge functions
│   ├── runner.py                  # graph.invoke() entry point
│   ├── scheduler.py               # APScheduler daily cron
│   └── retry.py                   # Exponential backoff utilities
│
├── 📁 compiler/
│   ├── __init__.py
│   ├── deduplicator.py            # Hash dedup + semantic dedup
│   ├── narrative_builder.py       # Exec summary + theme detection
│   ├── pdf_renderer.py            # WeasyPrint HTML→PDF
│   └── email_sender.py            # MCP email client
│
├── 📁 api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   └── routes/
│       ├── sources.py             # CRUD for source URLs
│       ├── runs.py                # Trigger run, run history
│       ├── findings.py            # Query findings, filter
│       └── digests.py             # List/download PDFs
│
├── 📁 ui/
│   ├── app.py                     # Streamlit main app
│   └── pages/
│       ├── 1_dashboard.py         # Run status + top findings
│       ├── 2_sources.py           # Source management
│       ├── 3_runs.py              # Run history + logs
│       ├── 4_findings.py          # Findings explorer
│       └── 5_archive.py           # PDF digest archive
│
├── 📁 config/
│   ├── sources.yaml               # All agent source definitions
│   ├── scoring.yaml               # Impact score weights (tunable)
│   └── settings.py                # Loads all config + env vars
│
├── 📁 templates/
│   ├── digest.html                # Branded PDF HTML template
│   └── email_inline.html          # Email body template
│
├── 📁 data/
│   ├── long_term/                 # JSON files for long-term memory
│   │   ├── run_history.json
│   │   ├── content_hashes.json
│   │   └── entity_profiles.json
│   └── entity_store/              # ChromaDB local vector store
│
├── 📁 tests/
│   ├── unit/
│   │   ├── test_tools.py
│   │   ├── test_ranker.py
│   │   └── test_deduplicator.py
│   └── integration/
│       └── test_research_agent_e2e.py
│
├── .env.example                   # All required keys (see ENV section)
├── .env                           # Never commit — gitignored
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## COMPLETE .ENV FILE — ALL KEYS REQUIRED

```env
# ── ANTHROPIC (LLM Brain) ─────────────────────────────────────────────
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_MODEL=claude-opus-4-6

# ── LANGSMITH (Observability — Free Tier) ─────────────────────────────
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=frontier-ai-radar

# ── WEB SEARCH ────────────────────────────────────────────────────────
TAVILY_API_KEY=your_tavily_api_key_here

# ── HUGGINGFACE ────────────────────────────────────────────────────────
HF_API_TOKEN=your_huggingface_token_here

# ── SEMANTIC SCHOLAR ──────────────────────────────────────────────────
SEMANTIC_SCHOLAR_API_KEY=your_s2_api_key_here
# Note: S2 API works without key but rate-limited. Key = higher limits.

# ── MCP EMAIL SERVER ──────────────────────────────────────────────────
MCP_SERVER=gmail                          # gmail | sendgrid | smtp
MCP_EMAIL_SERVER_URL=your_mcp_server_url
MCP_EMAIL_API_KEY=your_mcp_email_key

# ── GMAIL (if MCP_SERVER=gmail) ───────────────────────────────────────
GMAIL_CREDENTIALS_PATH=credentials.json   # OAuth2 credentials file path
EMAIL_FROM=your_email@gmail.com
EMAIL_RECIPIENTS=recipient1@email.com,recipient2@email.com

# ── SENDGRID (if MCP_SERVER=sendgrid) ─────────────────────────────────
SENDGRID_API_KEY=your_sendgrid_api_key
EMAIL_FROM=your_verified_sender@domain.com
EMAIL_RECIPIENTS=recipient1@email.com,recipient2@email.com

# ── MEMORY / STORAGE ──────────────────────────────────────────────────
LONG_TERM_MEMORY_PATH=data/long_term      # local JSON storage (Phase 1)
ENTITY_STORE_PATH=data/entity_store       # ChromaDB local path
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# ── PDF / REPORTS ─────────────────────────────────────────────────────
REPORTS_OUTPUT_PATH=data/reports
PDF_BRAND_NAME=Frontier AI Radar
PDF_BRAND_COLOR=#2563eb

# ── ARXIV (no key needed — built-in rate limiting) ────────────────────
ARXIV_RATE_LIMIT_SECONDS=3               # seconds between requests

# ── PLAYWRIGHT (headless browser) ─────────────────────────────────────
PLAYWRIGHT_BROWSER=chromium              # chromium | firefox | webkit

# ── DOCLING (PDF — optional, off by default) ──────────────────────────
ENABLE_PDF_GLOBALLY=false                # true to activate for all agents
DOCLING_TABLE_EXTRACTION=true           # extract tables as structured JSON

# ── SCHEDULER ─────────────────────────────────────────────────────────
DAILY_RUN_TIME=06:30                     # 24h format, server timezone
TIMEZONE=Asia/Kolkata

# ── FASTAPI ───────────────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
API_SECRET_KEY=your_random_secret_key_here

# ── STREAMLIT ─────────────────────────────────────────────────────────
STREAMLIT_PORT=8501

# ── RATE LIMITING ─────────────────────────────────────────────────────
MAX_PAGES_PER_DOMAIN=10
DEFAULT_CRAWL_RATE_SECONDS=2
MAX_CONCURRENT_AGENTS=4

# ── AGENT ITERATION CAPS ──────────────────────────────────────────────
MAX_ITERATIONS_COMPETITOR=3
MAX_ITERATIONS_RESEARCH=3
MAX_ITERATIONS_MODEL=3
MAX_ITERATIONS_BENCHMARK=3
MIN_CONTENT_LENGTH_CHARS=300             # below this = thin page = try fallback
```

---

## PHASE 1 BUILD PLAN — RESEARCH AGENT PILOT (DO THIS FIRST)

**Philosophy:** Build ONE complete end-to-end vertical. Not all agents at once. The Research Intelligence Agent is the pilot because:
- arXiv API is the cleanest, most reliable data source (no scraping)
- No headless browser needed (reduces complexity)
- No cross-agent verification needed (no SOTA claims in research agent)
- Full ReAct loop is meaningful and demonstrable
- Once working: all other agents are replicas with different tools + prompts

### What "Complete End-to-End" Means for the Pilot

```
sources.yaml (research config)
     ↓
pipeline/runner.py (selective mode: run_mode="research")
     ↓
pipeline/graph.py (routes to research agent only)
     ↓
agents/layer4_research_intel.py (full ReAct loop)
     ↓ uses ↓
core/tools.py → search_arxiv() + search_semantic_scholar() + read_memory() + write_memory()
     ↓
memory/long_term.py (JSON) + memory/entity_store.py (ChromaDB)
     ↓
layer5_ranking.py (impact score on research findings)
     ↓
layer6_digest.py (research-only digest)
     ↓
layer6_report_generator.py (PDF with research section)
     ↓
layer6_notification.py (MCP email with PDF attached)
     ↓
ui/ (Streamlit dashboard shows research findings)
```

**Every piece of infrastructure built for the Research Agent pilot is REUSED by all other agents. The other agents are then plug-and-play.**

---

## RESEARCH INTELLIGENCE AGENT — COMPLETE SPECIFICATION

### Agent Goal (system prompt opening)
```
You are a Research Intelligence Agent for the Frontier AI Radar system.
Your goal: Identify the most relevant recent AI/ML research publications
for a team focused on: data curation, evaluation methodology, agentic 
workflows, multimodal AI, safety/alignment, and inference efficiency.
```

### Execution Order (DO NOT DEVIATE)
```
STEP 1 — MANDATORY (Python, no LLM):
  papers = await search_arxiv(
      query=state["strategy_plan"]["focus_keywords"],
      categories=["cs.CL", "cs.LG", "stat.ML"],
      since_date=state["since_timestamp"]
  )

STEP 2 — MANDATORY (Python, no LLM):
  seen_ids = await read_memory("long_term", "seen_arxiv_ids")
  new_papers = [p for p in papers if p["arxiv_id"] not in seen_ids]

STEP 3 — OPTIONAL (if new_papers < 5, Python, no LLM):
  more_papers = await search_semantic_scholar(
      query=state["strategy_plan"]["focus_keywords"]
  )
  new_papers = deduplicate(new_papers + more_papers)

STEP 4 — MANDATORY (Single Claude call with ALL collected data):
  Pass: all new_papers titles + abstracts + entity context from memory
  Claude: scores each paper on relevance rubric, picks top papers,
          writes structured findings with evidence

STEP 5 — OPTIONAL (Claude decides — for papers scored > 0.8 only):
  Claude calls: fetch_webpage(arxiv_full_url)
  Max 2 papers get this treatment per run

STEP 6 — MANDATORY (Python, no LLM):
  Write findings to state["research_findings"]
  Update seen_arxiv_ids in long_term memory
  Update entity memory with new models/papers mentioned
```

### Relevance Scoring Rubric (in Claude system prompt)
```
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

THRESHOLD: relevance_score < 0.4 → skip entirely
           relevance_score 0.4-0.6 → include with "low_priority" tag
           relevance_score > 0.6 → include as key finding
           relevance_score > 0.8 → flag as "must_read", fetch full page
```

### Tools Available to Research Agent
```python
tools = [
    search_arxiv,            # MANDATORY — always runs first
    search_semantic_scholar, # OPTIONAL — fallback if arxiv thin
    fetch_webpage,           # OPTIONAL — only for must_read papers
    read_memory,             # MANDATORY — check seen IDs + entity context
    write_memory,            # MANDATORY — save seen IDs + new findings
    search_entity_memory,    # OPTIONAL — get entity context for scoring
]
```

---

## ALL OTHER AGENTS — HOW TO REPLICATE (After Pilot Works)

Once the Research Agent pilot is end-to-end working, each additional agent follows the same pattern:

```
1. Copy agents/layer4_research_intel.py → rename for new agent
2. Replace tools[] with agent-specific tools
3. Replace system_prompt with agent-specific goal + rules
4. Replace state read/write keys (research_findings → competitor_findings etc.)
5. Update pipeline/graph.py to add new node
6. Update config/sources.yaml with new agent's sources
```

**Agents in order of addition after pilot:**
1. ✅ Research Agent (pilot — build first)
2. Competitor Intelligence (same pattern, different tools: crawl_page + fetch_rss_feed)
3. Model Intelligence (adds: flag_verification_task tool)
4. Benchmark Intelligence (adds: fetch_hf_leaderboard + diff_leaderboard_snapshots)
5. Verification Agent (consumes verification_tasks from Model Intel)
6. Source Scout + Feed Monitor + Trend Scout (Layer 3)
7. Mission Controller + Strategy Planner (Layer 1+2)

---

## AGENT PROMPT TEMPLATES — RESEARCH AGENT (FULL)

### System Prompt
```
You are the Research Intelligence Agent for Frontier AI Radar.

GOAL: Find the most relevant recent AI/ML research papers published since {since_date}.
Your audience is a senior AI team focused on: evaluation, data, agents, multimodal, safety.

TOOLS AVAILABLE:
- search_arxiv: Use for primary paper discovery. Already called — results provided.
- search_semantic_scholar: Use if arxiv results are thin (< 5 new papers). 
- fetch_webpage: Use ONLY for papers you score > 0.8 relevance. Max 2 per run.
- read_memory / write_memory: Use to check seen papers and save results.
- search_entity_memory: Use to get context about companies/models mentioned in papers.

RELEVANCE SCORING RUBRIC:
{relevance_rubric}

OUTPUT RULES:
- Score every paper. Skip papers below 0.4.
- Never report a paper you haven't read the abstract of.
- Evidence snippet must be a direct quote from the abstract.
- Confidence: HIGH if peer-reviewed venue, MEDIUM if arXiv preprint, LOW if workshop.

OUTPUT FORMAT: Return ONLY valid JSON array of Finding objects. No preamble. No markdown.
```

### Per-Iteration User Prompt
```
Iteration: {current_iteration} of {max_iterations}

ARXIV RESULTS ({paper_count} new papers since {since_date}):
{papers_json}

ENTITY CONTEXT FROM MEMORY:
{entity_context}

STRATEGY FOCUS TODAY: {strategy_plan_keywords}

Your task:
1. Score each paper against the relevance rubric
2. For papers > 0.8 relevance — call fetch_webpage to get more detail
3. For all papers >= 0.4 — emit structured Finding objects
4. If total results < 5 — call search_semantic_scholar with refined query

Return findings as JSON array OR make a tool call. Do not do both.
```

---

## CODING STANDARDS — ENTERPRISE GRADE

### Python Standards
- Python 3.11+
- Type hints on every function signature
- Pydantic models for all data structures
- async/await throughout (all agents are async)
- All external calls wrapped in try/except with typed error handling
- Logging with structlog (not print statements)
- No hardcoded values — everything from config/settings.py or .env

### LangGraph Standards
- Every agent is a pure async function: `async def agent_name(state: RadarState) -> RadarState`
- Return `{**state, "field": new_value}` — never mutate state directly
- All parallel agents use `asyncio.gather(*tasks, return_exceptions=True)`
- Partial failure tolerance: `isinstance(result, Exception)` check on every gather result

### Tool Standards
- Every tool has a complete docstring with: what, when to use, when NOT to use, return format
- Every tool handles its own retry (max 3, exponential backoff) internally
- Every tool respects rate limits internally — callers don't manage this
- Tools never raise exceptions to agents — return error dict instead

### File Standards
- One agent per file in agents/
- All tools in one file: core/tools.py
- All Claude prompts as module-level constants (not inline strings)
- Config loaded once at startup via config/settings.py
- Secrets only from .env via python-dotenv

---

## SETUP INSTRUCTIONS FOR CURSOR

### Step 1: Project initialization
```bash
mkdir frontier-ai-radar && cd frontier-ai-radar
python -m venv venv && source venv/bin/activate
pip install langgraph langchain-anthropic langsmith anthropic
pip install httpx beautifulsoup4 feedparser playwright arxiv
pip install chromadb sentence-transformers
pip install fastapi uvicorn streamlit
pip install weasyprint pydantic python-dotenv structlog
pip install apscheduler tavily-python
pip install docling  # PDF tool — build but keep disabled
playwright install chromium
```

### Step 2: Create folder structure
Create every folder and `__init__.py` as defined in the repo structure above.

### Step 3: Create `.env` from the complete template above
Fill in all keys. Never commit `.env`.

### Step 4: Build in this exact order
```
1. pipeline/state.py          — RadarState TypedDict
2. memory/long_term.py        — JSON read/write helpers
3. memory/entity_store.py     — ChromaDB setup + operations
4. core/tools.py              — All 21 tools (stubs first, implement progressively)
5. agents/base_agent.py       — Abstract base class
6. agents/layer4_research_intel.py  — PILOT AGENT (full implementation)
7. pipeline/graph.py          — LangGraph graph (research-only selective mode first)
8. pipeline/runner.py         — run_radar(mode="research", config)
9. layer5_ranking.py          — Impact scoring on research findings
10. layer6_digest.py          — Research-only digest
11. layer6_report_generator.py — PDF with research section
12. layer6_notification.py    — MCP email delivery
13. api/main.py + routes      — FastAPI backend
14. ui/app.py + pages         — Streamlit dashboard
15. Test end-to-end research run
16. Add remaining agents one by one (replicas of research agent pattern)
```

### Step 5: First test command
```bash
python -c "from pipeline.runner import run_radar; import asyncio; asyncio.run(run_radar(mode='research'))"
```

---

## WHAT SUCCESS LOOKS LIKE FOR THE PILOT

When the Research Agent pilot is working correctly, you should see:

1. `python pipeline/runner.py --mode research` runs without errors
2. arXiv is queried, new papers are found
3. Claude scores papers and emits structured findings
4. Findings appear in `data/long_term/research_findings.json`
5. Seen paper IDs saved so next run doesn't re-report
6. Impact scores computed and findings ranked
7. PDF generated at `data/reports/YYYY-MM-DD-research.pdf`
8. Email sent via MCP with PDF attached
9. Streamlit dashboard shows findings at `localhost:8501`
10. LangSmith trace shows full agent execution graph

Once all 10 are working → add next agent. Repeat until all 12 agents are live.

---

## FINAL REMINDER — WHAT MAKES THIS GENUINELY AGENTIC

Do not build any of the following — they make the system a pipeline, not an agent:

❌ Hardcoded tool call sequences where Claude has no choice  
❌ Confidence score as a loop controller  
❌ Claude calling tools one at a time when data could be batched  
❌ Agents that cannot handle partial failures gracefully  
❌ Memory that is written but never read back  
❌ Tools without docstrings (Claude can't reason about them)  
❌ State mutations (always return new state, never mutate)  

Build only this:

✅ Mandatory tools run first → Claude observes → Claude decides optional tools or emit  
✅ Hard iteration cap (max 3) — never infinite  
✅ Confidence as output label only  
✅ All data batched into single Claude calls where possible  
✅ Partial failure returns error in state, doesn't crash pipeline  
✅ Memory read at start of every agent, written at end  
✅ Every tool has docstring that teaches Claude when to use it  
✅ Every agent returns `{**state, updated_field: new_value}`  
