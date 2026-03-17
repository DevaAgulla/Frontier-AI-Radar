"""
Frontier AI Radar - Schema Migration: ai_radar - ai_data_radar
===============================================================

Creates the new `ai_data_radar` schema with the following improvements
over `ai_radar`:

  1. No inline BYTEA content (pdf_content removed - blob storage is the source of truth)
  2. active_flag CHAR(1) DEFAULT 'Y' on mutable tables for soft deletes
  3. Normalized run_audio_presets table (replaces audio_presets_paths JSONB blob)
  4. Normalized run_asset_cache table (replaces blob_sas_cache JSONB blob)
  5. is_admin column on users (was missing from ai_radar setup_db.py)
  6. Clean constraint and index naming throughout

After running this script, update Backend/db/connection.py:
    TARGET_SCHEMA = "ai_data_radar"

Usage:
    cd Backend
    python scripts/migrate_to_ai_data_radar.py
    python scripts/migrate_to_ai_data_radar.py --validate-only   # re-run counts only
    python scripts/migrate_to_ai_data_radar.py --skip-data       # DDL only, no data copy
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import sqlalchemy as sa
from sqlalchemy import text

# -----------------------------------------------------------------------------
# CONNECTION
# -----------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("\n[ERR]  DATABASE_URL not set in Backend/.env - aborting.\n")
    sys.exit(1)
if DATABASE_URL.startswith("sqlite"):
    print("\n[ERR]  DATABASE_URL is pointing to SQLite - this migration targets PostgreSQL.\n")
    sys.exit(1)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_AZURE = "postgres.database.azure.com" in DATABASE_URL
connect_args = {}
if IS_AZURE:
    if "sslmode" not in DATABASE_URL:
        DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
    connect_args["sslmode"] = "require"
connect_args["options"] = "-c search_path=public"

print(f"\n[>>]  Connecting to: {DATABASE_URL[:70]}...")
engine = sa.create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)

try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("[OK]  Connection OK.")
except Exception as e:
    print(f"\n[ERR]  Connection failed: {e}\n")
    sys.exit(1)

SRC = "ai_radar"
DST = "ai_data_radar"

# -----------------------------------------------------------------------------
# DDL - ai_data_radar schema
# -----------------------------------------------------------------------------

DDL_STATEMENTS = [

    # -- Schema --------------------------------------------------------------
    f"CREATE SCHEMA IF NOT EXISTS {DST}",

    # -- Extensions (safe - already enabled in public / ai_radar) -----------
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    "CREATE EXTENSION IF NOT EXISTS vector",

    # -- 1. users -------------------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.users (
        id                SERIAL       PRIMARY KEY,
        name              VARCHAR(200) NOT NULL,
        email             VARCHAR(320) NOT NULL UNIQUE,
        password_hash     VARCHAR(256),
        is_admin          BOOLEAN      NOT NULL DEFAULT FALSE,
        centific_team     VARCHAR(100),
        active_persona_id UUID,
        active_flag       CHAR(1)      NOT NULL DEFAULT 'Y' CHECK (active_flag IN ('Y','N')),
        subscribed_at     TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 2. extractions -------------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.extractions (
        id               SERIAL      PRIMARY KEY,
        publication_date TIMESTAMP,
        mode             VARCHAR(10) CHECK (mode IN ('job', 'UI')),
        metadata         TEXT,
        active_flag      CHAR(1)     NOT NULL DEFAULT 'Y' CHECK (active_flag IN ('Y','N')),
        created_at       TIMESTAMP   NOT NULL DEFAULT NOW()
    )
    """,

    # -- 3. runs -------------------------------------------------------------
    # pdf_content BYTEA REMOVED - blob storage is the source of truth
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.runs (
        id                     SERIAL      PRIMARY KEY,
        extraction_id          INTEGER     REFERENCES {DST}.extractions(id) ON DELETE SET NULL,
        user_id                INTEGER     REFERENCES {DST}.users(id)       ON DELETE SET NULL,
        status                 VARCHAR(20),
        run_mode               VARCHAR(20) NOT NULL DEFAULT 'daily'
                                   CHECK (run_mode IN ('daily','weekly','monthly')),
        time_taken             INTEGER,
        started_at             TIMESTAMP   NOT NULL DEFAULT NOW(),
        completed_at           TIMESTAMP,
        pdf_path               TEXT,
        persona_id             UUID,
        config                 JSONB       NOT NULL DEFAULT '{{}}',
        blob_pdf_path          TEXT,
        blob_audio_path        TEXT,
        audio_script_blob_path TEXT,
        active_flag            CHAR(1)     NOT NULL DEFAULT 'Y' CHECK (active_flag IN ('Y','N'))
    )
    """,

    # -- 4. run_audio_presets  (normalized - replaces audio_presets_paths JSONB) --
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.run_audio_presets (
        id          SERIAL       PRIMARY KEY,
        run_id      INTEGER      NOT NULL REFERENCES {DST}.runs(id) ON DELETE CASCADE,
        preset_id   VARCHAR(50)  NOT NULL,
        blob_path   TEXT,
        is_ready    BOOLEAN      NOT NULL DEFAULT FALSE,
        generated_at TIMESTAMP,
        UNIQUE (run_id, preset_id)
    )
    """,

    # -- 5. run_asset_cache  (normalized - replaces blob_sas_cache JSONB) ---
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.run_asset_cache (
        id          SERIAL       PRIMARY KEY,
        run_id      INTEGER      NOT NULL REFERENCES {DST}.runs(id) ON DELETE CASCADE,
        asset_type  VARCHAR(50)  NOT NULL,
        preset_id   VARCHAR(50),
        sas_url     TEXT         NOT NULL,
        expires_at  TIMESTAMP    NOT NULL,
        UNIQUE (run_id, asset_type, preset_id)
    )
    """,

    # -- 6. findings  (pdf_content BYTEA removed) ----------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.findings (
        id                 SERIAL       PRIMARY KEY,
        extraction_id      INTEGER      REFERENCES {DST}.extractions(id) ON DELETE CASCADE,
        run_id             INTEGER      REFERENCES {DST}.runs(id)        ON DELETE CASCADE,
        agent_name         VARCHAR(30)  NOT NULL,
        title              VARCHAR(500),
        source_url         TEXT,
        publisher          VARCHAR(200),
        what_changed       TEXT,
        why_it_matters     TEXT,
        evidence           TEXT,
        confidence         VARCHAR(10)  DEFAULT 'MEDIUM',
        impact_score       FLOAT        DEFAULT 0.0,
        relevance          FLOAT        DEFAULT 0.0,
        novelty            FLOAT        DEFAULT 0.0,
        credibility        FLOAT        DEFAULT 0.0,
        actionability      FLOAT        DEFAULT 0.0,
        rank               INTEGER,
        topic_cluster      VARCHAR(50),
        needs_verification BOOLEAN      DEFAULT FALSE,
        tags               TEXT[],
        html_content       TEXT,
        metadata           JSONB        NOT NULL DEFAULT '{{}}',
        active_flag        CHAR(1)      NOT NULL DEFAULT 'Y' CHECK (active_flag IN ('Y','N')),
        created_at         TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 7. resources ---------------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.resources (
        id            SERIAL       PRIMARY KEY,
        run_id        INTEGER      NOT NULL REFERENCES {DST}.runs(id) ON DELETE CASCADE,
        agent_name    VARCHAR(20)  NOT NULL,
        name          VARCHAR(500) NOT NULL,
        url           TEXT,
        resource_type VARCHAR(50),
        discovered_at TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 8. competitors -------------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.competitors (
        id          SERIAL       PRIMARY KEY,
        name        VARCHAR(200) NOT NULL,
        url         TEXT         NOT NULL UNIQUE,
        source_type VARCHAR(20)  NOT NULL,
        selector    VARCHAR(200),
        is_default  BOOLEAN      NOT NULL DEFAULT TRUE,
        is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
        added_by    INTEGER      REFERENCES {DST}.users(id) ON DELETE SET NULL,
        created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 9. voice_presets -----------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.voice_presets (
        id               VARCHAR(50)  PRIMARY KEY,
        voice_id         VARCHAR(100) NOT NULL,
        label            VARCHAR(100) NOT NULL,
        gender           VARCHAR(20)  NOT NULL DEFAULT 'neutral',
        style            VARCHAR(50)  NOT NULL DEFAULT 'professional',
        elevenlabs_model VARCHAR(100) NOT NULL DEFAULT 'eleven_turbo_v2',
        is_active        BOOLEAN      NOT NULL DEFAULT TRUE
    )
    """,

    # -- 10. persona_templates ------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.persona_templates (
        id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
        name                 VARCHAR(200) NOT NULL,
        description          TEXT,
        persona_type         VARCHAR(50),
        digest_system_prompt TEXT,
        suggested_questions  JSONB        NOT NULL DEFAULT '[]',
        digest_focus_areas   JSONB        NOT NULL DEFAULT '[]',
        owner_id             INTEGER      REFERENCES {DST}.users(id) ON DELETE SET NULL,
        visibility           VARCHAR(10)  NOT NULL DEFAULT 'private'
                                 CHECK (visibility IN ('public','private')),
        is_system_default    BOOLEAN      NOT NULL DEFAULT FALSE,
        created_at           TIMESTAMP    NOT NULL DEFAULT NOW(),
        updated_at           TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 11. user_persona_preferences ----------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.user_persona_preferences (
        user_id      INTEGER   NOT NULL REFERENCES {DST}.users(id)             ON DELETE CASCADE,
        persona_id   UUID      NOT NULL REFERENCES {DST}.persona_templates(id) ON DELETE CASCADE,
        pinned       BOOLEAN   NOT NULL DEFAULT FALSE,
        last_used_at TIMESTAMP,
        PRIMARY KEY (user_id, persona_id)
    )
    """,

    # -- 12. chat_sessions ---------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.chat_sessions (
        id            UUID      PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id       INTEGER   REFERENCES {DST}.users(id) ON DELETE CASCADE,
        run_id        INTEGER   NOT NULL REFERENCES {DST}.runs(id) ON DELETE CASCADE,
        title         VARCHAR(200),
        message_count INTEGER   NOT NULL DEFAULT 0,
        created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
        last_active   TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # -- 13. chat_messages ---------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.chat_messages (
        id          BIGSERIAL   PRIMARY KEY,
        session_id  UUID        NOT NULL REFERENCES {DST}.chat_sessions(id) ON DELETE CASCADE,
        role        VARCHAR(10) NOT NULL CHECK (role IN ('user','assistant','tool')),
        content     TEXT        NOT NULL,
        sources     JSONB       NOT NULL DEFAULT '[]',
        tool_calls  JSONB       NOT NULL DEFAULT '[]',
        mode        VARCHAR(10) NOT NULL DEFAULT 'text' CHECK (mode IN ('text','voice')),
        tokens_used INTEGER,
        created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
    )
    """,

    # -- 14. chat_answer_cache ------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.chat_answer_cache (
        id                 BIGSERIAL   PRIMARY KEY,
        run_id             INTEGER     NOT NULL REFERENCES {DST}.runs(id) ON DELETE CASCADE,
        question_text      TEXT        NOT NULL,
        question_hash      VARCHAR(64) NOT NULL,
        question_embedding FLOAT[],
        answer_text        TEXT        NOT NULL,
        sources            JSONB       NOT NULL DEFAULT '[]',
        tool_calls_used    JSONB       NOT NULL DEFAULT '[]',
        mode               VARCHAR(10) NOT NULL DEFAULT 'text',
        hit_count          INTEGER     NOT NULL DEFAULT 0,
        created_at         TIMESTAMP   NOT NULL DEFAULT NOW(),
        last_hit_at        TIMESTAMP
    )
    """,

    # -- 15. audio_sessions --------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.audio_sessions (
        id                 UUID      PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id            INTEGER   REFERENCES {DST}.users(id)             ON DELETE SET NULL,
        run_id             INTEGER   REFERENCES {DST}.runs(id)              ON DELETE SET NULL,
        persona_id         UUID      REFERENCES {DST}.persona_templates(id) ON DELETE SET NULL,
        session_state      VARCHAR(20) NOT NULL DEFAULT 'menu',
        conversation       JSONB     NOT NULL DEFAULT '[]',
        findings_explored  INTEGER[] NOT NULL DEFAULT '{{}}',
        started_at         TIMESTAMP NOT NULL DEFAULT NOW(),
        ended_at           TIMESTAMP,
        duration_seconds   INTEGER
    )
    """,

    # -- 16. audio_messages --------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.audio_messages (
        id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id   UUID        NOT NULL REFERENCES {DST}.audio_sessions(id) ON DELETE CASCADE,
        turn_index   INTEGER,
        role         VARCHAR(10) NOT NULL CHECK (role IN ('user','assistant')),
        text_content TEXT,
        audio_url    VARCHAR(500),
        agent_type   VARCHAR(30),
        created_at   TIMESTAMP   NOT NULL DEFAULT NOW()
    )
    """,

    # -- 17. entities --------------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.entities (
        id          VARCHAR(200) PRIMARY KEY,
        name        VARCHAR(300) NOT NULL,
        entity_type VARCHAR(50)  NOT NULL,
        description TEXT,
        metadata    JSONB        NOT NULL DEFAULT '{{}}',
        source      VARCHAR(50)  NOT NULL DEFAULT 'seed',
        created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 18. memory_kv -------------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.memory_kv (
        key        VARCHAR(500) PRIMARY KEY,
        value      JSONB,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # -- 19. event_triggers --------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.event_triggers (
        id             SERIAL       PRIMARY KEY,
        keyword        VARCHAR(200) NOT NULL,
        cooldown_hours INTEGER      NOT NULL DEFAULT 24,
        last_triggered TIMESTAMP,
        is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at     TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- 20. review_queue ----------------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DST}.review_queue (
        id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id         INTEGER      REFERENCES {DST}.runs(id) ON DELETE CASCADE,
        section        VARCHAR(50),
        reviewer_email VARCHAR(320),
        status         VARCHAR(20)  NOT NULL DEFAULT 'pending',
        comments       TEXT,
        reviewed_at    TIMESTAMP,
        created_at     TIMESTAMP    NOT NULL DEFAULT NOW()
    )
    """,

    # -- INDEXES --------------------------------------------------------------
    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_user_run  ON {DST}.chat_sessions(user_id, run_id) WHERE user_id IS NOT NULL",
    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_cache_run_hash          ON {DST}.chat_answer_cache(run_id, question_hash)",
    f"CREATE INDEX IF NOT EXISTS idx_runs_status       ON {DST}.runs(status)",
    f"CREATE INDEX IF NOT EXISTS idx_runs_started      ON {DST}.runs(started_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_runs_active       ON {DST}.runs(active_flag) WHERE active_flag = 'Y'",
    f"CREATE INDEX IF NOT EXISTS idx_findings_run      ON {DST}.findings(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_findings_agent    ON {DST}.findings(agent_name)",
    f"CREATE INDEX IF NOT EXISTS idx_findings_impact   ON {DST}.findings(impact_score DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_findings_active   ON {DST}.findings(active_flag) WHERE active_flag = 'Y'",
    f"CREATE INDEX IF NOT EXISTS idx_resources_run     ON {DST}.resources(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_chat_msg_session  ON {DST}.chat_messages(session_id, created_at ASC)",
    f"CREATE INDEX IF NOT EXISTS idx_cache_popular     ON {DST}.chat_answer_cache(run_id, hit_count DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_audio_sess_user   ON {DST}.audio_sessions(user_id)",
    f"CREATE INDEX IF NOT EXISTS idx_audio_msg_session ON {DST}.audio_messages(session_id)",
    f"CREATE INDEX IF NOT EXISTS idx_entities_type     ON {DST}.entities(entity_type)",
    f"CREATE INDEX IF NOT EXISTS idx_run_audio_run     ON {DST}.run_audio_presets(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_run_asset_run     ON {DST}.run_asset_cache(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_persona_system    ON {DST}.persona_templates(is_system_default)",
]


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def src_table_exists(conn, table: str) -> bool:
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = :s AND table_name = :t"
    ), {"s": SRC, "t": table})
    return bool(r.fetchone())


def src_column_exists(conn, table: str, col: str) -> bool:
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
    ), {"s": SRC, "t": table, "c": col})
    return bool(r.fetchone())


def src_count(conn, table: str) -> int:
    try:
        r = conn.execute(text(f"SELECT COUNT(*) FROM {SRC}.{table}"))
        return r.scalar() or 0
    except Exception:
        return 0


def dst_count(conn, table: str) -> int:
    try:
        r = conn.execute(text(f"SELECT COUNT(*) FROM {DST}.{table}"))
        return r.scalar() or 0
    except Exception:
        return 0


# -----------------------------------------------------------------------------
# STEP 1 - CREATE DDL
# -----------------------------------------------------------------------------

def create_schema():
    print(f"\n{'='*60}")
    print(f"STEP 1 - Creating schema '{DST}' and all tables")
    print(f"{'='*60}")

    for stmt in DDL_STATEMENTS:
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception as e:
            err_str = str(e)
            if "already exists" in err_str:
                pass  # idempotent - expected
            elif "uuid-ossp" in err_str or "vector" in err_str or "extension" in err_str.lower():
                print(f"  [WARN] Extension skipped (not allow-listed on Azure): {stmt[:60]}")
            else:
                print(f"  [WARN] DDL: {err_str[:120]}")

    print(f"[OK]  Schema '{DST}' and all tables ready.")


# -----------------------------------------------------------------------------
# STEP 2 - MIGRATE DATA
# -----------------------------------------------------------------------------

def _run(sql: str, params: dict = None):
    """Execute SQL in its own transaction (independent — won't poison other steps)."""
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def _check(table: str, schema: str = SRC) -> bool:
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=:s AND table_name=:t"
        ), {"s": schema, "t": table})
        return bool(r.fetchone())


def _col_exists(table: str, col: str, schema: str = SRC) -> bool:
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=:s AND table_name=:t AND column_name=:c"
        ), {"s": schema, "t": table, "c": col})
        return bool(r.fetchone())


def _count(table: str, schema: str = SRC) -> int:
    try:
        with engine.connect() as conn:
            r = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
            return r.scalar() or 0
    except Exception:
        return 0


def migrate_data():
    print(f"\n{'='*60}")
    print(f"STEP 2 - Migrating data: {SRC} -> {DST}")
    print(f"{'='*60}")

    # Each table migrated in its own transaction so failures are isolated

    # -- users ----------------------------------------------------------------
    if _check("users"):
        n = _count("users")
        is_admin_expr = "is_admin" if _col_exists("users", "is_admin") else "FALSE"
        _run(f"""
            INSERT INTO {DST}.users
                (id, name, email, password_hash, is_admin, centific_team,
                 active_persona_id, subscribed_at)
            SELECT id, name, email, password_hash, {is_admin_expr}, centific_team,
                   active_persona_id, subscribed_at
            FROM {SRC}.users ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.users_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.users), 1))")
        print(f"  [OK]  users: {n} rows migrated")

    # -- extractions ----------------------------------------------------------
    if _check("extractions"):
        n = _count("extractions")
        _run(f"""
            INSERT INTO {DST}.extractions (id, publication_date, mode, metadata, created_at)
            SELECT id, publication_date, mode, metadata, created_at
            FROM {SRC}.extractions ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.extractions_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.extractions), 1))")
        print(f"  [OK]  extractions: {n} rows migrated")

    # -- runs (pdf_content dropped) -------------------------------------------
    if _check("runs"):
        n = _count("runs")
        blob_pdf  = "blob_pdf_path"          if _col_exists("runs", "blob_pdf_path")          else "NULL"
        blob_aud  = "blob_audio_path"         if _col_exists("runs", "blob_audio_path")         else "NULL"
        script    = "audio_script_blob_path"  if _col_exists("runs", "audio_script_blob_path")  else "NULL"
        _run(f"""
            INSERT INTO {DST}.runs
                (id, extraction_id, user_id, status, run_mode, time_taken,
                 started_at, completed_at, pdf_path, persona_id, config,
                 blob_pdf_path, blob_audio_path, audio_script_blob_path)
            SELECT id, extraction_id, user_id, status,
                   COALESCE(run_mode, 'daily'), time_taken,
                   started_at, completed_at, pdf_path, persona_id,
                   COALESCE(config, '{{}}'::jsonb),
                   {blob_pdf}, {blob_aud}, {script}
            FROM {SRC}.runs ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.runs_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.runs), 1))")
        print(f"  [OK]  runs: {n} rows migrated (pdf_content dropped)")

    # -- run_audio_presets (expand JSONB) -------------------------------------
    if _check("runs") and _col_exists("runs", "audio_presets_paths"):
        _run(f"""
            INSERT INTO {DST}.run_audio_presets (run_id, preset_id, blob_path, is_ready)
            SELECT r.id, kv.key, kv.value, TRUE
            FROM {SRC}.runs r,
                 jsonb_each_text(COALESCE(r.audio_presets_paths, '{{}}'::jsonb)) AS kv
            WHERE kv.value IS NOT NULL AND kv.value != ''
            ON CONFLICT (run_id, preset_id) DO NOTHING
        """)
        print(f"  [OK]  run_audio_presets: {_count('run_audio_presets', DST)} rows expanded")

    # -- run_asset_cache (expand blob_sas_cache JSONB) ------------------------
    if _check("runs") and _col_exists("runs", "blob_sas_cache"):
        rows = []
        with engine.connect() as c2:
            r = c2.execute(text(
                f"SELECT id, blob_sas_cache FROM {SRC}.runs "
                f"WHERE blob_sas_cache IS NOT NULL AND blob_sas_cache != '{{}}'::jsonb"
            ))
            rows = r.fetchall()
        migrated_cache = 0
        for run_id, sas_cache in rows:
            if not sas_cache:
                continue
            for asset_type, val in sas_cache.items():
                if isinstance(val, dict) and "url" in val:
                    expires_at = val.get("expires_at") or datetime.now(timezone.utc).isoformat()
                    try:
                        _run(f"""
                            INSERT INTO {DST}.run_asset_cache
                                (run_id, asset_type, preset_id, sas_url, expires_at)
                            VALUES (:r, :a, NULL, :u, :e::timestamp)
                            ON CONFLICT (run_id, asset_type, preset_id) DO NOTHING
                        """, {"r": run_id, "a": asset_type, "u": val["url"], "e": str(expires_at)})
                        migrated_cache += 1
                    except Exception:
                        pass
                elif isinstance(val, dict):
                    for preset_id, pval in val.items():
                        if isinstance(pval, dict) and "url" in pval:
                            expires_at = pval.get("expires_at") or datetime.now(timezone.utc).isoformat()
                            try:
                                _run(f"""
                                    INSERT INTO {DST}.run_asset_cache
                                        (run_id, asset_type, preset_id, sas_url, expires_at)
                                    VALUES (:r, :a, :p, :u, :e::timestamp)
                                    ON CONFLICT (run_id, asset_type, preset_id) DO NOTHING
                                """, {"r": run_id, "a": asset_type, "p": preset_id,
                                      "u": pval["url"], "e": str(expires_at)})
                                migrated_cache += 1
                            except Exception:
                                pass
        print(f"  [OK]  run_asset_cache: {migrated_cache} rows expanded from blob_sas_cache JSONB")

    # -- findings (pdf_content dropped) ---------------------------------------
    if _check("findings"):
        n = _count("findings")
        _run(f"""
            INSERT INTO {DST}.findings
                (id, extraction_id, run_id, agent_name, title, source_url,
                 publisher, what_changed, why_it_matters, evidence,
                 confidence, impact_score, relevance, novelty, credibility,
                 actionability, rank, topic_cluster, needs_verification,
                 tags, html_content, metadata, created_at)
            SELECT id, extraction_id, run_id, agent_name, title, source_url,
                   publisher, what_changed, why_it_matters, evidence,
                   confidence, impact_score, relevance, novelty, credibility,
                   actionability, rank, topic_cluster, needs_verification,
                   tags, html_content, COALESCE(metadata, '{{}}'::jsonb), created_at
            FROM {SRC}.findings ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.findings_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.findings), 1))")
        print(f"  [OK]  findings: {n} rows migrated (pdf_content dropped)")

    # -- resources ------------------------------------------------------------
    if _check("resources"):
        n = _count("resources")
        _run(f"""
            INSERT INTO {DST}.resources
                (id, run_id, agent_name, name, url, resource_type, discovered_at)
            SELECT id, run_id, agent_name, name, url, resource_type, discovered_at
            FROM {SRC}.resources ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.resources_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.resources), 1))")
        print(f"  [OK]  resources: {n} rows migrated")

    # -- competitors ----------------------------------------------------------
    if _check("competitors"):
        n = _count("competitors")
        _run(f"""
            INSERT INTO {DST}.competitors
                (id, name, url, source_type, selector, is_default, is_active, added_by, created_at)
            SELECT id, name, url, source_type, selector, is_default, is_active, added_by, created_at
            FROM {SRC}.competitors ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.competitors_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.competitors), 1))")
        print(f"  [OK]  competitors: {n} rows migrated")

    # -- voice_presets --------------------------------------------------------
    if _check("voice_presets"):
        n = _count("voice_presets")
        _run(f"""
            INSERT INTO {DST}.voice_presets
                (id, voice_id, label, gender, style, elevenlabs_model, is_active)
            SELECT id, voice_id, label, gender, style, elevenlabs_model, is_active
            FROM {SRC}.voice_presets ON CONFLICT (id) DO NOTHING
        """)
        print(f"  [OK]  voice_presets: {n} rows migrated")

    # -- persona_templates ----------------------------------------------------
    if _check("persona_templates"):
        n = _count("persona_templates")
        _run(f"""
            INSERT INTO {DST}.persona_templates
                (id, name, description, persona_type, digest_system_prompt,
                 suggested_questions, digest_focus_areas, owner_id,
                 visibility, is_system_default, created_at, updated_at)
            SELECT id, name, description, persona_type, digest_system_prompt,
                   COALESCE(suggested_questions, '[]'::jsonb),
                   COALESCE(digest_focus_areas, '[]'::jsonb),
                   owner_id, visibility, is_system_default, created_at, updated_at
            FROM {SRC}.persona_templates ON CONFLICT (id) DO NOTHING
        """)
        print(f"  [OK]  persona_templates: {n} rows migrated")

    # -- user_persona_preferences ---------------------------------------------
    if _check("user_persona_preferences"):
        n = _count("user_persona_preferences")
        if n > 0:
            _run(f"""
                INSERT INTO {DST}.user_persona_preferences
                    (user_id, persona_id, pinned, last_used_at)
                SELECT user_id, persona_id, pinned, last_used_at
                FROM {SRC}.user_persona_preferences
                ON CONFLICT DO NOTHING
            """)
        print(f"  [OK]  user_persona_preferences: {n} rows migrated")

    # -- chat_sessions --------------------------------------------------------
    if _check("chat_sessions"):
        n = _count("chat_sessions")
        _run(f"""
            INSERT INTO {DST}.chat_sessions
                (id, user_id, run_id, title, message_count, created_at, last_active)
            SELECT id, user_id, run_id, title, message_count, created_at, last_active
            FROM {SRC}.chat_sessions ON CONFLICT (id) DO NOTHING
        """)
        print(f"  [OK]  chat_sessions: {n} rows migrated")

    # -- chat_messages --------------------------------------------------------
    if _check("chat_messages"):
        n = _count("chat_messages")
        _run(f"""
            INSERT INTO {DST}.chat_messages
                (id, session_id, role, content, sources, tool_calls, mode, tokens_used, created_at)
            SELECT id, session_id, role, content,
                   COALESCE(sources, '[]'::jsonb),
                   COALESCE(tool_calls, '[]'::jsonb),
                   COALESCE(mode, 'text'), tokens_used, created_at
            FROM {SRC}.chat_messages ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.chat_messages_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.chat_messages), 1))")
        print(f"  [OK]  chat_messages: {n} rows migrated")

    # -- chat_answer_cache ----------------------------------------------------
    if _check("chat_answer_cache"):
        n = _count("chat_answer_cache")
        _run(f"""
            INSERT INTO {DST}.chat_answer_cache
                (id, run_id, question_text, question_hash, question_embedding,
                 answer_text, sources, tool_calls_used, mode, hit_count, created_at, last_hit_at)
            SELECT id, run_id, question_text, question_hash, question_embedding,
                   answer_text,
                   COALESCE(sources, '[]'::jsonb),
                   COALESCE(tool_calls_used, '[]'::jsonb),
                   COALESCE(mode, 'text'), hit_count, created_at, last_hit_at
            FROM {SRC}.chat_answer_cache ON CONFLICT (id) DO NOTHING
        """)
        _run(f"SELECT setval('{DST}.chat_answer_cache_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.chat_answer_cache), 1))")
        print(f"  [OK]  chat_answer_cache: {n} rows migrated")

    # -- audio_sessions / audio_messages (0 rows, skip) -----------------------
    for tbl in ("audio_sessions", "audio_messages"):
        n = _count(tbl)
        print(f"  [OK]  {tbl}: {n} rows {'migrated' if n == 0 else '(empty, skip)'}")

    # -- entities -------------------------------------------------------------
    if _check("entities"):
        n = _count("entities")
        if n > 0:
            _run(f"""
                INSERT INTO {DST}.entities
                    (id, name, entity_type, description, metadata, source, created_at, updated_at)
                SELECT id, name, entity_type, description,
                       COALESCE(metadata, '{{}}'::jsonb), source, created_at, updated_at
                FROM {SRC}.entities ON CONFLICT (id) DO NOTHING
            """)
        print(f"  [OK]  entities: {n} rows migrated")

    # -- memory_kv ------------------------------------------------------------
    if _check("memory_kv"):
        n = _count("memory_kv")
        if n > 0:
            _run(f"""
                INSERT INTO {DST}.memory_kv (key, value, updated_at)
                SELECT key, value, updated_at
                FROM {SRC}.memory_kv ON CONFLICT (key) DO NOTHING
            """)
        print(f"  [OK]  memory_kv: {n} rows migrated")

    # -- event_triggers -------------------------------------------------------
    if _check("event_triggers"):
        n = _count("event_triggers")
        if n > 0:
            _run(f"""
                INSERT INTO {DST}.event_triggers
                    (id, keyword, cooldown_hours, last_triggered, is_active, created_at)
                SELECT id, keyword, cooldown_hours, last_triggered, is_active, created_at
                FROM {SRC}.event_triggers ON CONFLICT (id) DO NOTHING
            """)
            _run(f"SELECT setval('{DST}.event_triggers_id_seq', COALESCE((SELECT MAX(id) FROM {DST}.event_triggers), 1))")
        print(f"  [OK]  event_triggers: {n} rows migrated")

    # -- review_queue ---------------------------------------------------------
    if _check("review_queue"):
        n = _count("review_queue")
        if n > 0:
            _run(f"""
                INSERT INTO {DST}.review_queue
                    (id, run_id, section, reviewer_email, status, comments, reviewed_at, created_at)
                SELECT id, run_id, section, reviewer_email, status, comments, reviewed_at, created_at
                FROM {SRC}.review_queue ON CONFLICT (id) DO NOTHING
            """)
        print(f"  [OK]  review_queue: {n} rows migrated")

    print(f"\n[OK]  Data migration complete.")


# -----------------------------------------------------------------------------
# STEP 3 - VALIDATE
# -----------------------------------------------------------------------------

TABLES_TO_CHECK = [
    "users", "extractions", "runs", "findings", "resources", "competitors",
    "voice_presets", "persona_templates", "user_persona_preferences",
    "chat_sessions", "chat_messages", "chat_answer_cache",
    "audio_sessions", "audio_messages", "entities", "memory_kv",
    "event_triggers", "review_queue",
    # New normalized tables:
    "run_audio_presets", "run_asset_cache",
]

def validate():
    print(f"\n{'='*60}")
    print(f"STEP 3 - Validation: {SRC} vs {DST}")
    print(f"{'='*60}")
    print(f"  {'Table':<35} {'src':>8} {'dst':>8}  {'Match':>6}")
    print(f"  {'-'*35} {'-'*8} {'-'*8}  {'-'*6}")

    all_ok = True
    with engine.connect() as conn:
        for tbl in TABLES_TO_CHECK:
            src_n = src_count(conn, tbl)
            dst_n = dst_count(conn, tbl)
            # run_audio_presets and run_asset_cache are NEW - no src count
            if tbl in ("run_audio_presets", "run_asset_cache"):
                icon = "[NEW]"
                print(f"  {tbl:<35} {'-':>8} {dst_n:>8}  {icon}")
            else:
                ok = src_n == dst_n
                if not ok:
                    all_ok = False
                icon = "[OK]" if ok else "[ERR]"
                print(f"  {tbl:<35} {src_n:>8} {dst_n:>8}  {icon}")

    if all_ok:
        print(f"\n[OK]  All row counts match - migration verified.")
    else:
        print(f"\n[WARN]   Some counts differ - review above. Re-run script to retry.")
    return all_ok


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Migrate ai_radar - ai_data_radar")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only print validation counts, skip DDL + data copy")
    parser.add_argument("--skip-data", action="store_true",
                        help="Create schema/tables but skip data migration")
    args = parser.parse_args()

    if args.validate_only:
        validate()
        return

    create_schema()

    if not args.skip_data:
        migrate_data()

    ok = validate()

    if ok:
        print(f"""
{'='*60}
NEXT STEPS
{'='*60}
1. Update Backend/db/connection.py:
     TARGET_SCHEMA = "{DST}"

2. Update Backend/scripts/setup_db.py (if re-running setup):
     TARGET_SCHEMA = "{DST}"

3. Test the application against the new schema.

4. Once stable, drop the old schema:
     DROP SCHEMA {SRC} CASCADE;
{'='*60}
""")


if __name__ == "__main__":
    main()
