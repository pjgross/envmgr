from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.api_scopes import KNOWN_SCOPES


class ApiKeyCreate(BaseModel):
    name: str = Field(..., max_length=120)
    scopes: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None

    @field_validator("scopes")
    @classmethod
    def _scopes_must_be_known(cls, value: list[str]) -> list[str]:
        # Validation is on CREATE only — an existing api_key row carrying an
        # unknown scope (from before this validator existed) is untouched
        # and keeps working exactly as before; it simply never matches a
        # required_scope. See app/core/api_scopes.py.
        unknown = [s for s in value if s not in KNOWN_SCOPES]
        if unknown:
            valid = ", ".join(sorted(KNOWN_SCOPES))
            raise ValueError(
                f"Unknown scope(s): {', '.join(unknown)}. "
                f"Valid scopes are: {valid}."
            )
        return value


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
