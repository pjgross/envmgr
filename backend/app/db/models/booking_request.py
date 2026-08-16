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
    # The project this booking belongs to. Nullable, and deliberately BESIDE
    # project_name rather than replacing it: in real data that field holds a
    # booking label ("Health Demo Booking", "Reserved check"), so promoting it
    # would manufacture projects nobody wants. The UI relabels it "Purpose".
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("project.id"), nullable=True, index=True
    )
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
    # How hard this claim is — see app/core/protection_levels.py. Values are
    # "soft" | "hard"; String, not a native enum, per the house rule.
    #
    # ON THE REQUEST, NOT THE BOOKING, and that is load-bearing. A2's group
    # bookings share ONE BookingRequest, and A4's argument that "group
    # reachability is exactly equal to individual reachability" depends on
    # `_record_values` being byte-identical across members. A per-booking
    # override would let one member of an atomic group be protected and another
    # not, which the group transition cannot express. Do not add one without
    # revisiting that argument.
    protection_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="soft", default="soft"
    )
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
