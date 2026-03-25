from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator, ConfigDict


# ── JSONB definition sub-schemas ────────────────────────────────────────────

VALID_FIELD_NAMES = {
    "project_name", "start_date", "end_date", "notes", "exclusive_use", "custom_fields"
}

VALID_ROLES = {"Admin", "Release Manager", "Test Manager", "Developer", "Viewer"}


class LifecycleState(BaseModel):
    key: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False


class LifecycleTransition(BaseModel):
    from_state: str
    to_state: str
    label: str
    allowed_roles: list[str]


class CustomFieldPermission(BaseModel):
    editable_by: list[str]

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")
        return v


class LifecycleFieldPermission(BaseModel):
    editable_fields: list[str]
    editable_by: list[str]
    custom_fields: Optional[dict[str, CustomFieldPermission]] = None

    @field_validator("editable_fields")
    @classmethod
    def validate_fields(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_FIELD_NAMES
        if invalid:
            raise ValueError(f"Invalid field names: {invalid}. Must be one of {VALID_FIELD_NAMES}")
        return v


class LifecycleDefinition(BaseModel):
    states: list[LifecycleState]
    transitions: list[LifecycleTransition]
    field_permissions: dict[str, LifecycleFieldPermission]

    @field_validator("states")
    @classmethod
    def validate_one_initial(cls, v: list[LifecycleState]) -> list[LifecycleState]:
        initial = [s for s in v if s.is_initial]
        if len(initial) != 1:
            raise ValueError("Exactly one state must have is_initial=True")
        return v


# ── Request/Response schemas ─────────────────────────────────────────────────

class LifecycleTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False
    definition: LifecycleDefinition


class LifecycleTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    definition: Optional[LifecycleDefinition] = None


class LifecycleTemplateCopy(BaseModel):
    name: str


class LifecycleTemplateResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    is_default: bool
    definition: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookingTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    lifecycle_template_id: int
    color: Optional[str] = None
    is_active: bool = True


class BookingTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    lifecycle_template_id: Optional[int] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class BookingTypeResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    lifecycle_template_id: int
    color: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
