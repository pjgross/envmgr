import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum as SAEnum

from app.db.base import Base


class BookingType(str, enum.Enum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    booked_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    booking_type: Mapped[BookingType] = mapped_column(
        SAEnum(BookingType, native_enum=False), nullable=False
    )
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, native_enum=False),
        nullable=False,
        default=BookingStatus.PENDING,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    context_tag: Mapped[ContextTag] = mapped_column(
        SAEnum(ContextTag, native_enum=False),
        nullable=False,
        default=ContextTag.NONE,
    )
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    environment: Mapped["Environment"] = relationship("Environment")
    booker: Mapped["User"] = relationship("User", foreign_keys=[booked_by])
    occurrences: Mapped[list["Booking"]] = relationship(
        "Booking",
        foreign_keys=[recurrence_parent_id],
        primaryjoin="Booking.id == foreign(Booking.recurrence_parent_id)",
    )
