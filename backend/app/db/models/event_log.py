from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventLog(Base):
    """Immutable outbox event log. No deleted_at — audit record."""
    __tablename__ = "event_log"

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_event_log_published_at_created_at", "published_at", "created_at"),
    )
