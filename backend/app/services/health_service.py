"""Real dependency checks. Each one opens an actual connection."""

import logging

import redis
import sqlalchemy as sa

from app.core.config import get_settings
from app.core.database import get_engine
from app.schemas.health import ServiceHealth

logger = logging.getLogger(__name__)


def check_database() -> ServiceHealth:
    try:
        with get_engine().connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure means "not healthy"
        # Log only the error class: messages can contain connection strings.
        logger.warning("Database health check failed: %s", type(exc).__name__)
        return ServiceHealth(
            status="unavailable", service="database", detail=f"Database unreachable ({type(exc).__name__})"
        )
    return ServiceHealth(status="ok", service="database")


def check_redis() -> ServiceHealth:
    client = None
    try:
        client = redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", type(exc).__name__)
        return ServiceHealth(
            status="unavailable", service="redis", detail=f"Redis unreachable ({type(exc).__name__})"
        )
    finally:
        if client is not None:
            client.close()
    return ServiceHealth(status="ok", service="redis")
