import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum as SAEnum

from app.db.base import Base


class ContextTag(str, enum.Enum):
    DEPLOYMENT = "deployment"
    REGRESSION = "regression"
    NONE = "none"


class Booking(Base):
    __tablename__ = "booking"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    environment_group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # no FK yet (Phase 7)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")
    recurrence_rule: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )  # RRULE on parent only
    recurrence_parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("booking.id", use_alter=True, name="fk_booking_parent"),
        nullable=True,
        index=True,
    )
    release_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # no FK yet (Phase 3)
    test_phase_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # no FK yet
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    booking_request_id: Mapped[int] = mapped_column(
        ForeignKey("booking_request.id"), nullable=False, index=True
    )

    # Relationships
    booking_request = relationship(
        "BookingRequest",
        back_populates="bookings",
        foreign_keys=[booking_request_id],
    )
    environment: Mapped["Environment"] = relationship("Environment")
    occurrences: Mapped[list["Booking"]] = relationship(
        "Booking",
        foreign_keys=[recurrence_parent_id],
        primaryjoin="Booking.id == foreign(Booking.recurrence_parent_id)",
    )
