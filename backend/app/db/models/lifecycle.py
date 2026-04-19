from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LifecycleTemplate(Base):
    """Configurable state-machine template.

    Generic across entity types (booking, change_request, release, ...).
    State/transition/field-permission shape lives in the `definition` JSON blob;
    the service layer in app.services.lifecycle_service is the canonical
    interpreter.
    """

    __tablename__ = "lifecycle_template"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON for SQLite compat in tests; PostgreSQL migrations use JSONB DDL.
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_lifecycle_template_tenant_entity", "tenant_id", "entity_type"),
    )
