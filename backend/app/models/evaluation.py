import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Recommendation, enum_column

if TYPE_CHECKING:
    from app.models.candidate_response import CandidateResponse


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Validated LLM evaluation of ONE response.

    Rule: a row is only ever written AFTER the LLM output passed Pydantic validation
    (Day 4). That is why score/criteria/explanation are NOT NULL.
    """

    __tablename__ = "evaluations"
    __table_args__ = (sa.CheckConstraint("overall_score >= 0 AND overall_score <= 100", name="score_range"),)

    response_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("candidate_responses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    overall_score: Mapped[float] = mapped_column(sa.Float, nullable=False)  # normalized 0-100
    criteria_scores: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # spaCy / VADER / confidence heuristics (Day 5).
    nlp_enrichment: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    llm_provider: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    rubric_name: Mapped[str] = mapped_column(sa.String(100), nullable=False)

    # --- Day 4 Phase 3 (migration 0003): advice for a human on THIS answer, validated by the schema. ---
    recommendation: Mapped[Recommendation | None] = mapped_column(enum_column(Recommendation), nullable=True)
    # strengths, areas_for_improvement, the model's own holistic score, rubric key/version, prompt version.
    evaluation_details: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    response: Mapped["CandidateResponse"] = relationship("CandidateResponse", back_populates="evaluation")
