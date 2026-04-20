from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TestPhase(Base):
    __tablename__ = "test_phase"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
