# Frontier AI Radar — Sprint Plan & MOM
### Date: 13 March 2026 | Call with Abhishek Mukherji + Harshit Rajgarhia
### Author: Ramesh Nayak (LLMafia)

---

## GROUND RULES FROM THE CALL

- **Existing system works as-is.** No breaking changes to the current 11-agent pipeline.
- **All new features are new agent nodes** appended to the existing graph — fitting into the `create_react_agent` pattern.
- **LangGraph full capability upgrade** is the backbone for all new features (`checkpointer`, `store`, `interrupt_before`, `.astream()`).
- **SQLite → PostgreSQL migration** is mandatory and happens first — it unlocks everything else.
- **Freshness feature** is handled by a separate team member — LLMafia only needs to integrate once delivered.
- **ElevenLabs confirmed** for TTS. Ramesh to research alternatives and pick the best.
- **Timeline: 3–4 days** for Feature 1 (Personas) + Feature 2 (Audio Book).

---

## FEATURE 1 — PERSONA SYSTEM WITH USER BLUEPRINTS
### Priority: 1 (Highest) | Timeline: Days 1–2

---

### What Abhishek Asked For (Exact Intent)

1. When a user logs in → the system asks for their role/persona selection.
2. The Digest Agent must be persona-aware → each persona gets deeper, more focused content in their specific domain — same PDF format.
3. **Priority 1 feature:** Pre-defined suggested questions per persona — like Perplexity's suggested prompts. User selects a question → system responds using the persona's system prompt. Cold start is solved by these suggestions.
4. Users can select an existing blueprint OR create their own custom persona with their own requirements.
5. When creating a custom persona → must ask **Public or Private**:
   - **Public:** All Centific users can see and use this template.
   - **Private:** Visible only to that `user_id`.
6. Database must persist all user data, personas, templates, preferences.

---

### Design: User & Persona Schema

```
┌─────────────────────────────────────────────────────────┐
│                      users                              │
│  id (UUID PK)                                           │
│  email         VARCHAR UNIQUE NOT NULL                  │
│  name          VARCHAR                                  │
│  centific_team VARCHAR  (CAIR | Sales | AM | Leadership │
│                          | Custom)                      │
│  active_persona_id  UUID FK → persona_templates         │
│  created_at    TIMESTAMP                                │
│  updated_at    TIMESTAMP                                │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                  persona_templates                      │
│  id (UUID PK)                                           │
│  name               VARCHAR NOT NULL                    │
│  description        TEXT                                │
│  persona_type       VARCHAR  (CAIR | Sales | AM |       │
│                               Leadership | Custom)      │
│  digest_system_prompt  TEXT   ← what Digest Agent uses  │
│  suggested_questions   JSONB  ← array of Q strings      │
│  digest_focus_areas    JSONB  ← what to emphasize       │
│  owner_id           UUID FK → users (NULL = system)     │
│  visibility         VARCHAR  (public | private)         │
│  is_system_default  BOOLEAN DEFAULT false               │
│  created_at         TIMESTAMP                           │
│  updated_at         TIMESTAMP                           │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              user_persona_preferences                   │
│  user_id        UUID FK → users                         │
│  persona_id     UUID FK → persona_templates             │
│  pinned         BOOLEAN DEFAULT false                   │
│  last_used_at   TIMESTAMP                               │
└─────────────────────────────────────────────────────────┘
```

---

### Login Flow

```
User lands on login page
        ↓
Authenticates (email / SSO)
        ↓
First login?
  YES → Persona Selection Screen
        "Choose your role to personalize your digest"
        [ CAIR / AI COE ]  [ Leadership ]  [ Sales ]  [ Account Manager ]
        [ Browse Public Templates ]  [ Create My Own ]
        ↓
  NO  → Load active_persona from DB → go to dashboard
        (Option to change persona always available in profile settings)
```

---

### Suggested Questions — Perplexity Style

Each system persona template ships with 5–6 pre-built suggested questions displayed as clickable chips on the dashboard and in the chat interface.

**CAIR / AI COE:**
- "What benchmark movements happened this week?"
- "Which new models support tool use or function calling?"
- "What safety and alignment papers dropped today?"
- "Which open-source models closed the gap with proprietary ones?"
- "What API or inference efficiency changes should I know about?"

**Leadership:**
- "How is the AI market shifting this week?"
- "What should Centific prioritize based on today's intelligence?"
- "Which competitor moves require a strategic response?"
- "What regulatory changes are on the horizon?"
- "What's the one thing I need to read today?"

**Sales:**
- "What competitor features launched this week?"
- "What pricing shifts affect our active proposals?"
- "Which new capabilities will customers ask us about?"
- "How do I position against [competitor] today?"
- "What customer pain points does today's news surface?"

**Account Managers:**
- "What gaps exist in my customer's current AI stack?"
- "What new capabilities could benefit [customer] this week?"
- "How does today's news affect [customer]'s roadmap?"
- "What should I bring up in my next customer call?"

**Custom personas:** owner defines their own suggested questions during creation.

When user clicks a suggested question → it fires the question with the persona's system prompt pre-loaded → agent responds in persona context.

---

### Blueprint Creation Flow

```
"Create Your Own Persona" button
        ↓
Step 1: Name + Description
        "What do you call this persona?" / "What is its focus?"
        ↓
Step 2: Focus Areas (multi-select)
        [ Research ] [ Competitors ] [ Models ] [ Benchmarks ]
        [ Pricing ] [ Safety ] [ Tooling ] [ Customer-Specific ]
        ↓
Step 3: Custom Instructions (optional)
        "Anything specific this persona should emphasize or ignore?"
        ↓
Step 4: Suggested Questions (add up to 6)
        "What questions should this persona answer best?"
        ↓
Step 5: Visibility
        [ Private — only I can see this ]
        [ Public — all Centific users can use this ]
        ↓
Save → persona_templates table with owner_id = current user
```

Public personas appear in a **"Community Templates"** section on the persona selection screen, alongside system defaults.

---

### Digest Agent Integration

`digest.py` receives `persona_id` in `RadarState`. It loads the persona's `digest_system_prompt` from PostgreSQL (via `store`) and uses it as the reasoning instruction for that run.

**Same ranked findings → different narrative → same PDF format → persona-specific depth.**

---

## FEATURE 2 — AUDIO BOOK
### Priority: 1 | Timeline: Days 2–4

---

### What Abhishek Asked For (Exact Intent)

1. List of digest PDFs displayed like an audiobook library — by date, with template/design visual.
2. On selecting a digest:
   - First: narrate the **menu** — "Today I have X findings. Here are the topics: 1. ..., 2. ..., 3. ... Which would you like to explore?"
   - One narrative voice only (no news/podcast split for now).
3. User selects a topic → agent narrates it fully.
4. User says "tell me more" → **Deep Research Agent** activates:
   - Takes the conversation context + the source URL of that finding
   - Does deeper research (dynamically decides how much content is enough)
   - Streams the response to voice **simultaneously** as it researches (real-time streaming)
5. User can say **"go back to menu"** → restore session, re-narrate the table of contents.
6. After the session ends → persist the full conversation to the database.
7. **Session cache** (Redis) for active conversation context. PostgreSQL for post-session persistence.

---

### Architecture: Audio Book System

```
┌──────────────────────────────────────────────────────────────┐
│  AUDIO BOOK UI (Next.js)                                     │
│                                                              │
│  [Digest Library — book-cover cards by date + persona]      │
│  Select a digest                                             │
│          ↓                                                   │
│  Audio Player + Transcript Panel                             │
│  [▶ Play]  [⏸ Pause]  [Menu]  [Suggested Topics]           │
└──────────────────────────────────────────────────────────────┘
           ↕ WebSocket (real-time audio + transcript)
┌──────────────────────────────────────────────────────────────┐
│  FastAPI Audio Session Manager                               │
│                                                              │
│  Session State Machine:                                      │
│  MENU → EXPLORING → DEEP_RESEARCH → MENU → ... → ENDED      │
│                                                              │
│  Active session: Redis (conversation history, current state) │
│  Ended session: PostgreSQL (full transcript + audio URLs)    │
└──────────────────────────────────────────────────────────────┘
           ↕ LangGraph .astream()
┌──────────────────────────────────────────────────────────────┐
│  Audio Narration Agent (new node)                            │
│  Deep Research Agent  (new node)                             │
│  Both use create_react_agent with .astream()                 │
└──────────────────────────────────────────────────────────────┘
           ↕ ElevenLabs Streaming TTS API
┌──────────────────────────────────────────────────────────────┐
│  Audio chunks → WebSocket → Browser → Web Audio API         │
│  User hears response as it generates                         │
└──────────────────────────────────────────────────────────────┘
```

---

### Session Flow (Detailed)

```
1. USER SELECTS A DIGEST
   System loads ranked_findings for that run_id from PostgreSQL
   Generates table-of-contents script (pure Python, no LLM)
   ElevenLabs TTS: "Today's digest has 12 findings across 4 topics.
                    Topic 1: OpenAI released GPT-5 mini...
                    Topic 2: Three new papers on agentic frameworks...
                    Topic 3: Mistral pricing dropped 40%...
                    Which topic would you like to explore?"
   Session state → MENU
   Cache in Redis: {session_id, run_id, findings, current_state: MENU}

2. USER SAYS "Topic 2" or "Tell me about the agentic papers"
   STT → text → intent detection
   Audio Narration Agent reads the research_intel findings for that topic
   Narrates: full detail, evidence, why it matters, confidence score
   Session state → EXPLORING

3. USER SAYS "Tell me more about the second paper"
   Deep Research Agent activates
   Inputs: conversation history + finding.source_url + user query
   Agent calls: crawl_page(source_url), search_arxiv(paper_title),
                fetch_hf_model_card (if model mentioned)
   LangGraph .astream() → token chunks → ElevenLabs streaming TTS
   User hears response building in real-time
   Session state → DEEP_RESEARCH
   After response: "Would you like to explore further or go back to the menu?"

4. USER SAYS "Go back to the menu"
   Redis: restore session context
   Re-narrate table of contents (mark already-explored topics)
   Session state → MENU

5. USER SAYS "That's all, thanks"
   Session ends
   Redis: delete active session key
   PostgreSQL: write full session record
     - conversation_history (all turns)
     - audio_urls (S3 links per turn)
     - duration
     - findings_explored[]
```

---

### New Agent Nodes

#### Audio Narration Agent
- **Role:** Narrate a specific finding or the menu in a clear, engaging single-voice style
- **Input:** finding object(s) + persona context + narration type (menu | detail)
- **Tools:** `read_memory` (entity context for richer narration), `search_entity_memory`
- **Output:** narration script (streamed to ElevenLabs)
- **LangGraph:** `create_react_agent` with `.astream()` + `checkpointer`
- **Max iterations:** 2 (narration is focused, not open-ended research)

#### Deep Research Agent
- **Role:** Go deeper on any finding when user asks "tell me more"
- **Input:** conversation context + source URL + user query
- **Tools:** `crawl_page`, `search_web`, `search_arxiv`, `fetch_hf_model_card`, `search_entity_memory`
- **Output:** streamed research narrative (token by token to TTS)
- **LangGraph:** `create_react_agent` with `.astream()` + `checkpointer`
- **Depth decision:** LLM reasons — "Is this a paper? Crawl + arxiv. Is this a model? fetch_model_card + pricing. Is this a competitor move? crawl + search_web." Max 3 tool calls.
- **Max iterations:** 4

---

### Streaming Architecture (Feature 3 is embedded here)

```
Deep Research Agent
        ↓ .astream() — LangGraph yields token chunks
FastAPI StreamingResponse / WebSocket
        ↓ text chunks buffered into sentences
ElevenLabs Streaming TTS API
  POST /v1/text-to-speech/{voice_id}/stream
  Input: sentence chunks as they arrive
  Output: audio byte chunks
        ↓ audio chunks
WebSocket → Frontend
        ↓
Web Audio API (browser plays audio in real-time)
```

**Buffering strategy:** Don't send individual tokens to ElevenLabs. Buffer until sentence boundary (`.`, `!`, `?`) then send the complete sentence. This gives smooth audio without gaps. Typical latency: **~800ms from first token to first audio.**

---

### Database Schema: Audio Sessions

```sql
-- Active sessions (Redis handles live state, this is for persistence)
CREATE TABLE audio_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES users(id),
    run_id           UUID REFERENCES runs(id),      -- which digest
    persona_id       UUID REFERENCES persona_templates(id),
    session_state    VARCHAR DEFAULT 'menu',        -- menu|exploring|deep_research|ended
    conversation     JSONB DEFAULT '[]',            -- full turn history
    findings_explored UUID[] DEFAULT '{}',          -- which finding IDs were explored
    started_at       TIMESTAMP DEFAULT NOW(),
    ended_at         TIMESTAMP,
    duration_seconds INTEGER
);

CREATE TABLE audio_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID REFERENCES audio_sessions(id),
    turn_index   INTEGER,
    role         VARCHAR,      -- user | assistant
    text_content TEXT,
    audio_url    VARCHAR,      -- S3/Azure Blob URL for this turn's audio
    agent_type   VARCHAR,      -- narration | deep_research | menu
    created_at   TIMESTAMP DEFAULT NOW()
);
```

**Redis keys during active session:**
```
audio:session:{session_id}:state     → current state (menu|exploring|deep_research)
audio:session:{session_id}:history   → conversation turns (JSON, TTL 4 hours)
audio:session:{session_id}:context   → current finding being explored
```

---

## FEATURE 3 — REAL-TIME STREAMING TO VOICE
### Embedded in Feature 2 | No separate implementation needed

Streaming is not a separate feature — it is the delivery mechanism for Feature 2's Deep Research Agent. Every time the Deep Research Agent responds, it uses LangGraph's `.astream()` + ElevenLabs Streaming TTS. The user hears the response building in real-time, exactly like how ChatGPT streams text on screen.

**Key technical point:** This requires upgrading the `create_react_agent` calls to use `checkpointer` (required for streaming with tool use). This is already in the Day 1 plan.

---

## DATABASE MIGRATION PLAN
### SQLite → PostgreSQL | Day 1 (First Task)

### Full Schema (New + Existing)

```sql
-- CORE PIPELINE TABLES (migrated from SQLite)
CREATE TABLE runs (
    id            UUID PRIMARY KEY,
    run_mode      VARCHAR,
    status        VARCHAR,
    started_at    TIMESTAMP,
    completed_at  TIMESTAMP,
    config        JSONB
);

CREATE TABLE findings (
    id              UUID PRIMARY KEY,
    run_id          UUID REFERENCES runs(id),
    title           VARCHAR,
    source_url      VARCHAR,
    publisher       VARCHAR,
    what_changed    TEXT,
    why_it_matters  TEXT,
    evidence        TEXT,
    agent_source    VARCHAR,
    confidence      VARCHAR,
    impact_score    FLOAT,
    relevance       FLOAT,
    novelty         FLOAT,
    credibility     FLOAT,
    actionability   FLOAT,
    rank            INTEGER,
    topic_cluster   VARCHAR,
    needs_verification BOOLEAN DEFAULT false,
    tags            TEXT[],
    metadata        JSONB,
    embedding       vector(384),      -- for voice semantic search
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ENTITY MEMORY (replaces ChromaDB)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE entities (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    entity_type VARCHAR,              -- organization|model|benchmark|customer
    description TEXT,
    metadata    JSONB DEFAULT '{}',
    embedding   vector(384),
    source      VARCHAR DEFAULT 'seed',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX entities_embedding_idx ON entities
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- KEY-VALUE MEMORY (replaces long_term.py JSON)
CREATE TABLE memory_kv (
    key        VARCHAR PRIMARY KEY,
    value      JSONB,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- USER + PERSONA SYSTEM (new)
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR UNIQUE NOT NULL,
    name                VARCHAR,
    centific_team       VARCHAR,
    active_persona_id   UUID,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE persona_templates (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  VARCHAR NOT NULL,
    description           TEXT,
    persona_type          VARCHAR,
    digest_system_prompt  TEXT,
    suggested_questions   JSONB DEFAULT '[]',
    digest_focus_areas    JSONB DEFAULT '[]',
    owner_id              UUID REFERENCES users(id),
    visibility            VARCHAR DEFAULT 'private',
    is_system_default     BOOLEAN DEFAULT false,
    created_at            TIMESTAMP DEFAULT NOW(),
    updated_at            TIMESTAMP DEFAULT NOW()
);

CREATE TABLE user_persona_preferences (
    user_id     UUID REFERENCES users(id),
    persona_id  UUID REFERENCES persona_templates(id),
    pinned      BOOLEAN DEFAULT false,
    last_used_at TIMESTAMP,
    PRIMARY KEY (user_id, persona_id)
);

-- AUDIO BOOK (new)
CREATE TABLE audio_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES users(id),
    run_id           UUID REFERENCES runs(id),
    persona_id       UUID REFERENCES persona_templates(id),
    session_state    VARCHAR DEFAULT 'menu',
    conversation     JSONB DEFAULT '[]',
    findings_explored UUID[] DEFAULT '{}',
    started_at       TIMESTAMP DEFAULT NOW(),
    ended_at         TIMESTAMP,
    duration_seconds INTEGER
);

CREATE TABLE audio_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID REFERENCES audio_sessions(id),
    turn_index   INTEGER,
    role         VARCHAR,
    text_content TEXT,
    audio_url    VARCHAR,
    agent_type   VARCHAR,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- REVIEW WORKFLOW (from previous plan)
CREATE TABLE review_queue (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID REFERENCES runs(id),
    section     VARCHAR,
    reviewer_email VARCHAR,
    status      VARCHAR DEFAULT 'pending',
    comments    TEXT,
    reviewed_at TIMESTAMP,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- EVENT TRIGGERS (freshness — integration point for other team member)
CREATE TABLE event_triggers (
    id              SERIAL PRIMARY KEY,
    keyword         VARCHAR NOT NULL,
    cooldown_hours  INTEGER DEFAULT 24,
    last_triggered  TIMESTAMP,
    is_active       BOOLEAN DEFAULT true
);
```

---

## 4-DAY EXECUTION PLAN

### Day 1 — Foundation (PostgreSQL + LangGraph Upgrade)

**Morning:**
- Provision Railway PostgreSQL addon + enable pgvector extension
- Provision Railway Redis addon
- Run full Alembic migration: all tables above
- Migrate existing SQLite data to PostgreSQL
- Migrate long_term.py JSON → `memory_kv` table
- Swap `entity_store.py` backend: ChromaDB → pgvector queries (same interface)

**Afternoon:**
- Upgrade `base_agent.py` `build_react_agent()`: add `checkpointer=PostgresSaver`, `store=PostgresStore`, `response_format` per agent
- Delete `parse_json_output()` + all JSON repair code (replaced by structured output)
- Wire `PostgresSaver` checkpointer from FastAPI startup into all agents
- Test: run one full pipeline — verify it runs on PostgreSQL, checkpointer saves state, entity store queries work
- Write 30 seed entities into `entities.yaml` and load them

**End of Day 1:** System runs on PostgreSQL. Checkpointer live. Entity memory has seed data. Structured output on all agents.

---

### Day 2 — Persona System

**Morning:**
- FastAPI auth endpoints: `POST /auth/login`, `GET /auth/me`
- Seed 4 system default `persona_templates` with prompts + suggested questions
- `POST /personas` — create custom persona
- `GET /personas?visibility=public` — list public + own personas
- `PUT /personas/:id` — edit persona
- `RadarState`: add `persona_id`, `persona_prompt`, `suggested_questions` fields
- `digest.py`: load persona's `digest_system_prompt` from store, inject into Digest Agent reasoning

**Afternoon:**
- Next.js: Persona selection screen (shown at first login)
- Next.js: Dashboard — suggested questions as clickable chips (Perplexity style)
- Next.js: Question click → fires to chat endpoint → agent responds in persona context
- Next.js: Blueprint creation UI (5-step flow: name → focus → instructions → questions → visibility)
- Next.js: Community templates page (public personas browseable by all)
- Per-persona PDF template routing (4 Jinja2 templates wired to persona_type)

**End of Day 2:** Full persona system working. Login → select persona → get persona digest. Suggested questions clickable. Blueprint creation with public/private.

---

### Day 3 — Audio Book Foundation + Session Management

**Morning:**
- Next.js: Audio Book library page — digest PDFs as book-cover cards (date, persona, finding count)
- Next.js: Audio player page — transcript panel + play controls + topic chips
- ElevenLabs integration: `POST /audio/tts` endpoint — text → audio → S3 URL
- Table of contents generation (pure Python — no LLM, builds from `ranked_findings`)
- Menu narration: "Today's digest has N findings across X topics. Topic 1... Which would you like?"
- Redis session management: create, read, update session state
- PostgreSQL session persistence: write full session on end

**Afternoon:**
- Audio Narration Agent: new `create_react_agent` node for narrating a finding in detail
- WebSocket endpoint: `WS /audio/session/:session_id` — real-time audio delivery
- "Go back to menu" intent detection → restore Redis session → re-narrate menu
- Session expiry: Redis TTL 4 hours, auto-persist on expiry
- Wire `audio_messages` table: save each turn's text + S3 audio URL

**End of Day 3:** Audio book library live. Select a digest → hear menu → select topic → hear full narration. Go back to menu works. Session persists.

---

### Day 4 — Deep Research Agent + Streaming + Polish

**Morning:**
- Deep Research Agent: new `create_react_agent` node
  - Tools: `crawl_page`, `search_web`, `search_arxiv`, `fetch_hf_model_card`, `search_entity_memory`
  - Depth heuristic: paper topic → arxiv + crawl; model topic → model card + pricing; competitor → web search + crawl
  - Max 4 tool calls, dynamically decides based on content volume
- LangGraph `.astream()` wired to Deep Research Agent
- Sentence-boundary buffer: accumulate tokens → send complete sentences to ElevenLabs
- ElevenLabs Streaming TTS: `POST /v1/text-to-speech/{voice_id}/stream` → audio byte chunks
- WebSocket: stream audio chunks to frontend as they arrive
- Frontend: Web Audio API plays chunks in real-time

**Afternoon:**
- End-to-end test: Login → persona → digest → audio book → menu → explore → deep research (streaming) → back to menu → end session → verify PostgreSQL record
- Edge cases: empty findings, ElevenLabs rate limit fallback, WebSocket reconnect
- All 4 persona digest runs tested
- Blueprint creation → public → another user sees it → uses it → test
- Deploy: Railway backend + Vercel frontend

**End of Day 4:** Full production launch. All features live.

---

## RISK FACTORS

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| **ElevenLabs streaming latency** | Medium | High (bad voice UX) | Buffer to sentence boundary before sending. First chunk ~800ms — acceptable. Pre-generate menu narration so it plays instantly. |
| **PostgreSQL migration data loss** | Low | Critical | Backup SQLite before migration. Run migration on Railway staging first. Verify row counts before cutover. |
| **LangGraph `.astream()` with tool calls** | Medium | High | Test `.astream()` in isolation Day 1 before depending on it. LangGraph 0.2+ supports this cleanly — verify version. |
| **WebSocket complexity in production** | Medium | Medium | Use Server-Sent Events (SSE) as fallback if WebSocket proves unstable on Railway. SSE is simpler and one-directional which fits this use case. |
| **Deep Research Agent depth calibration** | Medium | Medium | Start with max 3 tool calls + 1000 word output cap. Let it run in testing and calibrate. Better to under-research first run than to hang. |
| **"Go back to menu" context restoration** | Medium | Medium | Redis stores full session state including which findings were explored. Menu re-narration marks explored topics. Tested thoroughly Day 3. |
| **ElevenLabs rate limits** | Low | Medium | Add request queue in FastAPI. One concurrent TTS generation per session. Batch pre-generation for menu narration at digest creation time. |
| **Custom persona prompt quality** | High | Medium | Guided creation flow (5 steps with examples). Default system instructions injected even for custom personas. Test with real personas before launch. |
| **Public persona abuse** | Low | Low | Admin flag on persona_templates. Centific internal tool — low abuse risk. Report/hide feature in next iteration. |
| **`response_format` breaking existing agents** | Medium | High | Upgrade one agent first (ranking — simplest output). Verify. Then roll out to all 11. Don't batch the upgrade. |

---

## TTS RESEARCH — ElevenLabs vs Alternatives

Abhishek suggested ElevenLabs. Research summary:

| Service | Quality | Streaming | Cost | Recommendation |
|---|---|---|---|---|
| **ElevenLabs** | Best-in-class | Yes (websocket + HTTP) | $22/mo (30 min), $99/mo (100 min) | **Use this** |
| Azure Cognitive Services TTS | Good, enterprise | Yes (SSML) | ~$4/1M chars | Good fallback |
| OpenAI TTS | Good | Yes | $15/1M chars | Simple but no real-time streaming |
| Google Cloud TTS | Good | No real streaming | $4/1M chars | Skip |
| Cartesia AI | Very good, low latency | Yes | $50/mo | Good alternative |

**Decision: ElevenLabs as primary. Azure TTS as fallback** (Centific likely has Azure credits).

---

## INTEGRATION POINT — FRESHNESS (Other Team Member)

When the freshness feature (weekly digest + event-triggered runs) is delivered:

**What LLMafia needs to integrate:**
1. A new `run_mode` value ("weekly" or "event") in `RadarState` — we add the field, they populate it
2. A FastAPI trigger endpoint `POST /runs/trigger` — already planned in our backend
3. The `event_triggers` table in PostgreSQL — schema is already included above
4. No changes to the pipeline itself — run_mode is read by Mission Controller and Strategy Planner to adjust focus

**Integration effort: 2–4 hours once their code is ready.**

---

## WHAT IS NEEDED BEFORE DAY 1

| Item | Owner | Status |
|---|---|---|
| Railway PostgreSQL addon provisioned | Ramesh | TODO |
| Railway Redis addon provisioned | Ramesh | TODO |
| ElevenLabs account + API key | Ramesh | TODO |
| Azure TTS key (fallback) | Centific / Harshit | TODO |
| S3 or Azure Blob bucket for audio | Centific / Harshit | TODO |
| 4 system persona prompts written (CAIR, Sales, AM, Leadership) | Ramesh | TODO |
| Suggested questions (5 per persona) | Ramesh | TODO — 20 questions total |
| Seed entities YAML (30–50 entities) | Ramesh | TODO |
| Centific branding assets for PDF templates | Centific | TODO |

---

## NORTH STAR FOR THIS SPRINT

> The audio book feature + persona system is what takes this from an internal tool to a product people actually want to open every morning. The persona system solves the "who is this for" problem. The audio book solves the "I don't have time to read" problem.

> Every decision in this sprint is in service of one thing: **make it feel like a product, not a pipeline.**

---

*LLMafia — Ramesh N, Mahesh K, Devaraj A*
*Sprint document — 13 March 2026*
