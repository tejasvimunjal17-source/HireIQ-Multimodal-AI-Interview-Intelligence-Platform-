from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.interview_session import InterviewSession


class Candidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Minimal personal data only: name + email (+ consent time). Nothing else is stored."""

    __tablename__ = "candidates"

    full_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False, unique=True, index=True)
    consent_given_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["InterviewSession"]] = relationship(
        "InterviewSession", back_populates="candidate", cascade="all, delete-orphan"
    )
