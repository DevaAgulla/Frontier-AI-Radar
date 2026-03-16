# Frontier AI Radar — Full Project Context & Status
### Last Updated: 14 March 2026
### Author: Ramesh Nayak (Team LLMafia)
### Read this file to get 100% context. This is the single source of truth.

---

## 1. WHO IS INVOLVED

| Person | Role | Responsibility |
|---|---|---|
| **Ramesh Nayak** | Team Lead, LLMafia | **Backend only** — all agents, pipeline, API, DB, memory, voice |
| **Mahesh Kola** | Team Member, LLMafia | Co-builder |
| **Devaraj Agulla (Deva)** | Team Member, LLMafia | **Frontend/UI only** — Next.js, UX, all UI enhancements |
| **Abhishek Mukherji** | AVP / VP, Centific | Sponsor, daily cadence call owner, feature requirements owner |
| **Harshit Rajgarhia** | Technical Lead, Centific | Technical counterpart, architecture reviewer |
| **Narsi Rangachari** | Senior Leader, Centific | Announced hackathon results |
| **Vasudevan Sundarababu** | Senior Leader, Centific | Congratulated team, part of leadership thread |

**Daily Cadence:** 8:00 AM PT / 8:30 PM IST.

**CRITICAL TEAM BOUNDARY:** Ramesh handles ALL backend implementation. Deva handles ALL UI/UX. Never mix these responsibilities when planning tasks.

---

## 2. HOW WE GOT HERE — THE FULL STORY

### The Hackathon
- **Company:** Centific (AI services company — "expert data as a service")
- **Problem Statement:** Build "Frontier AI Radar" — autonomous system tracking the AI ecosystem daily
- **Required to track:** Competitor product releases, foundation model provider updates, arXiv research papers, HuggingFace benchmark movements
- **Required output:** PDF digest emailed daily with ranked findings
- **Duration:** 48 hours | **Teams:** 20 teams

### What LLMafia Built (in 48 hours)
A fully autonomous multi-agent intelligence system:
- **11-agent LangGraph pipeline** across 5 layers (now 10 nodes in graph, verification is conditional)
- **Layer 1:** Mission Controller
- **Layer 2:** Strategy Planner
- **Layer 3:** 4 parallel intelligence agents (Competitor, Model, Research, Benchmark)
- **Layer 4:** Verification Agent (conditional — fires only for SOTA claims) + Ranking Agent
- **Layer 5:** Digest Agent → Report Generator → Notification Agent
- **SOTA Verification:** Verification Agent independently checks HuggingFace leaderboards when a model claims SOTA
- **Memory:** Short-term (LangGraph state) + Long-term (PostgreSQL memory_kv) + Entity memory (PostgreSQL entities table)
- **Output:** PDF digest + email via Brevo
- **Frontend:** Next.js deployed on Vercel
- **Backend:** FastAPI deployed on Railway
- **LLM:** Claude via OpenRouter (also supports Gemini as fallback)
- **Framework:** LangGraph (`langgraph.prebuilt.create_react_agent`)

### Hackathon Result
- **Score: 178/200 — Highest across all 20 teams. LLMafia WON.**
- Judges specifically called out: multi-agent pipeline, SOTA Verification Agent, live deployed product, "near production-grade"
- Official quote: *"The panel was particularly struck by the maturity and conviction behind their work — especially the philosophy: 'Build it right, not just build it fast.'"*

### What Happened After the Win
Abhishek Mukherji (AVP) immediately set up a daily cadence to take this to full production. Daily calls running. Harshit joined as technical counterpart. Sprint to production launch is live.

---

## 3. THE ARCHITECTURE — CURRENT STATE

### Repository
```
c:/Users/RathlavathRameshnaya/Videos/InternalHackathon/
├── Backend/                       ← Ramesh's domain (FastAPI, LangGraph, agents)
│   ├── agents/
│   │   ├── base_agent.py          ← LLM factory: build_react_agent() wraps create_react_agent
│   │   ├── mission_controller.py  ← Layer 1
│   │   ├── strategy_planner.py    ← Layer 2
│   │   ├── competitor_intel.py    ← Layer 3a — reads competitors table from DB
│   │   ├── model_intel.py         ← Layer 3b — flags SOTA claims
│   │   ├── research_intel.py      ← Layer 3c — arXiv, papers
│   │   ├── benchmark_intel.py     ← Layer 3d — HuggingFace leaderboards
│   │   ├── verification.py        ← Layer 4a (conditional)
│   │   ├── ranking.py             ← Layer 4b (deterministic scoring)
│   │   ├── digest.py              ← Layer 5a (persona-aware — future)
│   │   ├── report_generator.py    ← Layer 5b (Jinja2 → PDF via xhtml2pdf)
│   │   └── notification.py        ← Layer 5c (email via Brevo)
│   ├── pipeline/
│   │   ├── graph.py               ← Full LangGraph graph (create_radar_graph)
│   │   ├── state.py               ← RadarState TypedDict (shared state)
│   │   └── runner.py              ← run_radar() / execute_prepared_radar()
│   ├── api/
│   │   └── main.py                ← FastAPI app, all routes
│   ├── memory/
│   │   ├── short_term.py          ← LangGraph state helpers (read_from_state, etc.)
│   │   ├── long_term.py           ← memory_kv table interface
│   │   └── entity_store.py        ← PostgreSQL entities table + pgvector search
│   ├── core/
│   │   └── tools.py               ← All @tool functions incl. read_memory/write_memory
│   ├── db/
│   │   ├── models.py              ← SQLAlchemy ORM (PostgreSQL-native, JSONB, ARRAY)
│   │   └── persist.py             ← All DB read/write functions
│   ├── config/
│   │   └── settings.py            ← Pydantic BaseSettings, .env driven
│   ├── templates/
│   │   └── digest.html            ← Jinja2 PDF template
│   ├── voice/                     ← NEW (built March 14)
│   │   ├── config.env             ← ELEVENLABS_API_KEY + voice presets (edit this)
│   │   └── generate_voice_digest.py ← Standalone PDF-to-MP3 converter (WORKING)
│   ├── scripts/
│   │   ├── setup_db.py            ← Full DB provisioning script
│   │   ├── seed_centific_competitors.py ← Competitor seed runner (pending DB access)
│   │   └── seed_centific_competitors.sql ← Raw SQL version of same
│   └── data/
│       ├── reports/               ← Generated PDFs live here
│       └── audio/                 ← Generated MP3s live here (NEW)
├── frontend/                      ← Deva's domain (Next.js, Vercel)
└── Plannings/                     ← All planning docs live here
```

### LangGraph Graph Flow
```
START
  └─> mission_controller (Layer 1)
        └─> strategy_planner (Layer 2)
              └─> [conditional fan-out based on run_mode]
                    ├─> research_intel ─────┐
                    ├─> competitor_intel ───┤
                    ├─> model_intel ────────┤
                    └─> benchmark_intel ────┘
                              └─> intel_join (fan-in, persists to DB)
                                    └─> [conditional: SOTA found?]
                                          ├─> verification ──┐
                                          └─────────────────>┘
                                                └─> ranking
                                                      └─> digest
                                                            └─> report_generator
                                                                  └─> notification
                                                                        └─> END
```

### Key Architecture Principle (From Harshit — NON-NEGOTIABLE)
**Loosely coupled. Never tightly coupled.** Each agent node returns only a partial state dict. Agents don't know about each other. The graph wires them. LangGraph 100% capability utilization is the goal.

---

## 4. WHAT HAS BEEN BUILT (COMPLETED AS OF MARCH 14)

### Day 1 Completions

#### ✅ PostgreSQL Migration (db/models.py + db/persist.py)
- Full rewrite from SQLite-era ORM to PostgreSQL-native models
- Added `from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID as PG_UUID`
- `User` model: added `centific_team`, `active_persona_id`
- `Run` model: added `run_mode`, `completed_at`, `persona_id`, `config (JSONB)`
- `Finding` model: all individual columns (title, source_url, publisher, what_changed, why_it_matters, evidence, confidence, impact_score, relevance, novelty, credibility, actionability, rank, topic_cluster, needs_verification, tags ARRAY, metadata_ JSONB)
- `persist_intel_findings`: writes to individual Finding columns
- `finish_run`: fixed deprecated `session.query().get()` → `session.get()` (SQLAlchemy 2.0)

#### ✅ LangGraph Checkpointer Wired
- `pipeline/graph.py`: `create_radar_graph(checkpointer=None)` — accepts and passes checkpointer to `graph.compile()`
- `pipeline/runner.py`: `_build_checkpointer()` — creates `AsyncPostgresSaver` from `langgraph.checkpoint.postgres.aio`, gracefully falls back to None
- Each run gets its own `thread_id` = `run_id` — checkpoints are namespaced per run
- `requirements.txt`: added `psycopg[binary]>=3.1.5` (psycopg v3 required by LangGraph checkpointer)
- `requirements.txt`: added `langgraph-checkpoint-postgres>=2.0.0`

#### ✅ Memory System Fully Fixed (core/tools.py)
**Before fix (data loss bugs):**
- `write_memory(type="entity")` — silently discarded all entity data, returned fake success
- `read_memory(type="entity")` — always returned None
- `read_memory(type="short_term")` + `write_memory(type="short_term")` — both were no-ops

**After fix:**
- `type="entity"` write → calls `get_entity_store().add_entity(entity_data)` with proper defaults
- `type="entity"` read → calls `get_entity_store().search_entities(key, top_k=5)`
- `type="short_term"` → reads/writes `memory_kv` table with `st_` key prefix

#### ✅ OpenRouter Structured Output Fix (agents/base_agent.py)
**Problem:** `ValueError: response does not have 'parsed' or 'refusal' field` when using OpenRouter + Claude
**Root cause:** OpenRouter's Claude implementation doesn't support OpenAI's `parsed`/`refusal` structured output API
**Fix:** Skip `response_format` when `llm_backend == "openrouter"`. Agents already have text fallback via `extract_agent_output` + `parse_json_object`.
```python
_backend = (settings.llm_backend or "gemini").lower().strip()
if response_format is not None and _backend != "openrouter":
    kwargs["response_format"] = response_format
```

#### ✅ Competitor Seed Files Created (scripts/)
- `seed_centific_competitors.py` — Python runner using SQLAlchemy (safe upsert, mirrors setup_db.py pattern)
- `seed_centific_competitors.sql` — Raw SQL version for psql CLI
- 14 Centific-specific competitors across 3 groups:
  - **Core (direct RFP competitors):** Scale AI, Appen, iMerit, Sama, RWS TrainAI, Cognizant AI Lab, SuperAnnotate
  - **Platform-centric labeling:** Labelbox, V7 Labs, Encord, Kili Technology, CloudFactory
  - **Expert crowd/research-grade:** Surge AI, Prolific
- **Status: BLOCKED** — Azure PostgreSQL firewall blocks local IP. Run from cloud VM or add local IP to Azure firewall rules (`aidf-dev-pgsql.postgres.database.azure.com`)

#### ✅ Voice Digest — FULLY WORKING (voice/)
- `voice/config.env` — put ElevenLabs API key here (`ELEVENLABS_API_KEY=...`)
- `voice/generate_voice_digest.py` — standalone script, zero changes to pipeline
- **Uses ElevenLabs REST API directly via httpx** (no SDK — ElevenLabs SDK has Windows Long Path install bug)
- Flow: PDF → pdfplumber extracts text → clean (remove URLs, page numbers, dividers) → chunk into ≤4500 chars → POST to ElevenLabs API per chunk → concatenate → save .mp3
- Two voice presets: `rachel` (calm professional female) + `adam` (deep authoritative male)
- **TESTED AND WORKING:** digest-20260309-170217.pdf → 12 pages → 17,039 chars → 6 chunks → 20.9 MB MP3

**To run voice digest:**
```bash
# 1. Edit voice/config.env — set ELEVENLABS_API_KEY=your_key
# 2. Run from Backend/ directory:
python voice/generate_voice_digest.py
python voice/generate_voice_digest.py --both        # generates rachel + adam
python voice/generate_voice_digest.py --voice adam  # adam only
python voice/generate_voice_digest.py --pdf data/reports/your-file.pdf
```
Output: `data/audio/<pdf_stem>_<voice>.mp3`

---

## 5. KEY ARCHITECTURAL DECISIONS & CLARIFICATIONS

### Personas DO NOT Control Which Agents Run
This was explicitly confirmed. Personas ONLY affect the `digest.py` agent's system prompt — what narrative angle the digest takes. Which agents run (full/custom) is always controlled independently by the `mode` parameter in the run request. They are completely decoupled.

### ElevenLabs SDK Has Windows Long Path Bug
Do NOT try to install `elevenlabs` SDK on this machine. The package has file paths that exceed Windows 260-char limit. Use REST API via `httpx` directly. Already solved in `voice/generate_voice_digest.py`.

### LLM Backend: OpenRouter vs Gemini
- `LLM_BACKEND=openrouter` → uses Claude via OpenRouter
- `LLM_BACKEND=gemini` → uses Gemini directly
- OpenRouter does NOT support `response_format` structured output — always falls back to text + JSON parsing

### Database: Azure PostgreSQL Flexible Server
- Host: `aidf-dev-pgsql.postgres.database.azure.com`
- Schema: `ai_radar`
- Uses psycopg2-binary (SQLAlchemy ORM sync) AND psycopg[binary] v3 (LangGraph checkpointer async)

---

## 6. WHAT IS NEXT — THE REMAINING QUEUE

### Immediate (Next Session — Priority Order)

#### Priority 1: Wire Voice into FastAPI API Endpoint
Create `POST /api/v1/audio/generate` endpoint:
- Input: `{"run_id": "...", "voice": "rachel"}`
- Logic: reads the PDF for that run_id from DB, calls the voice generation logic from `voice/generate_voice_digest.py`, saves MP3 to `data/audio/`
- Output: `{"audio_url": "...", "voice": "rachel", "size_kb": 20928}`
- This makes voice accessible to Deva's frontend
- IMPORTANT: reuse the existing logic from `voice/generate_voice_digest.py` — do not duplicate

#### Priority 2: Interactive Chat Agent
New LangGraph ReAct agent (`agents/chat_agent.py`):
- Input: user question + `run_id` (to load digest context)
- If answerable from digest → answer directly from `ranked_findings` + `digest_json`
- If needs more research → triggers Tavily web search
- Both text and voice response via same endpoint
- Endpoint: `POST /api/v1/chat/ask`
- This is what Abhishek called "suggested questions" — user asks a question about the current digest and gets an intelligent answer

#### Priority 3: Competitor DB Seed
- Unblock by either: (a) adding local IP to Azure PostgreSQL firewall, or (b) running `python scripts/seed_centific_competitors.py` from the deployed server
- Scripts are ready and tested (minus the DB connection)

#### Priority 4: Persona System (After audio + chat)
- CRUD endpoints for `persona_templates` table
- Wire `persona_id` from run request into `RadarState.persona_prompt`
- `digest.py` reads persona's `digest_system_prompt` from DB, injects into agent reasoning
- 4 system default personas: CAIR/AI COE, Leadership, Sales, Account Manager
- Each persona has 5-6 suggested questions (pre-defined chips on dashboard)

### Medium Term (After Monday)
- Audio Book full system (session management, streaming, deep research agent)
- Review/validation workflow (`interrupt_before` on notification agent)
- Weekly + event-triggered run modes (Freshness feature)
- Entity enrichment node (enriches entity store after each run)

---

## 7. THE 4 ENHANCEMENT REQUIREMENTS (From Abhishek — March 13 Meeting)

### Enhancement 1: Freshness
**Requested:** Weekly digest mode + event-triggered runs (GTC, GPT-5, Claude 4, AI Act etc.)
**Status:** Not started
**Plan:** New `run_mode="weekly"` + `run_mode="event"` in RadarState + event_triggers table + Redis TTL cooldown

### Enhancement 2: Personas
**Requested:** CAIR/AI COE (technical depth), Sales (competitive intel), Account Managers (customer lens), Leadership (market direction)
**Status:** DB schema ready (persona_templates table exists in models.py). Pipeline not yet wired.
**Key clarification:** Persona = digest narrative only. NOT which agents run.

### Enhancement 3: Validation (Human Review)
**Requested:** Section-specific validation from Centific people before distribution
**Status:** Not started
**Plan:** LangGraph `interrupt_before` on notification agent. Review queue table. Redis pub/sub to resume. Next.js review page.

### Enhancement 4: Voice Agent (Audio Book)
**Requested:** Podcast-style narration. "Tell me more about X" triggers deep research. Real-time streaming.
**Status:** Foundation DONE (voice/generate_voice_digest.py working). API endpoint + streaming + interactive agent: NOT started.
**Architecture:**
- Audio Book UI: digest library → select → hear menu → select topic → narration
- Deep Research Agent: new node, `.astream()` → ElevenLabs Streaming TTS → WebSocket → browser
- Session state: Redis (active) + PostgreSQL `audio_sessions` table (persisted)

---

## 8. WHAT WAS DISCUSSED IN THE MARCH 13 MEETING (Abhishek + Harshit)

### Key Points from the Meeting
1. **Existing system works as-is** — no breaking changes to the 11-agent pipeline
2. **LangGraph 100% capability** is the backbone — checkpointer, store, interrupt_before, .astream()
3. **Loosely coupled architecture** is non-negotiable (Harshit's key requirement)
4. **"Cook the user with a massive experience"** — Harshit wants the platform to feel premium
5. **Reverse engineering approach** — understand the problem deeply before building
6. **Audio Book first** — takes priority over Persona implementation
7. **Interactive Chat first** — high value, not that complex
8. **ElevenLabs confirmed** for TTS — Ramesh researched alternatives and confirmed it's best-in-class
9. **Daily cadence continues** — Abhishek wants visible progress every day

### Revised Priority Order (Post-Meeting)
1. Audio Book foundation + Voice API endpoint ← CURRENT
2. Interactive Chat agent ← NEXT
3. Persona system
4. Review/validation workflow
5. Freshness (event-triggered + weekly modes)

---

## 9. CENTIFIC'S COMPETITORS (For competitor_intel Agent Context)

Centific is in "expert data as a service" — specialist humans + tooling for AI training data.

**Direct RFP competitors:**
- Scale AI (`scale.com/blog`)
- Appen (`appen.com/blog`)
- iMerit (`imerit.net/resources/blog/`)
- Sama (`sama.com/blog`)
- RWS TrainAI (`rws.com/artificial-intelligence/train-ai-data-services/blog/`)
- Cognizant AI Lab (`cognizant.com/us/en/ai-lab/blog`)
- SuperAnnotate (`superannotate.com/blog`)

**Platform-centric labeling vendors:**
- Labelbox, V7 Labs, Encord, Kili Technology, CloudFactory

**Expert crowd / research-grade:**
- Surge AI (`surgehq.ai/blog`)
- Prolific (`prolific.com/resources`)

**Note:** The existing 10 default competitors in the DB are LLM providers (OpenAI, Anthropic, etc.) — those track AI model news. The 14 above track Centific's business competitors. Both are needed.

---

## 10. HOW TO RESUME THIS CONTEXT IN A NEW CHAT

### Give Claude these files:
1. This file (`Project_Context_2026-03-14.md`) — full context
2. `Backend/agents/base_agent.py` — factory pattern all agents use
3. `Backend/pipeline/graph.py` — full LangGraph graph
4. `Backend/pipeline/state.py` — RadarState TypedDict
5. `Backend/api/main.py` — FastAPI routes (to see existing endpoint patterns)
6. `Backend/voice/generate_voice_digest.py` — voice logic to reuse

### Key phrases that restore context instantly:
- "We won the Centific hackathon with 178/200. Now in production sprint."
- "Ramesh = backend only. Deva = UI only."
- "10-node LangGraph pipeline. Loosely coupled. 100% create_react_agent."
- "ElevenLabs SDK has Windows Long Path bug — always use REST API via httpx."
- "Personas = digest narrative only, NOT which agents run."
- "Voice digest already working (voice/generate_voice_digest.py). Next: wire into API."

### Current blockers:
- Azure PostgreSQL firewall blocks local IP → competitor seed script can't run locally
- ElevenLabs SDK can't install on Windows (Long Path) → solved with REST API already

---

## 11. TECHNICAL DEBT AND KNOWN STUBS

| Component | Status | Notes |
|---|---|---|
| `search_semantic_scholar` | Mock data | Returns placeholder |
| `search_web` (Tavily) | Mock data | Tavily API key needed |
| `search_github_trending` | Mock data | GitHub API needed |
| `search_hackernews` | Mock data | HN Algolia API |
| `search_reddit` | Mock data | Reddit API |
| `diff_content` | Mock comparison | No real content diff |
| `diff_leaderboard_snapshots` | Mock diff | No real comparison |
| Entity memory | Wired correctly | But EMPTY — no entities seeded yet |
| LangSmith tracing | In code | LANGCHAIN_TRACING_V2=False in .env |
| robots.txt | Not implemented | Fetcher makes direct requests |
| Competitor DB | 14 records ready | Script written, blocked on Azure firewall |

---

## 12. NORTH STAR

> *"The judges were struck by the maturity and conviction — especially the philosophy: 'Build it right, not just build it fast.'"*

> *Harshit: "You have to cook the user with a massive experience on the platform."*

We won the hackathon with a system that was right. We are taking that system to production with the same standard. Every new feature is a proper agent node, loosely coupled, wired into LangGraph correctly. No shortcuts that create future pain.

---

## 13. DAILY LOG

| Date | What Was Done |
|---|---|
| **Hackathon (pre-March 13)** | Built 11-agent LangGraph pipeline. Won 178/200. |
| **March 13** | Meeting with Abhishek + Harshit. 4 enhancements scoped. Planning docs written. |
| **March 13-14** | Day 1 backend: PostgreSQL migration (models.py, persist.py), LangGraph checkpointer wired (graph.py, runner.py), Memory system fully fixed (core/tools.py — entity + short_term both now working), OpenRouter structured output bug fixed (base_agent.py), psycopg v3 installed, competitor seed scripts created. Full pipeline test: research agent ran, email received. ✅ |
| **March 14 (today)** | Voice digest built and TESTED: `voice/generate_voice_digest.py` working. ElevenLabs REST API via httpx (no SDK). 20.9 MB MP3 generated from digest PDF. Two voice presets ready. |
| **Next session** | Wire voice into FastAPI: `POST /api/v1/audio/generate`. Then: Interactive Chat agent. |

---

*LLMafia — Ramesh N, Mahesh K, Devaraj A*
*Frontier AI Radar — Centific Internal Project*
*Document Date: 14 March 2026*
