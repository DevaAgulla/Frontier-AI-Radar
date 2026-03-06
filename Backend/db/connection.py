"""
SQLite database connection layer for Frontier AI Radar.

Usage:
    from db.connection import get_session, init_db

    # Call once at app startup (creates tables if they don't exist)
    init_db()

    # Use sessions for queries
    with get_session() as session:
        session.add(Extraction(...))
        session.commit()
"""

from pathlib import Path
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
import structlog

from db.models import Base

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Engine & session factory (lazy-initialised on first call to init_db)
# ---------------------------------------------------------------------------
_engine = None
_SessionFactory = None


def _get_database_url() -> str:
    """Resolve the DATABASE_URL from settings."""
    from config.settings import settings
    return settings.database_url


def _enable_sqlite_fk(dbapi_conn, connection_record):
    """Enable foreign-key enforcement for every SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def init_db() -> None:
    """
    Initialise the SQLite database.

    - Creates the ``db/`` directory if it doesn't exist.
    - Creates the ``.db`` file and all tables on first run.
    - Safe to call multiple times (uses ``CREATE TABLE IF NOT EXISTS``).
    """
    global _engine, _SessionFactory

    db_url = _get_database_url()

    # Ensure the directory for the .db file exists
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        db_url,
        echo=False,                 # set True for SQL debug logging
        connect_args={"check_same_thread": False},  # needed for SQLite + threads
    )

    # Turn on foreign-key support for every connection
    event.listen(_engine, "connect", _enable_sqlite_fk)

    # Create all tables (no-op if they already exist)
    Base.metadata.create_all(_engine)

    _SessionFactory = sessionmaker(bind=_engine)

    # Seed default competitor sources (idempotent — skips if table already has rows)
    from db.persist import seed_default_competitors
    seed_default_competitors()

    logger.info("Database initialised", url=db_url)


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
    """Return the current SQLAlchemy engine (init if needed)."""
    if _engine is None:
        init_db()
    return _engine
