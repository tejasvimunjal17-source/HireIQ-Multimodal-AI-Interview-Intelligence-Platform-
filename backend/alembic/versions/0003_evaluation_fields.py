"""Add LLM evaluation columns (Day 4, Phase 3)

Revision ID: 0003_evaluation_fields
Revises: 0002_transcription_fields

Only ADDS columns (nullable or with defaults); 0001 and 0002 are untouched and existing rows are kept.
- evaluations.recommendation / evaluations.evaluation_details: the validated recommendation and the other
  validated parts of the model output (strengths, improvements, holistic score, versions).
- candidate_responses.evaluation_*: the claim (task id), attempt counter, status and failure code of the
  evaluation, mirroring the transcription bookkeeping.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_evaluation_fields"
down_revision: Union[str, None] = "0002_transcription_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column(
        "recommendation", sa.Enum("proceed", "hold", "reject", native_enum=False, length=20), nullable=True))
    op.add_column("evaluations", sa.Column("evaluation_details", sa.JSON(), nullable=True))
    op.add_column("candidate_responses", sa.Column(
        "evaluation_status",
        sa.Enum("pending", "processing", "completed", "failed", "skipped", native_enum=False, length=20),
        server_default="pending", nullable=False))
    op.add_column("candidate_responses", sa.Column("evaluation_task_id", sa.String(length=155), nullable=True))
    op.add_column("candidate_responses", sa.Column("evaluation_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("candidate_responses", sa.Column("evaluation_error", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("candidate_responses") as batch:
        batch.drop_column("evaluation_error")
        batch.drop_column("evaluation_attempts")
        batch.drop_column("evaluation_task_id")
        batch.drop_column("evaluation_status")
    with op.batch_alter_table("evaluations") as batch:
        batch.drop_column("evaluation_details")
        batch.drop_column("recommendation")
