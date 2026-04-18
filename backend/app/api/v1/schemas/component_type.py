import re
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


VALID_FIELD_TYPES = {"text", "number", "boolean"}
FIELD_KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')


class FieldDefinitionSchema(BaseModel):
    field_key: str
    label: str
    field_type: str
    required: bool = False
    display_order: int = 0

    @field_validator("field_type")
    @classmethod
    def validate_field_type(cls, v: str) -> str:
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}")
        return v

    @field_validator("field_key")
    @classmethod
    def validate_field_key(cls, v: str) -> str:
        if not FIELD_KEY_RE.match(v):
            raise ValueError("field_key must match ^[a-z][a-z0-9_]*$")
        return v


class ComponentTypeDefinitionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    field_definitions: Optional[list[FieldDefinitionSchema]] = None

    @model_validator(mode="after")
    def validate_unique_field_keys(self):
        if self.field_definitions:
            keys = [f.field_key for f in self.field_definitions]
            if len(keys) != len(set(keys)):
                raise ValueError("field_key values must be unique within field_definitions")
        return self


class ComponentTypeDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    field_definitions: Optional[list[FieldDefinitionSchema]] = None

    @model_validator(mode="after")
    def validate_unique_field_keys(self):
        if self.field_definitions:
            keys = [f.field_key for f in self.field_definitions]
            if len(keys) != len(set(keys)):
                raise ValueError("field_key values must be unique within field_definitions")
        return self


class ComponentTypeDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    field_definitions: Optional[list[FieldDefinitionSchema]] = None
    created_at: datetime
    updated_at: datetime
