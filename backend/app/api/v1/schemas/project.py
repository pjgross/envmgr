from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    is_active: bool = True


class ProjectUpdate(BaseModel):
    """Every field optional. `team_group_id` is `int | None`: the service keys
    on model_fields_set, so an omitted key means "leave alone" and only an
    explicit null clears the team — the same contract B1 gave expires_at.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    """`team_group_name` and `environment_count` travel with the row.

    Resolving them in the browser against separately-fetched collections is the
    failure docs/pagination.md documents: those collections are capped, so a
    `.find()` miss renders the entity as '—' and loses information no
    truncation banner can recover.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    team_group_name: Optional[str] = None
    environment_count: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "ProjectResponse":
        p = view.project
        return cls(
            id=p.id, tenant_id=p.tenant_id, name=p.name, code=p.code,
            description=p.description, team_group_id=p.team_group_id,
            team_group_name=view.team_group_name,
            environment_count=view.environment_count,
            is_active=p.is_active,
            created_at=p.created_at, updated_at=p.updated_at,
        )


class UsageAgreementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: int
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    notes: Optional[str] = None


class UsageAgreementResponse(BaseModel):
    """Both display names travel with the row: this list is read from the
    project side AND the environment side, and neither page should resolve the
    other end against a capped collection."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    project_name: str
    environment_id: int
    environment_name: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "UsageAgreementResponse":
        agreement, project_name, environment_name = row
        return cls(
            id=agreement.id, tenant_id=agreement.tenant_id,
            project_id=agreement.project_id, project_name=project_name,
            environment_id=agreement.environment_id,
            environment_name=environment_name,
            starts_at=agreement.starts_at, ends_at=agreement.ends_at,
            notes=agreement.notes, created_at=agreement.created_at,
        )
