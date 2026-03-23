# backend/app/db/models/custom_field.py
from sqlalchemy import String, Boolean, Integer, JSON, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from datetime import datetime

from app.db.base import Base


class CustomFieldDefinition(Base):
    """Tenant-scoped custom field schema for an entity type."""

    __tablename__ = "custom_field_definition"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # system, subsystem, environment, booking
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)   # snake_case JSON key; immutable after creation
    label: Mapped[str] = mapped_column(String(200), nullable=False)       # display name; editable
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)   # text, number, boolean; immutable after creation
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # reserved for future select types
    lifecycle_states: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # null = always visible
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "field_key", name="uq_custom_field_def"),
    )

    def __repr__(self) -> str:
        return f"<CustomFieldDefinition(id={self.id}, entity_type='{self.entity_type}', field_key='{self.field_key}')>"
