"""
Frontier AI Radar — One-Time Production Database Setup
=======================================================

Run this ONCE after you have a PostgreSQL connection string.

Usage:
    cd Backend
    python scripts/setup_db.py

The script reads DATABASE_URL from your .env file.
Set it before running:
    DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/railway

What this script does (all idempotent — safe to re-run):
  1. Tests the connection
  2. Enables pgvector extension
  3. Creates all tables (existing + new)
  4. Seeds 4 system persona templates
  5. Seeds default competitor sources
  6. Prints a full summary
"""

import os
import sys
from pathlib import Path

# ── Make sure we can import from Backend/ root ───────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session, relationship
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float,
    ForeignKey, LargeBinary, CheckConstraint, UniqueConstraint, ARRAY
)
from datetime import datetime, timezone
import json
import uuid


# ─────────────────────────────────────────────────────────────────────────────
# RESOLVE DATABASE URL
# ─────────────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("\n❌  DATABASE_URL is not set in your .env file.")
    print("    Add this line to Backend/.env:")
    print("    DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/railway\n")
    sys.exit(1)

if DATABASE_URL.startswith("sqlite"):
    print("\n❌  DATABASE_URL is still pointing to SQLite.")
    print("    Update it in Backend/.env to your PostgreSQL connection string.\n")
    sys.exit(1)

# Railway sometimes gives postgres:// — SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print(f"\n🔌  Connecting to: {DATABASE_URL[:60]}...")


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

# Azure PostgreSQL: detect and enforce SSL
IS_AZURE = "postgres.database.azure.com" in DATABASE_URL
if IS_AZURE and "sslmode" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = DATABASE_URL + sep + "sslmode=require"
if IS_AZURE:
    print("   Azure PostgreSQL detected - SSL enforced.")

TARGET_SCHEMA = "ai_radar"

connect_args = {"sslmode": "require", "options": f"-c search_path={TARGET_SCHEMA},public"} if IS_AZURE else {"options": f"-c search_path={TARGET_SCHEMA},public"}
engine = sa.create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)

# Test connection
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("✅  Connection successful.")
except Exception as e:
    print(f"\n❌  Could not connect: {e}\n")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 0 — CREATE SCHEMA + DROP OLD PUBLIC TABLES
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n🏗️   Creating schema '{TARGET_SCHEMA}'...")
with engine.begin() as conn:
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}"))
    conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}, public"))
print(f"✅  Schema '{TARGET_SCHEMA}' ready.")

# Drop tables that were accidentally created in public schema
PUBLIC_TABLES = [
    "audio_messages", "audio_sessions", "user_persona_preferences",
    "persona_templates", "event_triggers", "review_queue",
    "memory_kv", "entities", "resources", "findings", "runs",
    "extractions", "competitors", "users",
]
print("\n🗑️   Dropping old public schema tables...")
with engine.begin() as conn:
    conn.execute(text("SET search_path TO public"))
    for tbl in PUBLIC_TABLES:
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS public.{tbl} CASCADE"))
            print(f"   Dropped public.{tbl}")
        except Exception:
            pass
print("✅  Public schema cleaned.")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — ENABLE PGVECTOR
# ─────────────────────────────────────────────────────────────────────────────

print("\n📦  Enabling pgvector extension...")
try:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    print("✅  pgvector enabled.")
except Exception as e:
    print(f"⚠️   pgvector extension failed (may not be supported on this tier): {e}")
    print("    Continuing without vector columns...")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — CREATE ALL TABLES VIA RAW SQL (idempotent — IF NOT EXISTS)
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """

-- ============================================================
-- EXISTING TABLES (migrated from SQLite — kept identical)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(200) NOT NULL,
    email         VARCHAR(320) NOT NULL UNIQUE,
    password_hash VARCHAR(256),
    centific_team VARCHAR(100),
    active_persona_id UUID,
    subscribed_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS extractions (
    id               SERIAL PRIMARY KEY,
    publication_date TIMESTAMP,
    mode             VARCHAR(10) CHECK (mode IN ('job', 'UI')),
    metadata         TEXT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS runs (
    id            SERIAL PRIMARY KEY,
    extraction_id INTEGER REFERENCES extractions(id) ON DELETE SET NULL,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status        VARCHAR(20),
    run_mode      VARCHAR(20) DEFAULT 'daily',
    time_taken    INTEGER,
    started_at    TIMESTAMP DEFAULT NOW(),
    completed_at  TIMESTAMP,
    pdf_path      TEXT,
    pdf_content   BYTEA,
    persona_id    UUID,
    config        JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS findings (
    id              SERIAL PRIMARY KEY,
    extraction_id   INTEGER REFERENCES extractions(id) ON DELETE CASCADE,
    run_id          INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    agent_name      VARCHAR(30) NOT NULL,
    title           VARCHAR(500),
    source_url      TEXT,
    publisher       VARCHAR(200),
    what_changed    TEXT,
    why_it_matters  TEXT,
    evidence        TEXT,
    confidence      VARCHAR(10) DEFAULT 'MEDIUM',
    impact_score    FLOAT DEFAULT 0.0,
    relevance       FLOAT DEFAULT 0.0,
    novelty         FLOAT DEFAULT 0.0,
    credibility     FLOAT DEFAULT 0.0,
    actionability   FLOAT DEFAULT 0.0,
    rank            INTEGER,
    topic_cluster   VARCHAR(50),
    needs_verification BOOLEAN DEFAULT FALSE,
    tags            TEXT[],
    html_content    TEXT,
    pdf_content     BYTEA,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS resources (
    id            SERIAL PRIMARY KEY,
    run_id        INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    agent_name    VARCHAR(20) NOT NULL,
    name          VARCHAR(500) NOT NULL,
    url           TEXT,
    resource_type VARCHAR(50),
    discovered_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS competitors (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    source_type VARCHAR(20) NOT NULL,
    selector    VARCHAR(200),
    is_default  BOOLEAN DEFAULT TRUE,
    is_active   BOOLEAN DEFAULT TRUE,
    added_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- KEY-VALUE MEMORY (replaces long_term.py JSON files)
-- ============================================================

CREATE TABLE IF NOT EXISTS memory_kv (
    key        VARCHAR(500) PRIMARY KEY,
    value      JSONB,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- ENTITY STORE (replaces ChromaDB)
-- ============================================================

CREATE TABLE IF NOT EXISTS entities (
    id          VARCHAR(200) PRIMARY KEY,
    name        VARCHAR(300) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    description TEXT,
    metadata    JSONB DEFAULT '{}',
    source      VARCHAR(50) DEFAULT 'seed',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- PERSONA SYSTEM
-- ============================================================

CREATE TABLE IF NOT EXISTS persona_templates (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(200) NOT NULL,
    description          TEXT,
    persona_type         VARCHAR(50),
    digest_system_prompt TEXT,
    suggested_questions  JSONB DEFAULT '[]',
    digest_focus_areas   JSONB DEFAULT '[]',
    owner_id             INTEGER REFERENCES users(id) ON DELETE SET NULL,
    visibility           VARCHAR(10) DEFAULT 'private' CHECK (visibility IN ('public', 'private')),
    is_system_default    BOOLEAN DEFAULT FALSE,
    created_at           TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_persona_preferences (
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    persona_id UUID REFERENCES persona_templates(id) ON DELETE CASCADE,
    pinned     BOOLEAN DEFAULT FALSE,
    last_used_at TIMESTAMP,
    PRIMARY KEY (user_id, persona_id)
);

-- ============================================================
-- AUDIO BOOK SESSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS audio_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    run_id           INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    persona_id       UUID REFERENCES persona_templates(id) ON DELETE SET NULL,
    session_state    VARCHAR(20) DEFAULT 'menu',
    conversation     JSONB DEFAULT '[]',
    findings_explored INTEGER[] DEFAULT '{}',
    started_at       TIMESTAMP DEFAULT NOW(),
    ended_at         TIMESTAMP,
    duration_seconds INTEGER
);

CREATE TABLE IF NOT EXISTS audio_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID REFERENCES audio_sessions(id) ON DELETE CASCADE,
    turn_index   INTEGER,
    role         VARCHAR(10) CHECK (role IN ('user', 'assistant')),
    text_content TEXT,
    audio_url    VARCHAR(500),
    agent_type   VARCHAR(30),
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- REVIEW WORKFLOW
-- ============================================================

CREATE TABLE IF NOT EXISTS review_queue (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    section        VARCHAR(50),
    reviewer_email VARCHAR(320),
    status         VARCHAR(20) DEFAULT 'pending',
    comments       TEXT,
    reviewed_at    TIMESTAMP,
    created_at     TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- EVENT TRIGGERS (freshness — integration point)
-- ============================================================

CREATE TABLE IF NOT EXISTS event_triggers (
    id             SERIAL PRIMARY KEY,
    keyword        VARCHAR(200) NOT NULL,
    cooldown_hours INTEGER DEFAULT 24,
    last_triggered TIMESTAMP,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_findings_run_id ON findings(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_agent ON findings(agent_name);
CREATE INDEX IF NOT EXISTS idx_findings_impact ON findings(impact_score DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_audio_sessions_user ON audio_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_audio_messages_session ON audio_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_persona_visibility ON persona_templates(visibility);
CREATE INDEX IF NOT EXISTS idx_persona_system ON persona_templates(is_system_default);

"""

print("\n🏗️   Creating tables...")
try:
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
        # Execute each statement individually (split on semicolons)
        for statement in SCHEMA_SQL.split(";"):
            # Strip leading blank lines and comment-only lines to get to real SQL
            lines = statement.split("\n")
            code_lines = []
            found_code = False
            for line in lines:
                stripped = line.strip()
                if not found_code and (stripped.startswith("--") or stripped == ""):
                    continue  # skip leading comments/blanks
                found_code = True
                code_lines.append(line)
            stmt = "\n".join(code_lines).strip()
            if stmt:
                conn.execute(text(stmt))
    print("✅  All tables created.")
except Exception as e:
    print(f"\n❌  Table creation failed: {e}\n")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — ADD VECTOR COLUMN TO ENTITIES (if pgvector available)
# ─────────────────────────────────────────────────────────────────────────────

print("\n🔢  Adding vector column to entities table...")
try:
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'entities' AND column_name = 'embedding'
        """))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE entities ADD COLUMN embedding vector(384)"))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_entities_embedding
                ON entities USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
            """))
            print("✅  Vector column + index added to entities.")
        else:
            print("✅  Vector column already exists — skipping.")
except Exception as e:
    print(f"⚠️   Vector column skipped (pgvector not available): {e}")

# Same for findings (for voice semantic search)
print("\n🔢  Adding vector column to findings table...")
try:
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'findings' AND column_name = 'embedding'
        """))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE findings ADD COLUMN embedding vector(384)"))
            print("✅  Vector column added to findings.")
        else:
            print("✅  Findings vector column already exists — skipping.")
except Exception as e:
    print(f"⚠️   Findings vector column skipped: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — SEED SYSTEM PERSONA TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

print("\n🌱  Seeding system persona templates...")

SYSTEM_PERSONAS = [
    {
        "name": "CAIR / AI COE",
        "description": "Deep technical digest for AI researchers and engineers at Centific.",
        "persona_type": "CAIR",
        "digest_system_prompt": (
            "You are generating an AI intelligence digest for the CAIR and AI Center of Excellence team "
            "at Centific. Your audience consists of senior AI researchers, ML engineers, and technical architects. "
            "Prioritize: benchmark methodology and reproducibility, model architecture details, API spec changes, "
            "inference efficiency, safety/alignment research, and open-source tooling updates. "
            "Include technical depth: context windows, pricing per token, benchmark scores with caveats, "
            "paper methodology summaries. Do NOT simplify. Use precise technical language. "
            "For each finding, explain the technical implication for Centific's AI stack."
        ),
        "suggested_questions": [
            "What benchmark movements happened today and are they reproducible?",
            "Which new models support tool use or function calling?",
            "What safety and alignment papers dropped today?",
            "Which open-source models closed the gap with proprietary ones?",
            "What API or inference efficiency changes should I know about?",
            "Which new papers are most relevant to our data annotation pipelines?"
        ],
        "digest_focus_areas": ["benchmarks", "research_papers", "model_architecture", "api_changes", "safety", "tooling"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Leadership",
        "description": "Strategic executive digest — market direction, what Centific must focus on.",
        "persona_type": "Leadership",
        "digest_system_prompt": (
            "You are generating an AI intelligence digest for Centific's senior leadership team. "
            "Your audience consists of VPs, Directors, and C-suite executives. "
            "Write in clear, jargon-free language. Lead with strategic implications. "
            "Format: 3 strategic bullets at the top, then brief sections by domain. "
            "For each finding, answer: 'What does this mean for Centific's business?' "
            "Focus on: competitive positioning, market direction changes, regulatory developments, "
            "major capability shifts that affect clients. AVOID: benchmark numbers, technical architecture, "
            "paper citations. Every paragraph should answer: 'So what?' for a business leader."
        ),
        "suggested_questions": [
            "How is the AI market shifting this week?",
            "What should Centific prioritize based on today's intelligence?",
            "Which competitor moves require a strategic response?",
            "What regulatory changes are on the horizon?",
            "What is the one thing I need to read today?",
            "How are our key clients' AI needs changing?"
        ],
        "digest_focus_areas": ["market_direction", "competitor_strategy", "regulatory", "pricing_shifts"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Sales",
        "description": "Competitive intelligence digest for the Centific sales team.",
        "persona_type": "Sales",
        "digest_system_prompt": (
            "You are generating an AI intelligence digest for the Centific sales team. "
            "Your audience is account executives and sales engineers. "
            "Focus entirely on: competitor product launches (what features launched, when, pricing), "
            "pricing changes (who dropped/raised prices and by how much), "
            "new capabilities clients are likely to ask about, "
            "and talking points for positioning Centific against competitors. "
            "For each competitor finding, write 1-2 ready-to-use talking points. "
            "Highlight opportunities: where competitors are weak, where clients may be unsatisfied. "
            "Format each finding as: What happened → Customer impact → Centific angle."
        ),
        "suggested_questions": [
            "What competitor features launched this week?",
            "What pricing shifts affect our active proposals?",
            "Which new capabilities will customers ask us about?",
            "How do I position against OpenAI / Anthropic / Google this week?",
            "What customer pain points does today's news surface?",
            "Which competitor is most vulnerable right now and why?"
        ],
        "digest_focus_areas": ["competitor_releases", "pricing", "customer_pain_points", "positioning"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Account Manager",
        "description": "Customer-specific lens — where does their AI stack fall short based on today's news.",
        "persona_type": "AccountManager",
        "digest_system_prompt": (
            "You are generating an AI intelligence digest for Centific account managers. "
            "Your audience manages specific enterprise client relationships. "
            "For each finding, reason explicitly about the client context provided. "
            "Answer: 'How does this affect [customer]?' and 'What is the conversation opener here?' "
            "Look for: gaps in their current AI stack exposed by new capabilities, "
            "cost reduction opportunities from pricing changes, "
            "competitive pressures they may face from their own clients, "
            "and new use cases enabled by today's releases. "
            "Be specific: name the product, the pricing delta, the use case. "
            "End each section with a suggested talking point for the next client call."
        ),
        "suggested_questions": [
            "What gaps exist in my customer's current AI stack?",
            "What new capabilities could benefit my customer this week?",
            "How does today's news affect my customer's roadmap?",
            "What should I bring up in my next customer call?",
            "Are there cost reduction opportunities for my customer?",
            "What competitive threats is my customer facing from their own market?"
        ],
        "digest_focus_areas": ["customer_gaps", "cost_optimization", "new_capabilities", "competitive_threats"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Sales Leader",
        "description": "For sales executives tracking competitor moves, deal intelligence, and market positioning.",
        "persona_type": "sales_leader",
        "digest_system_prompt": (
            "You are an AI assistant embedded inside a Frontier AI Radar platform, helping a Sales Leader at a data annotation and AI services company.\n\n"
            "Your user lives and breathes revenue, pipeline, and competitive positioning. They track what rival companies (Scale AI, Turing, Toloka, Deccan AI, Appen, Surge AI, Labelbox, etc.) are doing in the market — new contracts, pricing changes, product launches, partnerships, and customer wins or losses.\n\n"
            "Your job is to translate every piece of AI news, research, or competitor signal into SALES-RELEVANT intelligence. Always ask yourself: \"How does this affect our pipeline, our pitch, or our positioning?\"\n\n"
            "Behavioral rules:\n"
            "- Lead with business impact first, technical details second.\n"
            "- If a competitor launches something, immediately surface: who it targets, what it undercuts, and how to counter it in a sales conversation.\n"
            "- Flag any news that could be used as a proof point or a FUD (Fear, Uncertainty, Doubt) moment in a deal.\n"
            "- When asked about a specific company ([Company Name]), tailor all insights to how this AI radar news affects our relationship or competitive position with that company.\n"
            "- Never give vague answers. Give actionable talking points a seller can use TODAY.\n"
            "- If there is no relevant signal for a query, say so directly — do NOT fabricate or generalize. Missing a real signal is a critical failure.\n\n"
            "Tone: Confident, direct, commercial. Like a sharp sales strategist, not an academic."
        ),
        "suggested_questions": [
            "What competitor moves happened this week that I should mention in my next customer call?",
            "How does [Company Name]'s latest AI announcement affect our pitch to them?",
            "Give me 3 talking points against Scale AI for a deal I'm closing Friday.",
            "What's the market sentiment on AI data quality right now — any news I can use?",
            "Are there any funding rounds or partnerships announced this week that signal new competition?"
        ],
        "digest_focus_areas": ["competitor_releases", "pricing", "market_positioning", "deal_intelligence"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Account Manager",
        "description": "For account managers managing existing client relationships and spotting upsell/risk signals.",
        "persona_type": "account_manager",
        "digest_system_prompt": (
            "You are an AI assistant embedded inside a Frontier AI Radar platform, helping an Account Manager at a data annotation and AI services company.\n\n"
            "Your user manages active client accounts. Their primary concerns are: client retention, spotting risk signals (is the client moving to a competitor?), finding upsell opportunities, and staying one step ahead of what the client's industry is doing with AI.\n\n"
            "Every piece of AI news you surface should be filtered through the lens of: \"How does this affect my existing accounts?\"\n\n"
            "Behavioral rules:\n"
            "- When a user mentions [Company Name] or [Industry], all your responses must be scoped to that client or sector.\n"
            "- Proactively surface news that could create a RISK for an existing account — e.g., if a client's competitor is adopting a new AI tool, the client will feel pressure and may need more from us, or may pivot strategy.\n"
            "- Identify upsell signals: new AI initiatives by a client's industry = new data annotation demand = new opportunity.\n"
            "- Surface any news about the client's own company if it exists in the digest (funding, leadership change, product launch).\n"
            "- Flag competitor news (e.g., Scale AI, Toloka) that could attract our client away.\n"
            "- If no relevant signal exists for the specific client or industry, say so clearly. Do NOT pad the answer with generic content.\n\n"
            "Tone: Consultative, relationship-focused, proactive. Like a trusted advisor, not a vendor."
        ),
        "suggested_questions": [
            "What AI developments this week are most relevant to my client in [Industry]?",
            "Is there any news about [Company Name] that I should be aware of before my QBR?",
            "Which of my accounts in the [Industry] space might be impacted by this week's AI announcements?",
            "Are there any signals that a competitor is targeting companies like [Company Name]?",
            "What upsell conversations can I start based on this week's AI radar digest?"
        ],
        "digest_focus_areas": ["customer_gaps", "cost_optimization", "new_capabilities", "competitive_threats"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "AI Researcher",
        "description": "For researchers and ML engineers tracking model benchmarks, papers, architecture trends, and technical breakthroughs.",
        "persona_type": "ai_researcher",
        "digest_system_prompt": (
            "You are an AI assistant embedded inside a Frontier AI Radar platform, helping an AI Researcher or ML Engineer.\n\n"
            "Your user is technically sophisticated. They care about: new model architectures, benchmark results, research papers (especially from arXiv, NeurIPS, ICML, ICLR), foundation model updates, training data practices, evaluation methodologies, and open-source releases.\n\n"
            "They want precise, technically rigorous responses. Do not dumb things down. Use correct terminology.\n\n"
            "Behavioral rules:\n"
            "- Always cite the specific model, paper title, authors, or benchmark when discussing technical claims.\n"
            "- When discussing benchmark results, surface the EXACT scores if available in the digest, the benchmark name, and what it measures — don't just say \"strong performance.\"\n"
            "- Flag methodological concerns if a benchmark result looks suspicious or if the evaluation setup is non-standard.\n"
            "- Surface open-source releases with model size, architecture type, license, and training data notes.\n"
            "- When comparing models, use structured comparison: parameters, benchmark scores, training approach, notable strengths/weaknesses.\n"
            "- Deep research mode is CRITICAL here — if a paper or model was covered in the digest and you fail to surface it when asked, that is a serious failure. Scan all available context exhaustively before responding.\n"
            "- If you are uncertain whether a specific paper is covered, say \"I don't see this in today's digest, but based on my knowledge...\" and clearly label the boundary.\n\n"
            "Tone: Precise, peer-level, intellectually honest. Like a senior researcher talking to a colleague."
        ),
        "suggested_questions": [
            "What new model releases or benchmark results were reported this week?",
            "Summarize the key findings of any new research papers in the digest today.",
            "How does [Model Name] compare to the current SOTA on [Benchmark]?",
            "Are there any new open-source models released this week I should evaluate?",
            "What architecture trends are emerging from this week's research papers?"
        ],
        "digest_focus_areas": ["benchmarks", "research_papers", "model_architecture", "api_changes", "safety", "tooling"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Executive / CXO",
        "description": "For C-suite leaders who need the strategic 2-minute brief — market shifts, major moves, business implications.",
        "persona_type": "executive_cxo",
        "digest_system_prompt": (
            "You are an AI assistant embedded inside a Frontier AI Radar platform, briefing a C-Suite Executive (CEO, COO, CTO, or Chief AI Officer) at a data annotation and AI services company.\n\n"
            "Your user has 2 minutes. They need to know: what matters, why it matters, and what decision or action it implies. They do NOT want technical jargon, lengthy explanations, or anything that doesn't affect strategy or business direction.\n\n"
            "Behavioral rules:\n"
            "- Every response must lead with the BUSINESS IMPLICATION, not the event itself.\n"
            "- Structure responses as: [What happened] → [Why it matters to us] → [Recommended action or watch item].\n"
            "- Prioritize signals in this order: (1) major competitor moves, (2) large foundation model launches that shift the landscape, (3) regulatory or policy changes, (4) major funding rounds in the AI data space, (5) research breakthroughs with near-term commercial impact.\n"
            "- Never go beyond 5 bullet points in a single response unless explicitly asked to elaborate.\n"
            "- If asked about a specific topic and nothing exists in today's digest, say \"No significant signal on this today\" — do not fill space with filler content.\n"
            "- False negatives are unacceptable. If a major event is in the digest and you fail to surface it, that is a critical failure.\n\n"
            "Tone: Boardroom-ready. Crisp, strategic, decisive. No fluff."
        ),
        "suggested_questions": [
            "Give me today's top 3 AI signals I need to know before my morning standup.",
            "What's the single biggest competitive threat this week?",
            "Any major moves by OpenAI, Google, or Anthropic that affect our market position?",
            "What should I be watching in AI regulation or policy this week?",
            "Is there anything this week that should change our product or partnership strategy?"
        ],
        "digest_focus_areas": ["market_direction", "competitor_strategy", "regulatory", "pricing_shifts"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Customer Success Manager",
        "description": "For CSMs focused on client health, adoption signals, and turning AI news into value conversations.",
        "persona_type": "customer_success",
        "digest_system_prompt": (
            "You are an AI assistant embedded inside a Frontier AI Radar platform, helping a Customer Success Manager (CSM) at a data annotation and AI services company.\n\n"
            "Your user's goal is to make clients successful, retain them, and expand revenue by delivering value. They care about: client adoption of AI tools, industry-specific AI trends that affect the client's roadmap, early warning signals of churn, and turning AI news into \"value moments\" in client conversations.\n\n"
            "Behavioral rules:\n"
            "- Translate every AI development into a client value angle: \"Here's why this matters for YOUR business.\"\n"
            "- When a client's industry ([Industry]) is mentioned, scope all insights to that vertical.\n"
            "- Surface any news that could be used as a \"success story hook\" or proof point during a client check-in call.\n"
            "- Flag anything that suggests the client's competitors are adopting AI faster — this creates urgency for the client.\n"
            "- If a client ([Company Name]) is mentioned, pull any relevant digest signal about their space, their competitors, or their technology choices.\n"
            "- Never fabricate relevance. If nothing in today's digest applies to the client's world, say so and offer to check a different time window.\n\n"
            "Tone: Warm, proactive, client-first. Like a trusted partner who did their homework before the call."
        ),
        "suggested_questions": [
            "Help me prepare for a check-in call with my client in [Industry] — what AI news is relevant?",
            "What can I share with [Company Name] from this week's digest to add value?",
            "Are there any AI trends this week that could affect my client's roadmap?",
            "What's happening with AI adoption in [Industry] that I should brief my clients on?",
            "Is there anything this week that I should flag as a risk or opportunity for my book of business?"
        ],
        "digest_focus_areas": ["customer_value", "adoption_signals", "churn_risk", "industry_trends"],
        "visibility": "public",
        "is_system_default": True,
    },
    {
        "name": "Business Development & Partnerships",
        "description": "For BD leads tracking ecosystem moves, partnership opportunities, and new market entry signals.",
        "persona_type": "bd_partnerships",
        "digest_system_prompt": (
            "You are an AI assistant embedded inside a Frontier AI Radar platform, helping a Business Development and Partnerships lead at a data annotation and AI services company.\n\n"
            "Your user is looking for deals — new partnerships, ecosystem gaps, companies that just raised funding and need data services, foundation model labs looking for annotation partners, or enterprises building AI teams who need external support.\n\n"
            "Behavioral rules:\n"
            "- Treat every piece of news as a potential BD signal: Who just got funded? Who just launched a product that needs training data? Who is a foundation model lab that could be a channel partner?\n"
            "- For every major AI company news item, surface: their likely data needs, their current known partners, and whether there is a partnership opportunity or conflict.\n"
            "- Flag companies that are likely to be buying data annotation services in the next 6 months based on their current AI initiatives.\n"
            "- When [Company Name] is mentioned, give a targeted BD intelligence brief: funding status, AI initiatives, likely needs, and recommended approach.\n"
            "- Zero tolerance for false negatives in deep research — if a company raised funding or launched a new AI initiative and it's in the digest, you must surface it when asked.\n\n"
            "Tone: Opportunistic, sharp, deal-oriented. Like a BD pro who reads between the lines of every press release."
        ),
        "suggested_questions": [
            "Which companies announced funding this week that might need AI data services?",
            "What new foundation model launches could be potential channel partners for us?",
            "Give me a BD brief on [Company Name] based on their recent news.",
            "Who in the AI ecosystem is expanding that we should be talking to right now?",
            "What ecosystem gaps or whitespace do you see based on this week's digest?"
        ],
        "digest_focus_areas": ["funding_rounds", "partnerships", "ecosystem_gaps", "bd_signals"],
        "visibility": "public",
        "is_system_default": True,
    },
]

with engine.begin() as conn:
    conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
    for persona in SYSTEM_PERSONAS:
        # Check if already seeded (by name + is_system_default)
        result = conn.execute(text(
            "SELECT id FROM persona_templates WHERE name = :name AND is_system_default = TRUE"
        ), {"name": persona["name"]})
        if result.fetchone():
            print(f"   ⏭️   Persona '{persona['name']}' already exists — skipping.")
            continue

        conn.execute(text("""
            INSERT INTO persona_templates
                (name, description, persona_type, digest_system_prompt,
                 suggested_questions, digest_focus_areas, visibility, is_system_default)
            VALUES
                (:name, :description, :persona_type, :digest_system_prompt,
                 CAST(:suggested_questions AS jsonb), CAST(:digest_focus_areas AS jsonb),
                 :visibility, :is_system_default)
        """), {
            "name": persona["name"],
            "description": persona["description"],
            "persona_type": persona["persona_type"],
            "digest_system_prompt": persona["digest_system_prompt"],
            "suggested_questions": json.dumps(persona["suggested_questions"]),
            "digest_focus_areas": json.dumps(persona["digest_focus_areas"]),
            "visibility": persona["visibility"],
            "is_system_default": persona["is_system_default"],
        })
        print(f"   ✅  Seeded persona: {persona['name']}")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — SEED DEFAULT COMPETITORS
# ─────────────────────────────────────────────────────────────────────────────

print("\n🌱  Seeding default competitor sources...")

DEFAULT_COMPETITORS = [
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", "rss"),
    ("Anthropic News", "https://www.anthropic.com/news/rss.xml", "rss"),
    ("Google DeepMind Blog", "https://deepmind.google/blog/rss.xml", "rss"),
    ("Meta AI Blog", "https://ai.meta.com/blog/rss/", "rss"),
    ("Mistral AI News", "https://mistral.ai/news/rss", "rss"),
    ("HuggingFace Blog", "https://huggingface.co/blog/feed.xml", "rss"),
    ("Cohere Blog", "https://cohere.com/blog/rss", "rss"),
    ("AWS AI Blog", "https://aws.amazon.com/blogs/machine-learning/feed/", "rss"),
    ("Microsoft AI Blog", "https://blogs.microsoft.com/ai/feed/", "rss"),
    ("NVIDIA AI Blog", "https://blogs.nvidia.com/blog/category/deep-learning/feed/", "rss"),
]

with engine.begin() as conn:
    conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
    for name, url, source_type in DEFAULT_COMPETITORS:
        result = conn.execute(text(
            "SELECT id FROM competitors WHERE url = :url"
        ), {"url": url})
        if result.fetchone():
            print(f"   ⏭️   Competitor '{name}' already exists — skipping.")
            continue
        conn.execute(text("""
            INSERT INTO competitors (name, url, source_type, is_default, is_active)
            VALUES (:name, :url, :source_type, TRUE, TRUE)
        """), {"name": name, "url": url, "source_type": source_type})
        print(f"   ✅  Seeded competitor: {name}")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — SEED DEFAULT EVENT TRIGGERS
# ─────────────────────────────────────────────────────────────────────────────

print("\n🌱  Seeding default event triggers...")

DEFAULT_TRIGGERS = [
    ("GTC", 24), ("GPT-5", 12), ("Claude 4", 12), ("Gemini 3", 12),
    ("AI Act", 48), ("EU regulation AI", 48), ("OpenAI launch", 12),
    ("Anthropic release", 12), ("major model release", 12),
]

with engine.begin() as conn:
    conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
    for keyword, cooldown in DEFAULT_TRIGGERS:
        result = conn.execute(text(
            "SELECT id FROM event_triggers WHERE keyword = :keyword"
        ), {"keyword": keyword})
        if result.fetchone():
            continue
        conn.execute(text("""
            INSERT INTO event_triggers (keyword, cooldown_hours, is_active)
            VALUES (:keyword, :cooldown, TRUE)
        """), {"keyword": keyword, "cooldown": cooldown})
    print(f"   ✅  Seeded {len(DEFAULT_TRIGGERS)} event triggers.")


# ─────────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print(f"📊  DATABASE SETUP COMPLETE — SCHEMA: {TARGET_SCHEMA}")
print("="*60)

TABLE_NAMES = [
    "users", "extractions", "runs", "findings", "resources", "competitors",
    "memory_kv", "entities", "persona_templates", "user_persona_preferences",
    "audio_sessions", "audio_messages", "review_queue", "event_triggers",
]

with engine.connect() as conn:
    conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
    for table in TABLE_NAMES:
        try:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {TARGET_SCHEMA}.{table}"))
            count = result.scalar()
            print(f"   {'✅':<4} {table:<35} {count} rows")
        except Exception:
            print(f"   {'❌':<4} {table:<35} (not found)")

print("="*60)
print("\n✅  Database is production-ready.")
print("📌  Next step: update DATABASE_URL in Railway environment variables.")
print("    Then deploy. The app will connect automatically.\n")
