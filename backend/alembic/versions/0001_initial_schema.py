"""Initial schema: candidates, interviews, questions, sessions, responses, evaluations, reports

Revision ID: 0001_initial_schema
Revises:
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(*values: str) -> sa.Enum:
    return sa.Enum(*values, native_enum=False, length=20)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidates")),
    )
    op.create_index(op.f("ix_candidates_email"), "candidates", ["email"], unique=True)

    op.create_table(
        "interviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("interview_type", _enum("technical", "behavioral", "mixed"), nullable=False),
        sa.Column("rubric_name", sa.String(length=100), nullable=False),
        sa.Column("total_time_limit_seconds", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interviews")),
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("question_type", _enum("technical", "behavioral"), nullable=False),
        sa.Column("rubric_key", sa.String(length=100), nullable=True),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["interview_id"], ["interviews.id"],
            name=op.f("fk_questions_interview_id_interviews"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
        sa.UniqueConstraint("interview_id", "position", name=op.f("uq_questions_interview_id_position")),
    )
    op.create_index(op.f("ix_questions_interview_id"), "questions", ["interview_id"], unique=False)

    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            _enum("created", "in_progress", "submitted", "processing", "evaluated", "failed"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"],
            name=op.f("fk_interview_sessions_candidate_id_candidates"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interview_id"], ["interviews.id"],
            name=op.f("fk_interview_sessions_interview_id_interviews"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_sessions")),
        sa.UniqueConstraint(
            "candidate_id", "interview_id", name=op.f("uq_interview_sessions_candidate_id_interview_id")
        ),
    )
    op.create_index(op.f("ix_interview_sessions_candidate_id"), "interview_sessions", ["candidate_id"], unique=False)
    op.create_index(op.f("ix_interview_sessions_interview_id"), "interview_sessions", ["interview_id"], unique=False)
    op.create_index(op.f("ix_interview_sessions_status"), "interview_sessions", ["status"], unique=False)

    op.create_table(
        "candidate_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("transcription_status", _enum("pending", "processing", "completed", "failed"), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_segments", sa.JSON(), nullable=True),
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
        sa.Column("transcription_error", sa.String(length=500), nullable=True),
        sa.Column("celery_task_id", sa.String(length=155), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"],
            name=op.f("fk_candidate_responses_session_id_interview_sessions"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"],
            name=op.f("fk_candidate_responses_question_id_questions"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_responses")),
        sa.UniqueConstraint("session_id", "question_id", name=op.f("uq_candidate_responses_session_id_question_id")),
    )
    op.create_index(op.f("ix_candidate_responses_session_id"), "candidate_responses", ["session_id"], unique=False)
    op.create_index(op.f("ix_candidate_responses_question_id"), "candidate_responses", ["question_id"], unique=False)
    op.create_index(
        op.f("ix_candidate_responses_transcription_status"),
        "candidate_responses", ["transcription_status"], unique=False,
    )

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("response_id", sa.Uuid(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("criteria_scores", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("nlp_enrichment", sa.JSON(), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=False),
        sa.Column("rubric_name", sa.String(length=100), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("overall_score >= 0 AND overall_score <= 100", name=op.f("ck_evaluations_score_range")),
        sa.ForeignKeyConstraint(
            ["response_id"], ["candidate_responses.id"],
            name=op.f("fk_evaluations_response_id_candidate_responses"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluations")),
    )
    op.create_index(op.f("ix_evaluations_response_id"), "evaluations", ["response_id"], unique=True)

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("recommendation", _enum("proceed", "hold", "reject"), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("overall_score >= 0 AND overall_score <= 100", name=op.f("ck_reports_score_range")),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"],
            name=op.f("fk_reports_session_id_interview_sessions"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_session_id"), "reports", ["session_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_reports_session_id"), table_name="reports")
    op.drop_table("reports")
    op.drop_index(op.f("ix_evaluations_response_id"), table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index(op.f("ix_candidate_responses_transcription_status"), table_name="candidate_responses")
    op.drop_index(op.f("ix_candidate_responses_question_id"), table_name="candidate_responses")
    op.drop_index(op.f("ix_candidate_responses_session_id"), table_name="candidate_responses")
    op.drop_table("candidate_responses")
    op.drop_index(op.f("ix_interview_sessions_status"), table_name="interview_sessions")
    op.drop_index(op.f("ix_interview_sessions_interview_id"), table_name="interview_sessions")
    op.drop_index(op.f("ix_interview_sessions_candidate_id"), table_name="interview_sessions")
    op.drop_table("interview_sessions")
    op.drop_index(op.f("ix_questions_interview_id"), table_name="questions")
    op.drop_table("questions")
    op.drop_table("interviews")
    op.drop_index(op.f("ix_candidates_email"), table_name="candidates")
    op.drop_table("candidates")
