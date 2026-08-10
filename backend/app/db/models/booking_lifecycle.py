from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingType(Base):
    __tablename__ = "booking_type"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lifecycle_template_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    # The protection level a request inherits from this type. A tenant declares
    # once, in the vocabulary it already configures, that (say) release-cycle
    # bookings are protected and ad-hoc ones are not.
    default_protection_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="soft", default="soft"
    )
    # The preset duration for this type, in minutes — 240 for a half-day,
    # 20160 for a two-week sprint. NULLABLE, and null means "this type has no
    # preset": a legitimate state, not a missing value.
    #
    # A CONVENIENCE, NEVER A CONSTRAINT. Nothing server-side checks that a
    # booking's length matches it, so a tenant editing a preset does not
    # retroactively make live bookings wrong.
    default_duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lifecycle_template = relationship("LifecycleTemplate")


class BookingStatusHistory(Base):
    __tablename__ = "booking_status_history"

    booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    from_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    to_state: Mapped[str] = mapped_column(String(100), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # No deleted_at — history rows are immutable audit records
