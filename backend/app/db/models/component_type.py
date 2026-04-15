from sqlalchemy import String, Text, JSON, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from datetime import datetime

from app.db.base import Base


class ComponentTypeDefinition(Base):
    """Tenant-scoped component type definition with custom field schema."""

    __tablename__ = "component_type_definition"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # optional ComponentType enum value
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    field_definitions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ComponentTypeDefinition(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"
