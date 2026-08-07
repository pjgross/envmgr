from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnvironmentGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: bool = True


class EnvironmentGroupUpdate(BaseModel):
    """Every field optional; the service keys on model_fields_set, so an
    omitted key means "leave alone".

    `name` and `is_active` reject an explicit null rather than 500ing on it —
    A1 shipped that bug by copying UserGroupUpdate's type and dropping its
    validator. `description` genuinely accepts null, to clear it.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name", "is_active")
    @classmethod
    def _reject_explicit_null(cls, v, info):
        if v is None:
            raise ValueError(f"{info.field_name} may not be null")
        return v


class EnvironmentGroupResponse(BaseModel):
    """`member_count` travels with the row.

    Counting in the browser against a separately-fetched members list is the
    failure docs/pagination.md documents: that list is capped, so past the cap
    the number is simply wrong — and a wrong number is worse than a hidden
    row, because nothing signals it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    member_count: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "EnvironmentGroupResponse":
        g = view.group
        return cls(
            id=g.id, tenant_id=g.tenant_id, name=g.name, description=g.description,
            member_count=view.member_count, is_active=g.is_active,
            created_at=g.created_at, updated_at=g.updated_at,
        )


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: int


class MemberResponse(BaseModel):
    """Both display names travel with the row: this list is read from the
    group side AND the environment side, and neither page should resolve the
    other end against a capped collection."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    group_id: int
    group_name: str
    environment_id: int
    environment_name: str
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "MemberResponse":
        member, group_name, environment_name = row
        return cls(
            id=member.id, tenant_id=member.tenant_id,
            group_id=member.group_id, group_name=group_name,
            environment_id=member.environment_id, environment_name=environment_name,
            created_at=member.created_at,
        )
