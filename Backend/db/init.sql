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
