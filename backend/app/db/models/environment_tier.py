from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentTier(Base):
    """Tenant-scoped environment tier vocabulary.

    Shaped like ComponentTypeDefinition and BookingType, the two vocabularies
    this codebase already configures per tenant.

    `category` is a plain VARCHAR, not an SAEnum, on purpose: SAEnum stores the
    member *name*, which is why `environment.status` holds 'ACTIVE' rather than
    'active'. It maps a tenant's own tier name onto one of the standard tiers
    (dev, sit, uat, preprod, performance, training, production, other) and is
    NULL for a tier that matches none of them.
    """

    __tablename__ = "environment_tier"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentTier(id={self.id}, name='{self.name}', "
            f"tenant_id={self.tenant_id})>"
        )
