"""Add question-bank metadata to questions (Day 8)

Revision ID: 0004_question_bank_fields
Revises: 0003_evaluation_fields

Only ADDS three nullable columns; 0001-0003 are untouched and existing questions keep working (NULL = not set).
- questions.category: short slug used to group questions (e.g. "databases").
- questions.difficulty: easy | medium | hard.
- questions.expected_skills: JSON list of skill names the answer is expected to show.
None of them is used for scoring; the rubric YAML stays the only source of scoring rules.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_question_bank_fields"
down_revision: Union[str, None] = "0003_evaluation_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("category", sa.String(length=50), nullable=True))
    op.add_column("questions", sa.Column(
        "difficulty", sa.Enum("easy", "medium", "hard", native_enum=False, length=20), nullable=True))
    op.add_column("questions", sa.Column("expected_skills", sa.JSON(), nullable=True))
    op.create_index(op.f("ix_questions_category"), "questions", ["category"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_questions_category"), table_name="questions")
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("expected_skills")
        batch.drop_column("difficulty")
        batch.drop_column("category")
