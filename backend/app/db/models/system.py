import enum

from sqlalchemy import String, Text, JSON, ForeignKey, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from datetime import datetime

from app.db.base import Base

class ComponentType(str, enum.Enum):
    WEB_SERVICE = 'web_service'
    API_GATEWAY = 'api_gateway'
    DATABASE = 'database'
    CACHE = 'cache'
    MESSAGE_QUEUE = 'message_queue'
    WORKER = 'worker'
    FRONTEND = 'frontend'
    OTHER = 'other'


class SubSystemSource(str, enum.Enum):
    """Where a subsystem row came from.

    `terraform` is a .tfstate upload and `terraform_hcl` is .tf source read
    from a repository. They are separate values on purpose: the two formats do
    not produce identical rows (HCL has no computed values or resource ids), so
    a drift report must never compare one against the other.
    """

    MANUAL = "manual"
    TERRAFORM = "terraform"
    TERRAFORM_HCL = "terraform_hcl"
    DOCKER_COMPOSE = "docker_compose"


class System(Base):
    """System model — a logical grouping of subsystems within a tenant."""

    __tablename__ = "system"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    github_repository_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    subsystems: Mapped[list["SubSystem"]] = relationship(
        "SubSystem", back_populates="system", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<System(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class SubSystem(Base):
    """SubSystem model — a component within a System."""

    __tablename__ = "subsystem"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    component_type: Mapped[ComponentType] = mapped_column(
        SAEnum(ComponentType, native_enum=False, values_callable=lambda obj: [e.value for e in obj], name="componenttype"),
        nullable=False,
        default=ComponentType.OTHER,
        server_default=ComponentType.OTHER.value,
    )
    technology: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[SubSystemSource] = mapped_column(
        SAEnum(
            SubSystemSource,
            native_enum=False,
            values_callable=lambda obj: [e.value for e in obj],
            name="subsystemsource",
        ),
        nullable=False,
        default=SubSystemSource.MANUAL,
        server_default=SubSystemSource.MANUAL.value,
    )
    #: Repository path that declared this subsystem, when it came from a scan.
    source_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    system: Mapped["System"] = relationship("System", back_populates="subsystems")

    def __repr__(self) -> str:
        return f"<SubSystem(id={self.id}, name='{self.name}', system_id={self.system_id})>"
