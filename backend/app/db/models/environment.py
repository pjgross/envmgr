import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EnvironmentStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


class EnvironmentSystemStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MOCK = "mock"


class Environment(Base):
    """Environment model — a named test environment within a tenant."""

    __tablename__ = "environment"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    environment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[EnvironmentStatus] = mapped_column(
        SAEnum(EnvironmentStatus, native_enum=False),
        nullable=False,
        default=EnvironmentStatus.ACTIVE,
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    environment_systems: Mapped[list["EnvironmentSystem"]] = relationship(
        "EnvironmentSystem", back_populates="environment", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Environment(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class EnvironmentSystem(Base):
    """Junction table linking an Environment to a System, with per-link metadata."""

    __tablename__ = "environment_system"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(
        ForeignKey("system.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    status: Mapped[EnvironmentSystemStatus] = mapped_column(
        SAEnum(EnvironmentSystemStatus, native_enum=False),
        nullable=False,
        default=EnvironmentSystemStatus.ACTIVE,
    )
    mock_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("environment_id", "system_id", name="uq_env_system"),
    )

    environment: Mapped["Environment"] = relationship(
        "Environment", back_populates="environment_systems"
    )
    system: Mapped["System"] = relationship("System")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<EnvironmentSystem(env={self.environment_id}, sys={self.system_id})>"
        )
