"""
Database and authentication dependencies for FastAPI routes.

- get_db: Yields a SQLAlchemy session bound to the configured engine.
- get_current_user: JWT-based authentication dependency (delegates to auth.get_current_user).

Configuration is sourced from environment variables (loaded via python-dotenv in app startup):
- DATABASE_URL: SQLAlchemy URL for the database (e.g. postgresql+psycopg2://user:pass@host:5432/dbname)

Notes:
- Do NOT hardcode secrets. Ensure .env contains DATABASE_URL and JWT settings (managed elsewhere).
"""

from __future__ import annotations

import os
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# PUBLIC_INTERFACE
def get_database_url() -> str:
    """Return the SQLAlchemy database URL from environment variables."""
    # This relies on dotenv being loaded by the FastAPI app startup (see main.py).
    url = os.getenv("DATABASE_URL", "")
    if not url:
        # For safety in local dev, allow empty; callers may handle missing DB.
        # In production this should be set via environment.
        return ""
    return url


# Configure SQLAlchemy engine and SessionLocal lazily to avoid import issues on app startup
_ENGINE = None
_SessionLocal: Optional[sessionmaker] = None


def _ensure_engine_and_session() -> None:
    """Create global engine and SessionLocal singleton if not already created."""
    global _ENGINE, _SessionLocal
    if _ENGINE is not None and _SessionLocal is not None:
        return

    database_url = get_database_url()
    if not database_url:
        # Create a dummy in-memory SQLite engine if no DB is configured,
        # allowing the app to start and expose diagnostics endpoints.
        # This can be replaced once DATABASE_URL is provided.
        database_url = "sqlite+pysqlite:///:memory:"

    # The pool_pre_ping helps drop broken connections gracefully.
    _ENGINE = create_engine(database_url, pool_pre_ping=True)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_ENGINE)


# PUBLIC_INTERFACE
def get_db() -> Generator[Session, None, None]:
    """Yield a database session for request handling and ensure proper cleanup."""
    _ensure_engine_and_session()
    assert _SessionLocal is not None  # For type checkers
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# PUBLIC_INTERFACE
def get_current_user():
    """
    Authentication dependency that validates a JWT Bearer token and returns the current user.

    This delegates to src.api.auth.get_current_user to keep a single source of truth.
    """
    from .auth import get_current_user as _get_current_user  # lazy import to avoid cycles
    return _get_current_user
