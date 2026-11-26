"""API tests using FastAPI's TestClient. Marked tests use test doubles."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.core.config import get_settings
from app.core.database import dispose_engine
from app.main import create_app, unhandled_exception_handler


def test_app_starts_and_lifespan_runs(client):
    assert isinstance(client.app, FastAPI)


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["docs_url"] == "/docs"
    assert body["environment"] == "test"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_swagger_ui_and_openapi_are_available(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for expected in ("/", "/health", "/health/db", "/health/redis"):
        assert expected in paths


def test_unknown_route_returns_json_404(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_health_db_ok_with_reachable_sqlite_standin(monkeypatch, tmp_path):
    """Real SQLAlchemy connection to a SQLite file (stand-in for PostgreSQL)."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ok.db'}")
    get_settings.cache_clear()
    dispose_engine()
    with TestClient(create_app()) as client:
        response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "database", "detail": None}


def test_health_db_reports_503_when_database_unreachable(monkeypatch, tmp_path):
    """A DB that cannot be opened must NOT be reported as healthy."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'missing_dir' / 'x.db'}")
    get_settings.cache_clear()
    dispose_engine()
    with TestClient(create_app()) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert str(tmp_path) not in str(body)  # no path / credentials leaked


def test_health_redis_reports_503_when_redis_unreachable(monkeypatch):
    """Real connection attempt to a closed port (127.0.0.1:1)."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.get("/health/redis")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


@pytest.mark.mocked
def test_health_redis_ok_with_fake_redis_client(monkeypatch, client):
    """MOCKED: a fake Redis client proves the ok-path logic only, not a real Redis."""

    class FakeRedis:
        def ping(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr("app.services.health_service.redis.Redis.from_url", lambda *a, **k: FakeRedis())
    response = client.get("/health/redis")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unhandled_exception_returns_safe_500():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "secret" not in response.text
    assert callable(unhandled_exception_handler)


def test_cors_allows_configured_origin_only(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://allowed.example")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        headers = {"Access-Control-Request-Method": "GET"}
        allowed = client.options("/health", headers={**headers, "Origin": "http://allowed.example"})
        denied = client.options("/health", headers={**headers, "Origin": "http://evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "http://allowed.example"
    assert "access-control-allow-origin" not in denied.headers
