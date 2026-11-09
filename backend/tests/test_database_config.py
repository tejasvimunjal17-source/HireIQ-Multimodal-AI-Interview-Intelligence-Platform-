"""Database connection configuration (no live PostgreSQL needed)."""

import sqlalchemy as sa

from app.core.config import get_settings
from app.core.database import dispose_engine, get_db, get_engine, get_session_factory


def test_engine_uses_database_url_from_settings(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'cfg.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    assert str(get_engine().url) == url


def test_postgres_url_builds_engine_with_psycopg_driver_without_connecting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@postgres:5432/hireiq")
    get_settings.cache_clear()
    engine = get_engine()  # creating an engine must NOT open a connection
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "postgres"
    assert engine.url.database == "hireiq"


def test_engine_and_session_factory_are_cached_until_disposed():
    assert get_engine() is get_engine()
    assert get_session_factory() is get_session_factory()
    first = get_engine()
    dispose_engine()
    assert get_engine() is not first


def test_get_db_yields_working_session_and_closes_it(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.db'}")
    get_settings.cache_clear()
    generator = get_db()
    session = next(generator)
    assert session.execute(sa.text("SELECT 1")).scalar() == 1
    generator.close()  # triggers the finally block (session.close)
