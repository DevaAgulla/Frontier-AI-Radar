"""
PostgreSQL database connection layer for Frontier AI Radar.

Schema: ai_radar
Tables are created by scripts/setup_db.py — this module only connects.

Usage:
    from db.connection import get_session, init_db

    init_db()  # call once at startup (no-op if already initialised)

    with get_session() as session:
        session.add(obj)
        session.commit()
"""

from contextlib import contextmanager
from typing import Generator

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_SCHEMA = "ai_radar"

# ---------------------------------------------------------------------------
# Engine & session factory (lazy-initialised on first call to init_db)
# ---------------------------------------------------------------------------
_engine = None
_SessionFactory = None


def _get_database_url() -> str:
    """Resolve the DATABASE_URL from settings."""
    from config.settings import settings
    return settings.database_url


def init_db() -> None:
    """
    Initialise the PostgreSQL connection pool.

    - Connects to Azure PostgreSQL using DATABASE_URL from .env
    - Sets search_path to ai_radar so all queries resolve to the right schema
    - Tables are NOT created here — they are created by scripts/setup_db.py
    - Safe to call multiple times (no-op after first call)
    """
    global _engine, _SessionFactory

    if _engine is not None:
        return  # already initialised

    db_url = _get_database_url()

    # Normalise postgres:// → postgresql:// (some providers give the short form)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    is_azure = "postgres.database.azure.com" in db_url
    connect_args: dict = {}
    if is_azure:
        connect_args["sslmode"] = "require"

    # Force search_path so every session lands in ai_radar schema automatically
    connect_args["options"] = f"-c search_path={TARGET_SCHEMA},public"

    _engine = sa.create_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,   # validate connections before use
    )

    # Verify the connection works at startup
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("PostgreSQL connected", schema=TARGET_SCHEMA)
    except Exception as e:
        logger.error("PostgreSQL connection failed", error=str(e))
        raise

    _SessionFactory = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Provide a transactional database session as a context manager.

    Usage::

        with get_session() as session:
            session.add(obj)
            session.commit()
    """
    if _SessionFactory is None:
        init_db()

    session = _SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine():
    """Return the current SQLAlchemy engine (initialises if needed)."""
    if _engine is None:
        init_db()
    return _engine
