# Frontier AI Radar — Full Project Context
### Last Updated: 13 March 2026
### Author: Ramesh Nayak (LLMafia)

---

## 1. WHO IS INVOLVED

| Person | Role | Context |
|---|---|---|
| **Ramesh Nayak** | Team Lead, LLMafia | Primary developer, architect, driving the project |
| **Mahesh Kola** | Team Member, LLMafia | Co-builder during hackathon |
| **Devaraj Agulla** | Team Member, LLMafia | Co-builder during hackathon |
| **Abhishek Mukherji** | AVP / VP (Centific) | Sponsor, gave the 4 enhancement requirements, daily cadence call owner |
| **Harshit Rajgarhia** | Technical Lead (Centific) | Technical counterpart, joins daily cadence calls |
| **Narsi Rangachari** | Senior Leader (Centific) | Announced hackathon results |
| **Ganesh Balasubramanian** | VP Delivery (Centific) | Sent company-wide congratulations |
| **Vasudevan Sundarababu** | Senior Leader (Centific) | Congratulated team, part of leadership thread |

**Daily Cadence:** 8:00 AM PT / 8:30 PM IST — Friday (start) through the following week. Then 1x/week after launch.

---

## 2. HOW WE GOT HERE — THE FULL STORY

### Hackathon
- **Company:** Centific (AI services company)
- **Problem Statement:** Build "Frontier AI Radar" — an autonomous system that tracks the AI ecosystem daily and delivers an intelligence digest
- **Required to track:** Competitor product releases, foundation model provider updates, arXiv research papers, HuggingFace benchmark movements
- **Required output:** PDF digest emailed daily with ranked findings
- **Duration:** 48 hours
- **Teams:** 20 teams participated

### What LLMafia Built (in 48 hours)
A fully autonomous multi-agent intelligence system:
- **11-agent LangGraph pipeline** across 6 layers
- **Layer 1:** Mission Controller
- **Layer 2:** Strategy Planner
- **Layer 3:** 4 parallel intelligence agents (Competitor, Model, Research, Benchmark)
- **Layer 4:** Verification Agent + Ranking Agent
- **Layer 5:** Digest Agent → Report Generator → Notification Agent
- **SOTA Verification:** When a model claims SOTA on a benchmark, the Verification Agent independently checks HuggingFace leaderboards and returns: confirmed / contradicted / unclear
- **Memory:** Short-term (LangGraph state) + Long-term (JSON files) + Entity memory (ChromaDB)
- **Output:** PDF digest + email via Brevo
- **Frontend:** Next.js deployed on Vercel
- **Backend:** FastAPI deployed on Railway
- **LLM:** Claude via OpenRouter (also supports Gemini as fallback)
- **Framework:** LangGraph (langgraph.prebuilt.create_react_agent)

### Hackathon Result
- **Score: 178/200 — Highest across all 20 teams**
- **Winner: LLMafia**
- Judges specifically called out: 12-agent pipeline, SOTA Verification Agent, live deployed product, "near production-grade"
- Official quote: *"The panel was particularly struck by the maturity and conviction behind their work — especially the philosophy: 'Build it right, not just build it fast.'"*

### What Happened Next
After the hackathon results, Abhishek Mukherji (AVP) reached out with 4 enhancement requirements and set up a daily cadence to take this to full production launch within 1 week.

---

## 3. THE CODEBASE — CURRENT STATE

**Repository location:** `c:/Users/RathlavathRameshnaya/Videos/InternalHackathon/`

```
InternalHackathon/
├── Backend/
│   ├── agents/
│   │   ├── base_agent.py          ← LLM factory + create_react_agent wrapper
│   │   ├── mission_controller.py  ← Layer 1
│   │   ├── strategy_planner.py    ← Layer 2
│   │   ├── competitor_intel.py    ← Layer 3a
│   │   ├── model_intel.py         ← Layer 3b (flags SOTA claims)
│   │   ├── research_intel.py      ← Layer 3c
│   │   ├── benchmark_intel.py     ← Layer 3d
│   │   ├── verification.py        ← Layer 4a
│   │   ├── ranking.py             ← Layer 4b (deterministic scoring)
│   │   ├── digest.py              ← Layer 5a
│   │   ├── report_generator.py    ← Layer 5b (Jinja2 → PDF)
│   │   └── notification.py        ← Layer 5c (email via Brevo)
│   ├── pipeline/
│   │   ├── graph.py               ← Full LangGraph graph definition
│   │   └── state.py               ← RadarState TypedDict (shared state)
│   ├── memory/
│   │   ├── short_term.py          ← LangGraph state wrapper
│   │   ├── long_term.py           ← JSON file storage (to be replaced)
│   │   └── entity_store.py        ← ChromaDB vector store (to be replaced)
│   ├── tools/                     ← All @tool decorated functions
│   ├── config/
│   │   └── settings.py            ← Pydantic BaseSettings, .env driven
│   ├── templates/
│   │   └── digest.html            ← Jinja2 PDF template
│   └── db/                        ← SQLite persistence (to be replaced)
├── frontend/                      ← Next.js app (Vercel)
└── Plannings/                     ← This file lives here
```

### What Is Fully Working (Production Quality)
- All 11 agent nodes — real LLM reasoning, real data
- arXiv + HuggingFace Papers crawling — real APIs
- Foundation model provider fetching — real sources
- HuggingFace leaderboard data — real APIs
- Conditional verification routing (fires only when SOTA claims detected)
- Deterministic impact scoring: `0.35×relevance + 0.25×novelty + 0.20×credibility + 0.20×actionability`
- PDF generation (WeasyPrint + Jinja2)
- Email delivery (Brevo API)
- FastAPI backend (all routes)
- Next.js frontend (dashboard, findings, run trigger, PDF download)
- APScheduler daily run

### What Is a Stub / Incomplete (Known, Documented)
| Tool/Component | Status | Notes |
|---|---|---|
| `search_semantic_scholar` | Mock data | Returns placeholder |
| `search_web` (Tavily) | Mock data | API key needed |
| `search_github_trending` | Mock data | GitHub API needed |
| `search_hackernews` | Mock data | HN Algolia API |
| `search_reddit` | Mock data | Reddit API |
| `diff_content` | Mock comparison | No real content diff |
| `diff_leaderboard_snapshots` | Mock diff | No real comparison |
| `compute_impact_score` | Mock score | Bypassed by deterministic ranker |
| Entity memory (ChromaDB) | Built but EMPTY | Zero entities loaded — search returns nothing |
| LangSmith tracing | In architecture, not enabled | Env var exists but tracing off |
| robots.txt checking | Not implemented | Fetcher makes direct requests |

### The Core LLM Setup (base_agent.py)
Every agent is built through one factory function:
```python
# Current (30% capability)
create_react_agent(
    model=model,
    tools=tools,
    prompt=system_prompt
)
```
Using: `from langgraph.prebuilt import create_react_agent` — correct modern LangGraph version.

---

## 4. THE 4 ENHANCEMENT REQUIREMENTS (From Abhishek)

### Enhancement 1: Freshness
**Requested:** Weekly digest vs. triggered by a big event (GTC)
**Today:** Daily fixed schedule only, no other modes
**Plan:**
- `run_mode="weekly"` — aggregates last 7 days, synthesizes trends
- Event-triggered runs — keyword monitoring (GTC, GPT-5, Claude 4, AI Act etc.), fires immediately on match, Redis TTL cooldown (24h)

### Enhancement 2: Personas
**Requested:** CAIR/AI COE (technical), Sales (competitive), Account Managers (customer lens), Leadership (market direction). Trend across multiple weeks.
**Today:** Single generic digest for all audiences
**Plan:**
- 4 persona-aware digest prompts in `digest.py`
- 4 Jinja2 PDF templates
- Per-persona email distribution
- Customer profiles table (for Account Manager persona — manually entered by AMs)
- Trend digest: `POST /digest/trend?weeks=4&persona=leadership`

### Enhancement 3: Validation
**Requested:** Validation from different people in Centific before distribution
**Today:** Zero human review — digest compiles and sends immediately
**Plan:**
- Section-specific review workflow: AI COE reviews Research, Sales reviews Competitor section, Leadership approves Executive Summary
- LangGraph `interrupt_before` on notification agent — pipeline pauses, waits for approvals
- Redis pub/sub — approval signal resumes the graph
- Review UI in Next.js: `/review/:run_id` with approve / request-changes per section
- 2-hour timeout → auto-distributes with "Unreviewed" watermark

### Enhancement 4: Voice Agent
**Requested:** Podcast style, news style, highlights, then "go into detail for X"
**Today:** Nothing voice-related
**Plan:**
- Phase 1: Pre-generated audio — ElevenLabs (podcast, two-host) + Azure TTS (news, anchor style). Generated per run, per persona. Audio player in email + UI.
- Phase 2: Interactive — Vapi.ai handles STT+TTS loop. FastAPI webhook `POST /voice/query`. pgvector semantic search over today's findings. User says "go deeper on X" → system responds.

---

## 5. FOUNDATION UPGRADES REQUIRED (Enables All 4 Enhancements)

### 5A — `create_react_agent` Full Utilization

Upgrade `base_agent.py` factory to use full LangGraph capabilities:

```python
create_react_agent(
    model=model,
    tools=tools,
    prompt=system_prompt,
    checkpointer=PostgresSaver(pg_conn),   # persistent memory, enables interrupt/resume
    store=PostgresStore(pg_conn),          # cross-agent shared memory, replaces ChromaDB
    response_format=AgentOutputSchema,     # structured output, kills all JSON parsing code
)
```

| Parameter | What It Unlocks |
|---|---|
| `checkpointer` | Review workflow pause/resume · Trend digest memory · Persona continuity |
| `store` | Entity memory (replaces ChromaDB) · Customer profiles · Replaces JSON memory files |
| `response_format` | No more manual JSON parsing — eliminates ~150 lines of brittle repair code |
| `interrupt_before=["tools"]` | Human review gate — notification agent pauses, waits for approval |
| `.astream()` | Voice streaming — user hears response as tokens generate |

### 5B — Single PostgreSQL Database (Replaces 3 Systems)

Replace: SQLite + ChromaDB + JSON files → **PostgreSQL + pgvector extension**

```
PostgreSQL + pgvector
├── Relational tables
│   ├── runs, extractions, findings, reports     ← replaces SQLite
│   ├── personas, customers, subscriptions       ← new (Personas)
│   ├── review_queue, review_comments            ← new (Validation)
│   ├── event_triggers, event_log               ← new (Freshness)
│   └── memory_kv                               ← replaces JSON files
└── Vector columns (pgvector)
    ├── entities.embedding                       ← replaces ChromaDB
    └── findings.embedding                       ← semantic search for voice
```

Redis: job queue + review pub/sub + event cooldown TTLs + digest cache
S3/Azure Blob: PDF and audio file storage (Railway filesystem is ephemeral)

### 5C — Entity Memory (Currently Empty — Must Be Populated)

The entity store infrastructure exists but has ZERO entities. Every agent calls `search_entity_memory()` and gets nothing back.

**Three entity types needed:**
1. **Organizations** — OpenAI, Anthropic, Google DeepMind, Meta AI, Mistral, Cohere + research labs
2. **Models** — GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro, Llama 3.1, Mistral Large, Deepseek R1 etc.
3. **Benchmarks** — MMLU, HumanEval, MATH, GPQA, MT-Bench, SWE-bench etc.
4. **Centific Customers** — manually entered by AMs for Account Manager persona

**Three population mechanisms:**
1. **Seed YAML** (one-time, before first production run): `data/seed/entities.yaml` — 50 curated entities
2. **Live enrichment node** (every run): new `entity_enrichment` node after `intel_join` — extracts entity names from findings, upserts profiles
3. **Weekly refresh** (scheduled): re-crawl entity source pages for latest pricing/products

**Impact:** Without entity memory → generic summaries. With entity memory → contextually rich summaries with history, pricing, competitive positioning.

---

## 6. THE 6-DAY DELIVERY PLAN

| Day | What Gets Built | End-of-Day State |
|---|---|---|
| **Day 0** (setup) | Provision Railway PostgreSQL + Redis · S3/Azure Blob · ElevenLabs + Vapi accounts · Seed YAML written | All external services ready |
| **Day 1** | PostgreSQL migration · pgvector schema · Entity seed loaded · `create_react_agent` upgrades (checkpointer + store + response_format) | System runs on PostgreSQL, entity memory live |
| **Day 2** | Fix 6 stub tools (Tavily, GitHub, diff_content, diff_leaderboard, HackerNews, Semantic Scholar) · Entity enrichment node | Real data from all sources, entity store grows each run |
| **Day 3** | 4 persona digests · 4 PDF templates · Per-persona email · Customer profiles UI | Same pipeline → 4 different outputs |
| **Day 4** | Review workflow (interrupt_before + Redis pub/sub + Next.js review page) · Weekly digest mode · Event-triggered runs | Human approval gate live, freshness working |
| **Day 5** | Voice Phase 1 (ElevenLabs + Azure TTS + audio player in email/UI) · Account Manager persona with customer context | Audio digest live |
| **Day 6** | Voice Phase 2 (Vapi interactive) · Stabilization · End-to-end test · Production deploy | Full launch |

---

## 7. WHAT IS NEEDED FROM CENTIFIC SIDE

### Decisions Required
1. Which 2 personas ship first if time gets tight? (Suggested: Leadership + CAIR)
2. Named reviewers per section — who validates Research? Competitor? Executive Summary?
3. Event trigger keyword list — confirm: GTC, GPT-5, Claude 4, Gemini 3, AI Act + others?
4. Voice style preference — review ElevenLabs samples before picking, or ship and iterate?

### Access Required
1. Centific customer list (3-5 anonymized profiles for Account Manager persona)
2. Centific branding assets (logo, brand colors, fonts for PDF templates)
3. Azure subscription (if using Azure Blob + Azure TTS — likely already available at Centific)
4. Named reviewer emails for validation workflow

### Monthly Budget (Estimate)
| Service | Cost/Month |
|---|---|
| ElevenLabs | ~$22 |
| Vapi.ai (interactive voice) | ~$0.10/min |
| Railway PostgreSQL | ~$20 |
| Railway Redis | ~$10 |
| S3 / Azure Blob | ~$5 |
| Tavily (web search) | ~$50 |
| **Total** | **~$107/mo** |

---

## 8. TECHNICAL DECISIONS MADE (AND WHY)

| Decision | Choice | Why |
|---|---|---|
| Primary database | PostgreSQL + pgvector | Handles relational + vector in one service. Replaces SQLite + ChromaDB. |
| Vector search | pgvector (PostgreSQL extension) | No separate service. Transactional consistency. Production-proven at scale. |
| Queue/cache | Redis | Pub/sub for review workflow. TTL for event cooldowns. Standard. |
| File storage | S3 / Azure Blob | Railway filesystem is ephemeral — PDFs and audio must be external. |
| LLM | Claude via Anthropic (direct, not OpenRouter) | Production: remove OpenRouter intermediary. One less dependency. |
| Voice TTS podcast | ElevenLabs | Best multi-voice quality for conversational format. |
| Voice TTS news | Azure Cognitive Services | Enterprise-grade, SSML support, Centific likely has Azure. |
| Interactive voice | Vapi.ai | Purpose-built voice agent platform. Fastest path. |
| Agent framework | LangGraph (already using) | No change — upgrade to full capability via checkpointer + store + response_format. |

---

## 9. HOW TO RESUME THIS CONTEXT IN A NEW CHAT

If this conversation is lost, load this file and provide the following to Claude Code:

1. This file (`Project_Context_2026-03-13.md`)
2. The enhancement plan (`Frontier_AI_Radar_Enhancement_Plan.md`)
3. The codebase at `c:/Users/RathlavathRameshnaya/Videos/InternalHackathon/Backend/`

Key files to read for instant context:
- `Backend/agents/base_agent.py` — the factory pattern all agents use
- `Backend/pipeline/graph.py` — the full LangGraph graph
- `Backend/pipeline/state.py` — RadarState, the shared state schema
- `Backend/memory/entity_store.py` — ChromaDB (to be replaced with pgvector)
- `Backend/memory/long_term.py` — JSON memory (to be replaced with PostgreSQL memory_kv)

Current phase: **Pre-production enhancement sprint — Day 0 setup phase.**
Next action: Provision PostgreSQL + Redis on Railway, create seed entities YAML, then start Day 1.

---

## 10. NORTH STAR

> *"The judges were struck by the maturity and conviction behind the work — especially the philosophy: 'Build it right, not just build it fast.'"*

That philosophy carries forward. We won the hackathon with it. We deliver production with it.

The system is not changing. The intelligence pipeline that scored 178/200 is the foundation. We are hardening it, expanding it, and making it genuinely useful for every person at Centific who needs to stay ahead of the AI curve.

---

*LLMafia — Ramesh N, Mahesh K, Devaraj A*
*Frontier AI Radar — Centific Internal Project*
*Document Date: 13 March 2026*
