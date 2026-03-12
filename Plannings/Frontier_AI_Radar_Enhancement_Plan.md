# Frontier AI Radar — Production Enhancement Plan
### Team LLMafia · Ramesh N, Mahesh K, Devaraj A
### Date: March 2026

---

## Context

Frontier AI Radar was built and deployed in 48 hours during the internal hackathon — scoring **178/200**, the highest across all 20 teams. The judges described it as *"near production-grade"* with a *"12-agent LangGraph pipeline, a SOTA Verification Agent, and a live deployed product."*

This document is the **production enhancement plan** based on the four areas identified by Abhishek. Each section covers:
- What was requested
- What exists today
- What needs to be built
- Technology and tools required

---

## Current System (Baseline)

| Component | Status | Details |
|---|---|---|
| Pipeline | Live | 11-agent LangGraph graph, 6 layers |
| Intelligence | Live | arXiv, HuggingFace, RSS, provider APIs, web crawling |
| Output | Live | PDF digest + email delivery via Brevo |
| Frontend | Live | Next.js on Vercel |
| Backend | Live | FastAPI on Railway |
| Database | Prototype | SQLite (needs migration) |
| Memory | Prototype | JSON files + ChromaDB (needs migration) |
| Schedule | Live | Daily run at 6:30 AM IST |

---

## Enhancement Area 1 — Freshness

### What Was Requested
> *"Weekly digest vs. triggered by a big event (GTC)"*

### What Exists Today
The system runs once daily on a fixed APScheduler job. There is no weekly rollup mode, no event detection, and no way to trigger a run when something significant happens in the AI world (e.g., NVIDIA GTC, GPT-5 launch, major regulatory announcement).

### What Needs to Be Built

#### 1A — Weekly Digest Mode
A new `run_mode = "weekly"` that queries the last 7 days of findings from the database, synthesizes trends across the week rather than just today's events, and produces a "Weekly Intelligence Brief" — a different format from the daily digest.

The Digest Agent receives a different prompt in weekly mode:
- Daily: *"What happened today, why does it matter?"*
- Weekly: *"What were the dominant themes this week? What direction is the market moving? What should each persona focus on next week?"*

#### 1B — Event-Triggered Runs
A keyword monitoring service that watches RSS feeds and news sources every 15 minutes. When a configured trigger keyword is detected — `GTC`, `GPT-5`, `Claude 4`, `AI Act`, `EU regulation`, `major model release` — it fires an immediate run with that event injected as the mission context.

Cooldown logic prevents re-triggering the same event within a configurable window (default: 24 hours).

```
Keyword Match → Cooldown Check → Inject Event Context → Fire Run → Persona Digests → Distribution
```

#### Technology Required
| Component | Technology |
|---|---|
| Weekly aggregation | PostgreSQL query (last 7 days by run_date) |
| Event keyword monitoring | APScheduler polling job (15-min interval) |
| Event cooldown | Redis key with TTL |
| Event config | `event_triggers` table in PostgreSQL |
| Trigger API | `POST /events/trigger` FastAPI endpoint |

---

## Enhancement Area 2 — Personas

### What Was Requested
> *"CAIR / AI COE (highly technical), Sales (competitor novelty or customer needs), Account managers (By a customer A's lens, where they fall short), Leadership (how the market is changing, what Centific must focus on). How narrative should change for different personas, maybe even combining multiple weeks' digests to see a trend."*

### What Exists Today
The pipeline produces a single digest for a generic audience. There is no persona awareness — one PDF, one email template, one narrative style for everyone. The current output tries to serve all audiences and therefore serves none optimally.

### What Needs to Be Built

#### 2A — Four Personas, One Pipeline

The same 11-agent pipeline runs once. All intelligence is gathered once. At the Digest Agent — the last reasoning step before PDF generation — the narrative forks by persona. Four digests, four PDFs, four email distributions from a single run.

| Persona | Narrative Style | What They Get |
|---|---|---|
| **CAIR / AI COE** | Deep technical | Benchmark tables, paper methodology, reproducibility caveats, full API spec changes, model architecture details |
| **Leadership** | Strategic executive | 3-bullet market direction, what Centific must prioritize, competitive positioning, no technical jargon |
| **Sales** | Competitive intelligence | Competitor feature launches, pricing shifts, customer talking points, new capabilities clients will ask about |
| **Account Managers** | Customer-specific lens | "For Customer X — here is where their current AI stack has gaps based on today's news. Conversation openers." |

Each persona gets:
- A different Jinja2 PDF template (layout, depth, sections)
- A different Digest Agent prompt (reasoning style, what to emphasize)
- A different email subject and body
- A different audio narration (covered in Enhancement 4)

#### 2B — Account Manager Persona (Customer Profiles)
The Account Manager persona requires customer context to work. A `customers` table stores each Centific customer's profile:
- Current AI stack (which models, which providers, which use cases)
- Known pain points
- Account owner
- Contract tier

Account managers add and maintain these profiles via the frontend UI. When an AM-persona run fires, the system loads the relevant customer profile and reasons: *"Given that Customer X is using Azure OpenAI GPT-4o for document processing, today's news about GPT-4o mini pricing dropping 60% is a direct cost-reduction opportunity worth ~$2,400/month for their current usage."*

#### 2C — Trend Digest (Multi-Week)
A `POST /digest/trend?weeks=4&persona=leadership` endpoint that:
1. Queries last N weeks of ranked findings from PostgreSQL
2. Sends all findings to the Digest Agent with a trend-analysis prompt
3. Returns: *"Over the last 4 weeks, the dominant themes are X, Y, Z. The consistent direction is toward A. Centific should respond by B."*

This is how the AVP sees the market moving, not just what happened today.

#### Technology Required
| Component | Technology |
|---|---|
| Persona config | `personas` table in PostgreSQL |
| Customer profiles | `customers` table + Next.js CRUD UI |
| Persona-aware Digest Agent | Prompt variants keyed by persona in `digest.py` |
| Per-persona PDF templates | 4 Jinja2 templates in `Backend/templates/` |
| Persona routing | `persona` field added to `RadarState` |
| Trend digest | PostgreSQL date-range query + new Digest Agent prompt variant |
| Subscription mapping | `subscriptions` table: each email recipient maps to one persona |

---

## Enhancement Area 3 — Validation

### What Was Requested
> *"Validation from different people in Centific."*

### What Exists Today
Zero human review. The pipeline compiles the digest and immediately sends it to all recipients. AI-generated content about competitors goes out without any internal validation.

For enterprise distribution — especially content that reaches Sales and Leadership — this is not acceptable.

### What Needs to Be Built

#### 3A — Section-Specific Review Workflow
After the Digest Agent compiles the draft, the pipeline pauses and routes to named section reviewers before the email goes out:

```
Digest compiled (draft)
        ↓
Section reviewers notified via email (each gets their section)
  · AI COE reviewer → validates Research section
  · Sales reviewer  → validates Competitor section
  · Leadership      → approves Executive Summary
        ↓
Each reviewer: Approve  OR  Request Changes (with comments)
        ↓
If all approved → email distributes
If changes requested → Digest Agent re-runs with reviewer comments
If timeout (2 hours, no response) → auto-distributes with "Unreviewed" watermark
```

#### 3B — Review UI in Frontend
A new page `/review/:run_id` in the Next.js frontend:
- Shows the full digest draft with section breakdown
- Per-section comment boxes
- Approve / Request Changes per section
- Shows who else has reviewed and their status
- Accessible via a secure deep-link sent in the reviewer notification email

#### Technology Required
| Component | Technology |
|---|---|
| Review queue | `review_queue` table in PostgreSQL |
| Pipeline pause | LangGraph `interrupt_before` on notification agent (see Section 5) |
| Reviewer notification | Brevo email with secure deep-link |
| Approval signal | Redis pub/sub — approval event resumes paused graph |
| Timeout/escalation | APScheduler job checks pending reviews every 30 min |
| Review frontend | Next.js `/review/:run_id` page |
| Review API | `GET /review/:run_id`, `POST /review/:run_id/approve`, `POST /review/:run_id/request-changes` |

---

## Enhancement Area 4 — Voice Agent

### What Was Requested
> *"Podcast style voice narrative, narrate like a news, highlights, then user says go into detail for X."*

### What Exists Today
Nothing. The system produces PDF and email only. No audio, no voice interface.

### What Needs to Be Built

#### 4A — Pre-Generated Audio (Phase 1)
After every run, alongside the PDF, generate audio files in two styles:

**Podcast Style**
- Conversational, two-host format (Host A presents, Host B reacts and asks follow-up questions)
- Opinionated: *"The interesting thing about Mistral's pricing move is that it directly undercuts Cohere's enterprise tier..."*
- Duration: ~10 minutes for full digest, ~2 minutes for highlights

**News Style**
- Single anchor, authoritative, structured
- *"Good morning. In today's Frontier AI Radar: OpenAI has announced..."*
- Duration: ~5 minutes for full digest, ~90 seconds for highlights

Both styles are generated per persona — the CAIR audio goes deeper on technical content, the Leadership audio leads with strategic implications.

#### 4B — Interactive Voice Agent (Phase 2)
The user listens to the highlights audio. They say: *"Go into detail for the OpenAI pricing change."*

The system:
1. Transcribes the voice input (STT)
2. Runs semantic search over today's findings using the entity memory
3. Returns the full finding — what changed, why it matters, evidence, verification verdict
4. Narrates the deep-dive back to the user (TTS)

This is a real-time conversational loop, not pre-generated audio.

```
User speaks → STT → Semantic search over today's findings
                                    ↓
                        Retrieve full finding detail
                                    ↓
                        Generate narration → TTS → User hears response
```

#### Technology Required
| Component | Technology | Notes |
|---|---|---|
| Voice script generation | New prompt phase in `digest.py` | Alongside digest_json, generate voice_script |
| TTS — Podcast style | **ElevenLabs API** | Multi-voice, most natural for conversational format |
| TTS — News style | **Azure Cognitive Services TTS** | Professional anchor voice, SSML support |
| Audio storage | S3 / Azure Blob Storage | PDFs also move here from Railway filesystem |
| Audio delivery | Signed URL (24h expiry) in email + frontend player | |
| STT (interactive) | Vapi.ai built-in | Handles transcription internally |
| Interactive agent | **Vapi.ai** | Purpose-built voice agent platform |
| Semantic search for voice | pgvector (see Section 5) | "Go deeper on X" → cosine similarity search over findings |
| FastAPI webhook | `POST /voice/query` | Vapi calls this for tool use |

---

## Enhancement Area 5 — Foundation Upgrades (Enables All Four Areas)

*These are not visible features — but every enhancement above depends on them.*

### 5A — LangGraph `create_react_agent` — Full Capability Utilization

The system already uses `langgraph.prebuilt.create_react_agent` — the correct, modern LangGraph implementation. However, it is currently used at approximately 30% of its capability.

**Current usage:**
```python
create_react_agent(
    model=model,
    tools=tools,
    prompt=system_prompt
)
```

**Production usage — three critical additions:**

```python
create_react_agent(
    model=model,
    tools=tools,
    prompt=system_prompt,

    # 1. CHECKPOINTER — Persistent agent memory across runs
    # Saves every agent's full conversation history to PostgreSQL.
    # Enables: trend digests, persona continuity, multi-week memory.
    # Required for: interrupt/resume (review workflow).
    checkpointer=PostgresSaver(pg_conn),

    # 2. STORE — Cross-agent shared memory
    # All 11 agents read/write a shared PostgreSQL-backed store.
    # Namespaced: entities, customers, memory key-value.
    # Replaces: ChromaDB + long_term.py JSON files entirely.
    store=PostgresStore(pg_conn),

    # 3. RESPONSE FORMAT — Structured output, no JSON parsing
    # Forces agent output into a validated Pydantic schema.
    # Eliminates: 150+ lines of manual JSON repair code in base_agent.py.
    # Production reliability: agent output is always valid, never broken.
    response_format=AgentOutputSchema,
)
```

**What each addition unlocks:**

| Parameter | Enhancement Unlocked |
|---|---|
| `checkpointer` | Review workflow pause/resume · Trend digest memory · Persona continuity across weeks |
| `store` | Entity memory · Customer profiles accessible by all agents · Replaces ChromaDB |
| `response_format` | Reliable structured output · Eliminates JSON parsing failures in production |
| `.astream()` | Voice agent streaming — user hears response as it generates, not after a 10-second wait |
| `interrupt_before=["tools"]` | Human review gate — pipeline pauses before sending email, resumes on approval |

**The review workflow (Enhancement 3) is natively solved by `interrupt_before`.** No custom state machine. No polling. LangGraph pauses the graph at the notification step, waits for the approval signal, and resumes exactly where it stopped. This is a built-in LangGraph feature — we are now using it.

### 5B — Single PostgreSQL Database (Replaces Three Systems)

**What we have today — three separate systems:**
- SQLite → structured data (runs, findings, reports)
- ChromaDB → vector/semantic search (entity memory)
- JSON files → key-value memory (seen papers, content hashes, run history)

**What production needs — one PostgreSQL database:**

PostgreSQL with the `pgvector` extension handles all three in a single database instance. One connection string, one backup, one migration system, transactional consistency across all data.

```
PostgreSQL + pgvector
│
├── Relational tables
│   ├── runs, extractions, findings, reports     ← replaces SQLite
│   ├── personas, customers, subscriptions       ← new (Personas feature)
│   ├── review_queue, review_comments            ← new (Validation feature)
│   ├── event_triggers, event_log               ← new (Freshness feature)
│   └── memory_kv                               ← replaces long_term.py JSON
│
└── Vector columns (pgvector)
    ├── entities.embedding                       ← replaces ChromaDB
    └── findings.embedding                       ← semantic search for voice agent
```

**Why pgvector over keeping ChromaDB:**
- One database to manage, not two separate services
- Transactional consistency — a finding and its embedding are written atomically
- Standard SQL queries join structured data with vector search in one query
- Production-grade: pgvector is used in production at Notion, Supabase, and others at scale

### 5C — Entity Memory — The Intelligence Multiplier

Every agent in the current system calls `search_entity_memory()` — but the entity store is empty. No entities have ever been added. When agents look up context for "Mistral" or "MMLU" — they get nothing.

**Populating entity memory is the single highest-leverage improvement** — it makes every agent's output richer immediately, before any other feature is built.

Three entity types:

**Organizations** (AI companies, research labs):
Each with: products, pricing history, competitive positioning, key personnel, past releases.
Examples: OpenAI, Anthropic, Google DeepMind, Meta AI, Mistral, Cohere, Stability AI, xAI

**Models** (foundation models):
Each with: context window, pricing per 1M tokens, benchmark scores, known strengths/weaknesses, release date, deprecation status.
Examples: GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro, Llama 3.1, Mistral Large, Deepseek R1

**Benchmarks** (evaluation standards):
Each with: what it measures, known gaming risks, current SOTA, human baseline, who runs it.
Examples: MMLU, HumanEval, MATH, GPQA, MT-Bench, Chatbot Arena ELO, SWE-bench

**Centific Customers** (for Account Manager persona — manually entered by AMs):
Each with: current AI stack, known pain points, account owner, contract tier.

**How entity memory grows:**
1. **Seed** (one-time): 50 curated entities loaded before first production run
2. **Live enrichment** (every run): new `entity_enrichment` node after `intel_join` — extracts mentioned organizations/models from findings and upserts their profiles
3. **Weekly refresh** (scheduled): re-crawl entity source pages to update pricing, new products, benchmark scores

**Impact on output quality:**

Without entity memory → *"Mistral has released a new model with competitive pricing."*

With entity memory → *"Mistral has released Mistral Large 2 at $3/1M tokens — their third pricing reduction in 6 months, continuing a pattern of aggressive enterprise positioning against Cohere. This undercuts Cohere Command R+ by 40% on input tokens and is directly relevant to Centific clients currently evaluating enterprise LLM providers."*

---

## 6-Day Delivery Plan

| Day | Delivers | Key Output |
|---|---|---|
| **Day 0** | Provision all services | Railway PostgreSQL + Redis · S3/Azure Blob · ElevenLabs + Vapi accounts · Seed YAML (50 entities) |
| **Day 1** | Foundation | PostgreSQL migration · pgvector schema · Entity seed loaded · `create_react_agent` upgrades (checkpointer + store + response_format) |
| **Day 2** | Data quality | All 6 stub tools implemented (Tavily web search, GitHub trending, content diff, leaderboard diff, HackerNews, Semantic Scholar) · Entity enrichment node live |
| **Day 3** | Personas | All 4 persona digests · 4 PDF templates · Per-persona email distribution · Customer profiles UI |
| **Day 4** | Validation + Freshness | Review workflow (interrupt_before + approval UI) · Weekly digest mode · Event-triggered runs + keyword monitoring |
| **Day 5** | Voice Phase 1 | Voice script generation · ElevenLabs podcast audio · Azure TTS news audio · Audio player in email + UI |
| **Day 6** | Voice Phase 2 + Launch | Vapi interactive voice agent · "Go into detail for X" working · Full end-to-end test · Production deployment |

---

## What We Need From Your Side

Before Day 1 of coding, the following decisions and access are needed:

### Decisions
1. **Persona priority** — if timeline gets tight, which 2 personas ship first?
2. **Named reviewers** — who validates each section? (Name + email per section: Research, Competitor, Executive Summary)
3. **Event trigger keywords** — confirm the list: GTC, GPT-5, Claude 4, Gemini 3, AI Act, [others?]
4. **Voice style preference** — review ElevenLabs voice samples before we pick, or ship and iterate?

### Access
1. Centific customer list for Account Manager persona — 3-5 anonymized profiles to start
2. Centific branding assets — logo, brand colors, fonts for PDF templates
3. Azure subscription access (if using Azure Blob + Azure TTS instead of S3 + ElevenLabs)
4. Named reviewers confirmed for the validation workflow

### Budget (Monthly Estimates)
| Service | Cost |
|---|---|
| ElevenLabs (podcast TTS) | ~$22/mo |
| Vapi.ai (interactive voice) | ~$0.10/min of voice usage |
| Railway PostgreSQL addon | ~$20/mo |
| Railway Redis addon | ~$10/mo |
| S3 / Azure Blob (PDFs + audio) | ~$5/mo |
| Tavily API (web search) | ~$50/mo |
| **Total** | **~$107/mo** |

---

## Summary

| Enhancement | Core Technology | Depends On |
|---|---|---|
| Freshness (weekly + event) | APScheduler · Redis TTL · PostgreSQL date queries | Day 1 foundation |
| Personas (4 audiences) | Prompt variants · Jinja2 templates · pgvector customer profiles | Day 1 foundation |
| Validation (review workflow) | LangGraph `interrupt_before` · Redis pub/sub · Next.js review UI | `checkpointer` (Day 1) |
| Voice (podcast + interactive) | ElevenLabs · Azure TTS · Vapi.ai · pgvector semantic search | Entity memory (Day 1) |
| LangGraph full utilization | `checkpointer` · `store` · `response_format` · `interrupt_before` | PostgreSQL (Day 1) |
| Single database | PostgreSQL + pgvector | Day 0 provisioning |
| Entity memory | Seed YAML · Live enrichment node · pgvector | Day 0 seed YAML |

**Everything builds on Day 1. Day 1 is PostgreSQL + `create_react_agent` upgrades.**

**End-of-week target: full production launch across all four enhancement areas.**

---

*Frontier AI Radar — LLMafia Team*
*Ramesh Nayak · Mahesh Kola · Devaraj Agulla*
