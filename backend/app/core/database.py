"""Database engine and session management (SQLAlchemy 2.0).

The engine is created lazily, so importing this module never opens a connection.
"""

from collections.abc import Generator
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        # Fail fast instead of hanging when PostgreSQL is down.
        kwargs["connect_args"] = {"connect_timeout": 3}
    return sa.create_engine(url, **kwargs)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def dispose_engine() -> None:
    """Close pooled connections and forget the cached engine (shutdown / tests)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
