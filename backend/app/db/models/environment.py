import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, JSON, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.component_type import ComponentTypeDefinition


class EnvironmentStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


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
    """Junction table linking an Environment to a System."""

    __tablename__ = "environment_system"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(
        ForeignKey("system.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("environment_id", "system_id", name="uq_env_system"),
    )

    environment: Mapped["Environment"] = relationship(
        "Environment", back_populates="environment_systems"
    )
    system: Mapped["System"] = relationship("System")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f"<EnvironmentSystem(env={self.environment_id}, sys={self.system_id})>"


class EnvironmentSubSystem(Base):
    """Per-subsystem real/mocked configuration for an environment."""

    __tablename__ = "environment_subsystem"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    is_mocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mock_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    component_type_definition_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("component_type_definition.id"), nullable=True, index=True
    )
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    component_type_definition: Mapped[Optional["ComponentTypeDefinition"]] = relationship(
        "ComponentTypeDefinition", lazy="select"
    )

    __table_args__ = (
        UniqueConstraint("environment_id", "subsystem_id", name="uq_env_subsystem"),
    )

    subsystem: Mapped["SubSystem"] = relationship("SubSystem")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<EnvironmentSubSystem(env={self.environment_id}, sub={self.subsystem_id}, "
            f"mocked={self.is_mocked})>"
        )
