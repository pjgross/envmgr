from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class UserGroupUpdate(BaseModel):
    # Unlike `description`, an omitted key and an explicit null are NOT both
    # legal here: `name` is NOT NULL with min_length=1, so clearing it is
    # never a valid state. Pydantic's min_length check does not run against
    # None, so without the validator below an explicit `"name": null` would
    # sail through untyped and reach the service as data.name is None — the
    # same shape the service uses to mean "omitted". The validator only fires
    # when the client actually supplies the key (validate_default is off), so
    # an omitted `name` still leaves the default None untouched.
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    # Typed `Optional[str] = None` like every other nullable field here — the
    # omitted-vs-null distinction is NOT carried by this type. It comes from
    # the service reading `model_fields_set`: an omitted key means "leave
    # alone", only an explicit null clears the description. Same contract as
    # environment_service's expires_at/operations_group_id.
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_cannot_be_cleared(cls, v):
        if v is None:
            raise ValueError("name cannot be cleared")
        return v


class UserGroupResponse(BaseModel):
    """The counts travel with the row rather than being resolved in the browser.

    `member_count` is what the group detail page shows instead of an embedded
    member array; `environment_count` is the grid column. Both are computed in
    SQL, so neither is sortable — see USER_GROUP_SORTS.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    member_count: int = 0
    environment_count: int = 0
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "UserGroupResponse":
        return cls(
            id=view.group.id,
            tenant_id=view.group.tenant_id,
            name=view.group.name,
            description=view.group.description,
            member_count=view.member_count,
            environment_count=view.environment_count,
            created_at=view.group.created_at,
            updated_at=view.group.updated_at,
        )


class UserGroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    group_id: int
    created_at: datetime


class UserGroupMemberCreate(BaseModel):
    user_id: int
