from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateCriterion(Base):
    __tablename__ = "gate_criterion"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    gate_id: Mapped[int] = mapped_column(
        ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
