import enum
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DependencyType(str, enum.Enum):
    API_CALL = "api_call"
    DATABASE = "database"
    MESSAGE_QUEUE = "message_queue"
    EVENT = "event"
    FILE = "file"
    OTHER = "other"


class DependencySource(str, enum.Enum):
    MANUAL = "manual"
    TERRAFORM = "terraform"
    DOCKER_COMPOSE = "docker_compose"


class SystemDependency(Base):
    """A declared dependency between two Systems within a tenant."""

    __tablename__ = "system_dependency"

    from_system_id: Mapped[int] = mapped_column(
        ForeignKey("system.id"), nullable=False, index=True
    )
    to_system_id: Mapped[int] = mapped_column(
        ForeignKey("system.id"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        SAEnum(DependencyType, native_enum=False), nullable=False
    )
    source: Mapped[DependencySource] = mapped_column(
        SAEnum(DependencySource, native_enum=False),
        nullable=False,
        default=DependencySource.MANUAL,
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("from_system_id", "to_system_id", "tenant_id", name="uq_system_dep"),
    )

    from_system: Mapped["System"] = relationship(  # type: ignore[name-defined]
        "System", foreign_keys=[from_system_id]
    )
    to_system: Mapped["System"] = relationship(  # type: ignore[name-defined]
        "System", foreign_keys=[to_system_id]
    )

    def __repr__(self) -> str:
        return (
            f"<SystemDependency(from={self.from_system_id}, to={self.to_system_id}, "
            f"type={self.dependency_type})>"
        )


class ComponentDependency(Base):
    """A declared dependency between two SubSystems within a tenant."""

    __tablename__ = "component_dependency"

    from_subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    to_subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        SAEnum(DependencyType, native_enum=False), nullable=False
    )
    protocol: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[DependencySource] = mapped_column(
        SAEnum(DependencySource, native_enum=False),
        nullable=False,
        default=DependencySource.MANUAL,
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "from_subsystem_id", "to_subsystem_id", "tenant_id", name="uq_component_dep"
        ),
    )

    from_subsystem: Mapped["SubSystem"] = relationship(  # type: ignore[name-defined]
        "SubSystem", foreign_keys=[from_subsystem_id]
    )
    to_subsystem: Mapped["SubSystem"] = relationship(  # type: ignore[name-defined]
        "SubSystem", foreign_keys=[to_subsystem_id]
    )

    def __repr__(self) -> str:
        return (
            f"<ComponentDependency(from={self.from_subsystem_id}, to={self.to_subsystem_id}, "
            f"type={self.dependency_type})>"
        )
