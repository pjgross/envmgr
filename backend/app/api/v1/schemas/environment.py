from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.environment import EnvironmentStatus
from app.api.v1.schemas.system import SystemResponse


class EnvironmentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tier_id: int
    owner_user_id: int
    operations_group_id: Optional[int] = None
    expires_at: datetime
    status: EnvironmentStatus = EnvironmentStatus.ACTIVE
    custom_fields: Optional[dict] = None


class EnvironmentUpdate(BaseModel):
    # forbid: the six handover fields (access_url, connection_notes,
    # support_contact, sla_notes, known_limitations, decommission_notes) are
    # deliberately absent from this schema — PATCH /environments/{id}/handover
    # is their only write path. Without extra="forbid" Pydantic silently drops
    # unknown keys, which would let a client send them here too and have them
    # quietly ignored rather than rejected — a second, unguarded door.
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    tier_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    # Typed `Optional[int] = None` like every other field here — the
    # omitted-vs-null distinction is NOT carried by this type. It comes from
    # the service reading `model_fields_set`: an omitted key means "leave
    # alone", only an explicit null clears the group. Same contract as
    # expires_at.
    operations_group_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    status: Optional[EnvironmentStatus] = None
    custom_fields: Optional[dict] = None


class EnvironmentHandoverUpdate(BaseModel):
    """The Welcome Pack's content. Six keys and no others.

    `extra="forbid"` is the safety property of this endpoint, not its
    authorization: whatever the permission rule says, a request body cannot
    reach tier_id, owner_user_id, operations_group_id or status through here.
    """

    model_config = ConfigDict(extra="forbid")

    access_url: Optional[str] = Field(default=None, max_length=500)
    connection_notes: Optional[str] = None
    support_contact: Optional[str] = Field(default=None, max_length=255)
    sla_notes: Optional[str] = None
    known_limitations: Optional[str] = None
    decommission_notes: Optional[str] = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    tier_id: int
    tier_name: str
    tier_color: Optional[str] = None
    owner_user_id: Optional[int] = None
    owner_username: Optional[str] = None
    operations_group_id: Optional[int] = None
    operations_group_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: EnvironmentStatus
    reserved_now: bool = False
    # The Welcome Pack's content — read-only here; written only via
    # PATCH /environments/{id}/handover.
    access_url: Optional[str] = None
    connection_notes: Optional[str] = None
    support_contact: Optional[str] = None
    sla_notes: Optional[str] = None
    known_limitations: Optional[str] = None
    decommission_notes: Optional[str] = None
    tenant_id: int
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "EnvironmentResponse":
        """Build from an environment_service.EnvironmentView.

        Display names travel with the row rather than being resolved by the
        browser against a separately-fetched collection — that collection is
        capped, so a `.find()` miss renders the entity as '—' and loses
        information no truncation banner can recover.
        """
        env = view.environment
        return cls(
            id=env.id,
            name=env.name,
            description=env.description,
            tier_id=env.tier_id,
            tier_name=view.tier_name,
            tier_color=view.tier_color,
            owner_user_id=env.owner_user_id,
            owner_username=view.owner_username,
            operations_group_id=env.operations_group_id,
            operations_group_name=view.operations_group_name,
            expires_at=env.expires_at,
            status=env.status,
            reserved_now=view.reserved_now,
            access_url=env.access_url,
            connection_notes=env.connection_notes,
            support_contact=env.support_contact,
            sla_notes=env.sla_notes,
            known_limitations=env.known_limitations,
            decommission_notes=env.decommission_notes,
            tenant_id=env.tenant_id,
            custom_fields=env.custom_fields,
            created_at=env.created_at,
            updated_at=env.updated_at,
        )


class EnvironmentSystemCreate(BaseModel):
    system_id: int


class EnvironmentSystemUpdate(BaseModel):
    pass  # reserved for future fields


class EnvironmentSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    system_id: int
    system: SystemResponse


class SystemSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


class EnvironmentSystemsResponse(BaseModel):
    """Response for GET /environments/{env_id}/systems — includes missing systems."""
    systems: list[EnvironmentSystemResponse]
    missing_systems: list[SystemSummary]


class VersionSummary(BaseModel):
    build_identifier: str
    version_label: str
    installed_at: datetime


class EnvironmentSubsystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    subsystem_id: int
    subsystem_name: str
    component_type: str
    component_type_definition_id: Optional[int] = None
    component_type_definition_name: Optional[str] = None
    technology: Optional[str] = None
    system_id: int
    system_name: str
    is_mocked: bool
    mock_notes: Optional[str] = None
    custom_fields: Optional[dict] = None
    latest_version: Optional[VersionSummary] = None


class EnvironmentSubsystemUpdate(BaseModel):
    is_mocked: Optional[bool] = None
    mock_notes: Optional[str] = None
    component_type_definition_id: Optional[int] = None
    custom_fields: Optional[dict] = None


class EnvSubsystemHostRef(BaseModel):
    """A host an environment subsystem is deployed on, for the topology diagram."""
    infrastructure_component_id: int
    name: str
    component_type: str          # InfrastructureComponentType value (str-enum)
    role: Optional[str] = None


class EnvSubsystemNode(BaseModel):
    """Subsystem node for the environment topology response."""
    id: int
    name: str
    component_type: str
    technology: Optional[str] = None
    system_id: int
    is_mocked: bool
    hosts: list[EnvSubsystemHostRef] = []


from app.api.v1.schemas.dependency import ComponentDependencyResponse  # noqa: E402


class EnvironmentTopologyResponse(BaseModel):
    environment_id: int
    subsystems: list[EnvSubsystemNode]
    dependencies: list[ComponentDependencyResponse]
    system_names: dict[str, str]
    outside_subsystems: list[EnvSubsystemNode]
    outside_dependencies: list[ComponentDependencyResponse]
