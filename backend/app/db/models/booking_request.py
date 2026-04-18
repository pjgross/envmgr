from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY

from app.db.base import Base
from app.db.models.booking import ContextTag


class BookingRequest(Base):
    __tablename__ = "booking_request"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    booking_type_id: Mapped[int] = mapped_column(
        ForeignKey("booking_type.id"), nullable=False, index=True
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_tag: Mapped[ContextTag] = mapped_column(
        SAEnum(ContextTag, native_enum=False),
        nullable=False,
        default=ContextTag.NONE,
    )
    exclusive_use_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    booked_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    # Stored as JSON array to keep SQLite (test) compatibility; Postgres accepts JSON too.
    delegate_user_ids: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    booking_type_ref = relationship("BookingType", foreign_keys=[booking_type_id])
    booker = relationship("User", foreign_keys=[booked_by])
    bookings = relationship(
        "Booking",
        back_populates="booking_request",
        foreign_keys="Booking.booking_request_id",
    )
