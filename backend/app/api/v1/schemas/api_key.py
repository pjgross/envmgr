from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., max_length=120)
    scopes: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scopes: list[str]
    created_by: int
    created_by_username: Optional[str] = None
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned exactly once from POST — includes the raw key."""
    raw_key: str
