"""Alembic environment. Reads DATABASE_URL via app settings (never from alembic.ini)."""

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: sa.Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass an existing connection through config.attributes.
    existing = config.attributes.get("connection")
    if existing is not None:
        _run(existing)
        return
    engine = sa.create_engine(get_settings().database_url, poolclass=sa.pool.NullPool)
    with engine.connect() as connection:
        _run(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
