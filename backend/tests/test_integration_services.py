"""REAL-service tests. They need running PostgreSQL + Redis and are SKIPPED unless
RUN_INTEGRATION=1 (GitHub Actions CI sets it and provides both services)."""

import os

import pytest
import sqlalchemy as sa
from alembic import command

from app.services.health_service import check_database, check_redis
from app.workers.celery_app import celery_app
from tests.test_migrations import TABLES, alembic_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="needs real PostgreSQL + Redis; set RUN_INTEGRATION=1 to run",
    ),
]


def test_real_postgres_is_reachable():
    assert os.environ["DATABASE_URL"].startswith("postgresql")
    assert check_database().status == "ok"


def test_migration_upgrades_and_downgrades_on_real_postgres():
    engine = sa.create_engine(os.environ["DATABASE_URL"])
    try:
        command.upgrade(alembic_config(), "head")  # uses env.py's own connection (real URL)
        assert TABLES <= set(sa.inspect(engine).get_table_names())
        command.downgrade(alembic_config(), "base")
        assert not (TABLES & set(sa.inspect(engine).get_table_names()))
    finally:
        engine.dispose()


def test_real_redis_ping():
    assert check_redis().status == "ok"


def test_celery_can_connect_to_real_redis_broker():
    with celery_app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=1)
        assert connection.connected
