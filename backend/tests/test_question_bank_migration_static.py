"""Day 8: STATIC checks of migration 0004 and the Question model (text only; needs no alembic or database).
The real upgrade/downgrade test lives in test_migrations.py and needs the project dependencies."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "alembic" / "versions" / "0004_question_bank_fields.py").read_text(encoding="utf-8")
MODEL = (ROOT / "app" / "models" / "question.py").read_text(encoding="utf-8")


def test_chain_and_file_names():
    assert re.search(r'^revision: str = "0004_question_bank_fields"$', MIGRATION, re.M)
    assert re.search(r'^down_revision: Union\[str, None\] = "0003_evaluation_fields"$', MIGRATION, re.M)
    names = sorted(p.name for p in (ROOT / "alembic" / "versions").glob("*.py"))
    assert names == ["0001_initial_schema.py", "0002_transcription_fields.py", "0003_evaluation_fields.py", "0004_question_bank_fields.py"]


def test_migration_only_adds_nullable_columns_to_questions():
    added = re.findall(r'op\.add_column\("(\w+)", sa\.Column\(\s*"(\w+)"', MIGRATION)
    assert sorted(added) == [("questions", "category"), ("questions", "difficulty"), ("questions", "expected_skills")]
    upgrade = MIGRATION.split("def downgrade")[0]
    assert upgrade.count("nullable=True") == 3 and "nullable=False" not in upgrade
    assert "drop_" not in upgrade and "alter_column" not in upgrade


def test_every_new_column_exists_in_the_model_with_the_same_shape():
    assert re.search(r"category: Mapped\[str \| None\] = mapped_column\(sa\.String\(50\), nullable=True, index=True\)", MODEL)
    assert re.search(r"difficulty: Mapped\[Difficulty \| None\] = mapped_column\(enum_column\(Difficulty\), nullable=True\)", MODEL)
    assert re.search(r"expected_skills: Mapped\[list\[str\] \| None\] = mapped_column\(sa\.JSON, nullable=True\)", MODEL)
    assert 'sa.String(length=50)' in MIGRATION and '"easy", "medium", "hard", native_enum=False, length=20' in MIGRATION
    assert 'op.f("ix_questions_category")' in MIGRATION  # index=True on the model creates ix_questions_category


def test_downgrade_removes_exactly_what_upgrade_added():
    downgrade = MIGRATION.split("def downgrade")[1]
    for column in ("category", "difficulty", "expected_skills"):
        assert f'batch.drop_column("{column}")' in downgrade
    assert "drop_index" in downgrade


def test_enum_values_match_the_schema_literals():
    from app.schemas.question_bank import DifficultyName
    from typing import get_args
    enums = (ROOT / "app" / "models" / "enums.py").read_text(encoding="utf-8")
    block = enums.split("class Difficulty(StrEnum):")[1].split("class SessionStatus")[0]
    assert sorted(re.findall(r'= "(\w+)"', block)) == sorted(get_args(DifficultyName))
