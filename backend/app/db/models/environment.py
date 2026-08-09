import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, JSON, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.component_type import ComponentTypeDefinition
    from app.db.models.infrastructure_component import InfrastructureComponent


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
    tier_id: Mapped[int] = mapped_column(
        ForeignKey("environment_tier.id"), nullable=False
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True
    )
    # Nullable so legacy rows stay honest rather than carrying a fabricated
    # owner/expiry; the API requires both going forward and the gap is
    # reportable via ?governance_gap=true.
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The team that operates this environment. Nullable everywhere: existing
    # rows keep a null rather than a fabricated group, and `?governance_gap=`
    # reports it. B3b is where the constraint lands — it refuses to *route* a
    # request for an environment with no operating team, which is where the
    # requirement actually matters.
    operations_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
    # Handover fields — the Welcome Pack's content, authored by the team that
    # operates this environment (see PATCH /environments/{id}/handover, which
    # is the ONLY write path for them; they are deliberately absent from
    # EnvironmentUpdate). All nullable: a newly created environment has nothing
    # to hand over until it has been built.
    #
    # Credentials are deliberately NOT here. This app has one secret store,
    # built for a single OAuth token. `connection_notes` says WHERE credentials
    # come from — a vault path, a team to ask — without this becoming the place
    # passwords live.
    access_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    connection_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    support_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sla_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    known_limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decommission_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[EnvironmentStatus] = mapped_column(
        SAEnum(EnvironmentStatus, native_enum=False),
        nullable=False,
        default=EnvironmentStatus.ACTIVE,
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # B2 — the stored verdict of the tenant's naming pattern. NULL means "no
    # pattern applies" (no policy, disabled, or a null pattern), NOT "unknown"
    # and NOT "failing": every clause and every cell treats null as compliant.
    #
    # Stored rather than computed because no regex is portable across both
    # engines, and every filter here must run in SQL. Its whole invalidation
    # surface is: create_environment_record, update_environment (name changed),
    # environment_request_service fulfilment, and a policy write. A future
    # write path that sets `name` without going through those produces a lying
    # verdict — see test_environment_compliance_write_paths.py.
    name_compliant: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Named explicitly. SQLAlchemy's default for an `index=True` column is
        # `ix_<table>_<column>`, which here would be `ix_environment_tier_id` —
        # the same name Base's indexed `id` already claims on the
        # `environment_tier` table. PostgreSQL index names are unique per
        # schema, so create_all would fail outright on the collision.
        Index("ix_environment_tier_fk", "tier_id"),
    )

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
    hosts: Mapped[list["EnvironmentSubSystemHost"]] = relationship(
        "EnvironmentSubSystemHost",
        back_populates="environment_subsystem",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentSubSystem(env={self.environment_id}, sub={self.subsystem_id}, "
            f"mocked={self.is_mocked})>"
        )


class EnvironmentSubSystemHost(Base):
    """Junction binding a deployed subsystem instance to the hosts it runs on.

    A single subsystem in one environment can span multiple hosts — replicas,
    multi-AZ, multi-region. The environment-level host set is therefore
    derived, not stored.
    """

    __tablename__ = "environment_subsystem_host"

    environment_subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("environment_subsystem.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    infrastructure_component_id: Mapped[int] = mapped_column(
        ForeignKey("infrastructure_component.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "environment_subsystem_id",
            "infrastructure_component_id",
            name="uq_env_subsystem_host",
        ),
    )

    environment_subsystem: Mapped["EnvironmentSubSystem"] = relationship(
        "EnvironmentSubSystem", back_populates="hosts"
    )
    infrastructure_component: Mapped["InfrastructureComponent"] = relationship(
        "InfrastructureComponent"
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentSubSystemHost(env_sub={self.environment_subsystem_id}, "
            f"host={self.infrastructure_component_id}, role={self.role!r})>"
        )
