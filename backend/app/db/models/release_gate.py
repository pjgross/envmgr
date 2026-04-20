from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseGate(Base):
    __tablename__ = "release_gate"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("test_phase.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
