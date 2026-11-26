"""Add transcription bookkeeping columns to candidate_responses (Day 3)

Revision ID: 0002_transcription_fields
Revises: 0001_initial_schema

Only ADDS columns (all nullable or with defaults), so existing rows are kept unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_transcription_fields"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "candidate_responses"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("transcript_language", sa.String(length=16), nullable=True))
    op.add_column(TABLE, sa.Column("transcription_provider", sa.String(length=30), nullable=True))
    op.add_column(TABLE, sa.Column("transcription_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column(TABLE, sa.Column("transcription_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("transcription_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("no_speech_detected", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    # batch mode lets SQLite (used in tests) drop columns too; on PostgreSQL it is plain ALTER TABLE.
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("no_speech_detected")
        batch.drop_column("transcription_completed_at")
        batch.drop_column("transcription_started_at")
        batch.drop_column("transcription_attempts")
        batch.drop_column("transcription_provider")
        batch.drop_column("transcript_language")
