-- Frontier AI Radar – SQLite Schema
-- Auto-created by SQLAlchemy on first run.
-- This file is kept as a reference / manual fallback.
-- Run manually: sqlite3 db/frontier_ai_radar.db < db/init.sql

-- 1. Extractions: basic info before passing to next stages
CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_date TIMESTAMP,
    mode VARCHAR(10) CHECK (mode IN ('job', 'UI')),
    metadata TEXT,  -- JSON stored as TEXT in SQLite
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Findings: high-impact summaries, scores, content from Summarizer Layer
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id INTEGER NOT NULL,
    agent_name VARCHAR(20) NOT NULL,
    html_content TEXT,
    pdf_content BLOB,
    metadata TEXT,  -- JSON stored as TEXT in SQLite
    FOREIGN KEY (extraction_id) REFERENCES extractions(id) ON DELETE CASCADE
);

-- 3. Users: subscribed email recipients
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL,
    email VARCHAR(320) NOT NULL UNIQUE,
    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Runs: observability / history / status of each execution
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id INTEGER,
    user_id INTEGER,     -- who triggered this run (NULL for cron jobs)
    status VARCHAR(20),
    time_taken INTEGER,  -- duration in seconds
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    pdf_path TEXT,       -- filesystem path for reference
    pdf_content BLOB,    -- actual PDF bytes
    FOREIGN KEY (extraction_id) REFERENCES extractions(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- 5. Resources: every source URL / name discovered by each agent per run
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    agent_name VARCHAR(20) NOT NULL,
    name VARCHAR(500) NOT NULL,
    url TEXT,
    resource_type VARCHAR(50),
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- 6. Competitors: configurable competitor sources for the Competitor Intel agent
--    Pre-seeded with defaults on first deploy; users can add extras via API.
CREATE TABLE IF NOT EXISTS competitors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(200) NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    source_type VARCHAR(20) NOT NULL,     -- 'rss' | 'webpage'
    selector    VARCHAR(200),              -- CSS selector (webpage only)
    is_default  BOOLEAN DEFAULT 1,         -- TRUE = seeded on deploy
    is_active   BOOLEAN DEFAULT 1,         -- toggle without deleting
    added_by    INTEGER,                   -- FK to users.id (NULL for defaults)
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL
);

SET search_path TO ai_radar;

-- ── 1. chat_sessions ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_radar.chat_sessions (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       INTEGER     REFERENCES ai_radar.users(id) ON DELETE CASCADE,
    run_id        INTEGER     NOT NULL REFERENCES ai_radar.runs(id) ON DELETE CASCADE,
    title         VARCHAR(200),
    message_count INTEGER     NOT NULL DEFAULT 0,
    created_at    TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_active   TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_user_run
    ON ai_radar.chat_sessions(user_id, run_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_run
    ON ai_radar.chat_sessions(run_id);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_active
    ON ai_radar.chat_sessions(last_active DESC);


-- ── 2. chat_messages ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_radar.chat_messages (
    id          BIGSERIAL   PRIMARY KEY,
    session_id  UUID        NOT NULL
                    REFERENCES ai_radar.chat_sessions(id) ON DELETE CASCADE,
    role        VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content     TEXT        NOT NULL,
    sources     JSONB       NOT NULL DEFAULT '[]',
    tool_calls  JSONB       NOT NULL DEFAULT '[]',
    mode        VARCHAR(10) NOT NULL DEFAULT 'text'
                    CHECK (mode IN ('text', 'voice')),
    tokens_used INTEGER,
    created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_time
    ON ai_radar.chat_messages(session_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_desc
    ON ai_radar.chat_messages(session_id, created_at DESC);


-- ── 3. chat_answer_cache ──────────────────────────────────────────
-- TODO [PRODUCTION]: Once DevOps allowlists 'vector' extension in Azure Portal
--   (Settings → Server parameters → azure.extensions → add VECTOR),
--   migrate question_embedding from FLOAT[] to vector(384) and add:
--   CREATE INDEX idx_cache_embedding_hnsw ON ai_radar.chat_answer_cache
--   USING hnsw (question_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
--   This drops semantic similarity query from ~20ms (Python) to ~2ms (SQL).

CREATE TABLE IF NOT EXISTS ai_radar.chat_answer_cache (
    id                  BIGSERIAL   PRIMARY KEY,
    run_id              INTEGER     NOT NULL
                            REFERENCES ai_radar.runs(id) ON DELETE CASCADE,
    question_text       TEXT        NOT NULL,
    question_hash       VARCHAR(64) NOT NULL,
    question_embedding  FLOAT[],
    answer_text         TEXT        NOT NULL,
    sources             JSONB       NOT NULL DEFAULT '[]',
    tool_calls_used     JSONB       NOT NULL DEFAULT '[]',
    mode                VARCHAR(10) NOT NULL DEFAULT 'text',
    hit_count           INTEGER     NOT NULL DEFAULT 0,
    created_at          TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_hit_at         TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cache_run_hash
    ON ai_radar.chat_answer_cache(run_id, question_hash);

CREATE INDEX IF NOT EXISTS idx_cache_popular
    ON ai_radar.chat_answer_cache(run_id, hit_count DESC);


-- ── 4. Verify ─────────────────────────────────────────────────────
SELECT
    relname         AS table_name,
    (SELECT COUNT(*)
     FROM information_schema.columns
     WHERE table_schema = 'ai_radar'
       AND table_name    = r.relname) AS column_count
FROM pg_class r
JOIN pg_namespace n ON n.oid = r.relnamespace
WHERE n.nspname  = 'ai_radar'
  AND r.relname IN ('chat_sessions', 'chat_messages', 'chat_answer_cache')
ORDER BY relname;



-- ── 1. Voice presets catalog ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS voice_presets (
    id               VARCHAR(50)  PRIMARY KEY,
    voice_id         VARCHAR(100) NOT NULL,
    label            VARCHAR(100) NOT NULL,
    gender           VARCHAR(20)  NOT NULL DEFAULT 'neutral',
    style            VARCHAR(50)  NOT NULL DEFAULT 'professional',
    elevenlabs_model VARCHAR(100) NOT NULL DEFAULT 'eleven_turbo_v2',
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE
);

INSERT INTO voice_presets (id, voice_id, label, gender, style, elevenlabs_model) VALUES
  -- ── Original presets ─────────────────────────────────────────────────────
  ('rachel_professional',   '21m00Tcm4TlvDq8ikWAM', 'Rachel – Female, Professional (American)',   'female', 'american',        'eleven_turbo_v2'),
  ('adam_calm',             'pNInz6obpgDQGcFmaJgB', 'Adam – Male, Calm (American)',                'male',   'american',        'eleven_turbo_v2'),
  ('elli_energetic',        'MF3mGyEYCl7XYWbV9V6O', 'Elli – Female, Energetic (American)',        'female', 'american',        'eleven_turbo_v2'),
  -- ── American ─────────────────────────────────────────────────────────────
  ('jessica_conversational','cgSgspJ2msm6clMCkdW9', 'Jessica – Female, Conversational (American)','female', 'american',        'eleven_turbo_v2'),
  ('eric_trustworthy',      'cjVigY5qzO86Huf0OWal', 'Eric – Male, Trustworthy (American)',         'male',   'american',        'eleven_turbo_v2'),
  ('matilda_educational',   'XrExE9yKIg1WjnnlVkGX', 'Matilda – Female, Educational (American)',   'female', 'american',        'eleven_turbo_v2'),
  ('brian_deep',            'nPczCjzI2devNBz1zQrb', 'Brian – Male, Deep & Comforting (American)', 'male',   'american',        'eleven_turbo_v2'),
  ('sarah_mature',          'EXAVITQu4vr4xnSDxMaL', 'Sarah – Female, Mature & Confident (American)','female','american',       'eleven_turbo_v2'),
  -- ── British ──────────────────────────────────────────────────────────────
  ('daniel_british',        'onwK4e9ZLuTAKqWW03F9', 'Daniel – Male, Broadcaster (British)',        'male',   'british',         'eleven_turbo_v2'),
  ('alice_british',         'Xb7hH8MSUJpSbSDYk0k2', 'Alice – Female, Educator (British)',          'female', 'british',         'eleven_turbo_v2'),
  ('george_british',        'JBFqnCBsd6RMkjVDRZzb', 'George – Male, Storyteller (British)',        'male',   'british',         'eleven_turbo_v2'),
  ('lily_british',          'pFZP5JQG7iQjIQuC4Bku', 'Lily – Female, Velvety (British)',            'female', 'british',         'eleven_turbo_v2'),
  ('emilia_british',        'E4IXevHtHpKGh0bvrPPr', 'Emilia – Female, Young Narrator (British)',  'female', 'british',         'eleven_turbo_v2'),
  -- ── Australian ───────────────────────────────────────────────────────────
  ('charlie_australian',    'IKne3meq5aSn9XLyUdCD', 'Charlie – Male, Energetic (Australian)',      'male',   'australian',      'eleven_turbo_v2'),
  ('samuel_australian',     'FrejFnPpRNrX6s6raOSX', 'Samuel – Male, Calm & Steady (Australian)',  'male',   'australian',      'eleven_turbo_v2'),
  ('brad_australian',       'HZTk7bUIkiI7yT7FKH4h', 'Brad – Male, Meditation (Australian)',       'male',   'australian',      'eleven_turbo_v2'),
  -- ── Indian ───────────────────────────────────────────────────────────────
  ('aaditya_indian',        'qWdiyiWdNPlPyVCOLW0h', 'Aaditya K – Male, Storyteller (Indian)',      'male',   'indian',          'eleven_turbo_v2'),
  ('diya_indian',           'Rk0hF1X0z2RQCmWH9SCb', 'Diya – Female, Soft & Trustworthy (Indian)', 'female', 'indian',          'eleven_turbo_v2'),
  ('raju_indian',           'pzxut4zZz4GImZNlqQ3H', 'Raju – Male, Customer Care (Indian)',         'male',   'indian',          'eleven_turbo_v2'),
  ('rhea_indian',           'eUdJpUEN3EslrgE24PKx', 'Rhea – Female, Polished (Indian)',            'female', 'indian',          'eleven_turbo_v2'),
  ('rahul_indian',          'u7bRcYbD7visSINTyAT8', 'Rahul – Male, Energetic (Indian)',            'male',   'indian',          'eleven_turbo_v2'),
  ('tarun_indian',          'v9Yyk1Gw8jEMGWtj1hgu', 'Tarun D – Male, Rich & Polished (Indian)',   'male',   'indian',          'eleven_turbo_v2'),
  -- ── Irish ────────────────────────────────────────────────────────────────
  ('maeve_irish',           'kOvUpYLYS0rKGldsKcD1', 'Maeve – Female, Soft (Irish)',                'female', 'irish',           'eleven_turbo_v2'),
  ('emily_irish',           'odyUrTN5HMVKujvVAgWW', 'Emily – Female, Influencer (Irish)',          'female', 'irish',           'eleven_turbo_v2'),
  -- ── Scottish ─────────────────────────────────────────────────────────────
  ('mark_scottish',         'pp4ihOlfDr2MgdTALvoR', 'Mark – Male, Warm Narrator (Scottish)',       'male',   'scottish',        'eleven_turbo_v2'),
  -- ── German accent ────────────────────────────────────────────────────────
  ('chris_german',          'blS2CVtvoZT2lNa8n6qk', 'Chris – Male, English with German Accent',   'male',   'german',          'eleven_turbo_v2'),
  -- ── Spanish / Latin American ─────────────────────────────────────────────
  ('ernesto_spanish',       'ZwLTvq6uCfb4W00YFl7F', 'Ernesto – Male, Mexican-American (Spanish)', 'male',   'latin american',  'eleven_turbo_v2'),
  -- ── Nigerian ─────────────────────────────────────────────────────────────
  ('favour_nigerian',       'ZXZq039skp0kfF9gO7Au', 'Favour – Female, Calm Narrator (Nigerian)',  'female', 'nigerian',        'eleven_turbo_v2'),
  -- ── Persian / Iranian ────────────────────────────────────────────────────
  ('shahram_persian',       'rNb3hdSf0n4ROIbYC8Bl', 'Shahram – Male, Documentary (Persian/Farsi)','male',   'persian',         'eleven_turbo_v2'),
  -- ── New Zealand ──────────────────────────────────────────────────────────
  ('liam_nz',               '6J1lB05oyDOLPaxMFyS9', 'Liam – Male, Narrator (New Zealand)',         'male',   'new zealand',     'eleven_turbo_v2')
ON CONFLICT (id) DO NOTHING;


-- ── 2. audio_script_blob_path on runs ────────────────────────────────────────
-- Stores the path of the LLM-generated narration .txt file in Azure Blob.
-- Set per-run by the post-pipeline audio script agent.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS audio_script_blob_path TEXT;


-- ── 3. audio_presets_paths on runs (JSONB) ────────────────────────────────────
-- Stores per-preset MP3 blob paths.
-- Example: {"rachel_professional": "Frontier-AI-Radar/digest-20260317/rachel_professional.mp3"}
ALTER TABLE runs ADD COLUMN IF NOT EXISTS audio_presets_paths JSONB DEFAULT '{}';

-- Note: blob_audio_path (TEXT) stays for backwards compat but will be deprecated.
-- Note: blob_sas_cache (JSONB) stays as-is — we'll nest audio SAS under
--       {"audio": {"rachel_professional": {"url": "...", "expires_at": "..."}}}
