# backend/app/api/v1/schemas/custom_field.py
import re
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


VALID_ENTITY_TYPES = {"system", "subsystem", "environment", "booking"}
VALID_FIELD_TYPES = {"text", "number", "boolean"}
FIELD_KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')


class CustomFieldDefinitionCreate(BaseModel):
    entity_type: str
    field_key: Optional[str] = None   # auto-generated from label if omitted
    label: str
    field_type: str
    required: bool = False
    display_order: int = 0

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in VALID_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of: {', '.join(sorted(VALID_ENTITY_TYPES))}")
        return v

    @field_validator("field_type")
    @classmethod
    def validate_field_type(cls, v: str) -> str:
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}")
        return v

    @field_validator("field_key")
    @classmethod
    def validate_field_key(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not FIELD_KEY_RE.match(v):
            raise ValueError("field_key must match ^[a-z][a-z0-9_]*$")
        return v


class CustomFieldDefinitionUpdate(BaseModel):
    # field_key and field_type are intentionally excluded — immutable after creation
    label: Optional[str] = None
    required: Optional[bool] = None
    display_order: Optional[int] = None


class CustomFieldDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    entity_type: str
    field_key: str
    label: str
    field_type: str
    required: bool
    display_order: int
    options: Optional[dict] = None
    lifecycle_states: Optional[list] = None
    created_at: datetime
    updated_at: datetime
