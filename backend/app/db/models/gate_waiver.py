from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateWaiver(Base):
    """The record behind an overridden gate: reason, approver, expiry,
    remediation.

    Rows ACCUMULATE as history; the newest row (by id) is current, WHETHER
    LIVE OR EXPIRED — "current" is about recency, not state. Re-waiving after
    an expiry must not overwrite the previous approver and reason — destroying
    that history destroys the one thing a waiver exists to create.

    There is NO state column. Live-versus-expired is computed from expires_at
    through expiry_boundary, A4's and B5's shape: nothing to invalidate, no
    scheduler.
    """

    __tablename__ = "gate_waiver"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    gate_id: Mapped[int] = mapped_column(
        ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    # NULL means "no expiry" — a permanent waiver, which is legitimate and must
    # not be confused with an expired one.
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    remediation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
