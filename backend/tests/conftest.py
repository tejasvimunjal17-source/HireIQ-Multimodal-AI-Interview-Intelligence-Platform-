"""Shared test setup.

Unit tests use SQLite (in memory / temp file) as a stand-in for PostgreSQL.
Tests that need REAL PostgreSQL + Redis live in test_integration_services.py
and only run when RUN_INTEGRATION=1.
"""

import os

# These must be set BEFORE the app is imported. setdefault keeps CI-provided values.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.database import dispose_engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.base import Base  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cached_state():
    """Settings and the DB engine are cached; reset them around every test."""
    get_settings.cache_clear()
    dispose_engine()
    yield
    get_settings.cache_clear()
    dispose_engine()


def _sqlite_engine(url: str = "sqlite://") -> sa.Engine:
    kwargs = {}
    if url == "sqlite://":
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    engine = sa.create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # SQLite ignores FKs unless asked
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture
def sqlite_engine():
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine):
    with Session(sqlite_engine) as session:
        yield session


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def audio_dir(tmp_path, monkeypatch):
    """A private temp folder for uploaded audio, created per test."""
    path = tmp_path / "audio"
    monkeypatch.setenv("AUDIO_TEMP_DIR", str(path))
    get_settings.cache_clear()
    return path


@pytest.fixture
def enqueued(monkeypatch):
    """Replaces the Celery send with a list, so API tests never need Redis. MOCKED broker."""
    calls: list[tuple] = []
    monkeypatch.setattr("app.services.transcription_dispatch._enqueue", lambda rid, tid: calls.append((rid, tid)))
    return calls


@pytest.fixture
def api_client(sqlite_engine, audio_dir, monkeypatch, enqueued):
    """TestClient whose database dependency points at the SQLite stand-in."""
    app = create_app()
    factory = sessionmaker(bind=sqlite_engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    # The transcription dispatcher opens its own session; point it at the same SQLite database.
    monkeypatch.setattr("app.services.transcription_dispatch.get_session_factory", lambda: factory)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(sqlite_engine):
    return sessionmaker(bind=sqlite_engine, autoflush=False, expire_on_commit=False)
