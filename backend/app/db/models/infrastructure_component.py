import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InfrastructureComponentType(str, enum.Enum):
    SERVER = "server"
    CONTAINER_RUNTIME = "container_runtime"
    KUBERNETES_CLUSTER = "kubernetes_cluster"
    MANAGED_DATABASE = "managed_database"
    LOAD_BALANCER = "load_balancer"
    NETWORK = "network"
    CDN = "cdn"
    QUEUE = "queue"
    CACHE = "cache"
    OTHER = "other"


class InfrastructureComponentSource(str, enum.Enum):
    MANUAL = "manual"
    TERRAFORM = "terraform"
    DOCKER_COMPOSE = "docker_compose"


class InfrastructureComponent(Base):
    """A deployment target — host, cluster, managed service, etc.

    Subsystems deployed into an environment reference one or more of these via
    the `environment_subsystem_host` junction. Change requests may also target
    one or more components directly for platform-level changes; the affected
    environments are then derived through the junction.

    The model is Phase 6-shaped (source / external_id / provider / region) so
    the later Terraform and Docker Compose parsers can populate rows without
    a schema change.
    """

    __tablename__ = "infrastructure_component"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    component_type: Mapped[InfrastructureComponentType] = mapped_column(
        SAEnum(
            InfrastructureComponentType,
            native_enum=False,
            values_callable=lambda obj: [e.value for e in obj],
            name="infrastructurecomponenttype",
        ),
        nullable=False,
        default=InfrastructureComponentType.OTHER,
    )
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source: Mapped[InfrastructureComponentSource] = mapped_column(
        SAEnum(
            InfrastructureComponentSource,
            native_enum=False,
            values_callable=lambda obj: [e.value for e in obj],
            name="infrastructurecomponentsource",
        ),
        nullable=False,
        default=InfrastructureComponentSource.MANUAL,
        server_default=InfrastructureComponentSource.MANUAL.value,
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_infra_component_tenant_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<InfrastructureComponent(id={self.id}, name='{self.name}', "
            f"type='{self.component_type}', tenant_id={self.tenant_id})>"
        )
