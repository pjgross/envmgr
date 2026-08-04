from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class UserGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None


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
