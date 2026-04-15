from datetime import datetime
from typing import Optional

from sqlalchemy import Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BookingConflictAck(Base):
    __tablename__ = "booking_conflict_ack"
    __table_args__ = (
        UniqueConstraint("booking_id", "other_booking_id", name="uq_conflict_ack_pair"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    other_booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    willing_to_share: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acknowledged_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
