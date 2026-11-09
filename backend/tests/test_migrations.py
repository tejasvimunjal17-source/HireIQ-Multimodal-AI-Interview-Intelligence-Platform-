"""Alembic migration tests on SQLite (stand-in). The same migration is run on REAL
PostgreSQL by test_integration_services.py when RUN_INTEGRATION=1."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.models.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = {
    "candidates", "interviews", "questions", "interview_sessions",
    "candidate_responses", "evaluations", "reports",
}


def alembic_config(connection=None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def test_there_is_exactly_one_migration_head():
    scripts = ScriptDirectory.from_config(alembic_config())
    assert scripts.get_heads() == ["0002_transcription_fields"]
    assert scripts.get_revision("0002_transcription_fields").down_revision == "0001_initial_schema"


def test_upgrade_creates_all_tables_and_matches_models(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    with engine.connect() as connection:
        assert TABLES <= set(sa.inspect(connection).get_table_names())
        context = MigrationContext.configure(connection, opts={"compare_type": False})
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert differences == [], f"Migration and models disagree: {differences}"


def test_downgrade_removes_all_tables(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'down.db'}")
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    with engine.connect() as connection:
        assert set(sa.inspect(connection).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_upgrading_from_day_2_keeps_existing_rows_and_fills_new_columns(tmp_path):
    """Create the Day 1/2 schema (revision 0001), insert data, upgrade to head, and check nothing changed."""
    import uuid

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    ids = {name: uuid.uuid4().hex for name in ("cand", "int", "q", "sess", "resp")}
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0001_initial_schema")
        run = connection.execute
        run(sa.text("INSERT INTO candidates (id, full_name, email) VALUES (:cand, 'A', 'a@example.com')"), ids)
        run(sa.text("INSERT INTO interviews (id, title, interview_type, rubric_name) VALUES (:int, 'T', 'mixed', 'r')"), ids)
        run(sa.text("INSERT INTO questions (id, interview_id, position, text, question_type) "
                    "VALUES (:q, :int, 1, 'Q', 'technical')"), ids)
        run(sa.text("INSERT INTO interview_sessions (id, candidate_id, interview_id, status) "
                    "VALUES (:sess, :cand, :int, 'in_progress')"), ids)
        run(sa.text("INSERT INTO candidate_responses (id, session_id, question_id, transcription_status, celery_task_id) "
                    "VALUES (:resp, :sess, :q, 'pending', 'old-task')"), ids)
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    with engine.connect() as connection:
        row = connection.execute(sa.text(
            "SELECT transcription_status, celery_task_id, transcription_attempts, no_speech_detected, "
            "transcript_language, transcription_provider FROM candidate_responses")).one()
        assert tuple(row) == ("pending", "old-task", 0, 0, None, None)
        assert connection.execute(sa.text("SELECT count(*) FROM candidates")).scalar() == 1
        context = MigrationContext.configure(connection, opts={"compare_type": False})
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()
