from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator, ConfigDict


# ── JSONB definition sub-schemas ────────────────────────────────────────────

VALID_ROLES = {"Admin", "Release Manager", "Test Manager", "Developer", "Viewer"}

VALID_STANDARD_FIELD_NAMES = {
    "project_name", "start_date", "end_date", "booking_type",
    "notes", "exclusive_use", "context_tag",
}

MANDATORY_STANDARD_FIELDS = {"project_name", "start_date", "end_date", "booking_type"}


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


class StandardFieldPermission(BaseModel):
    editable_by: list[str]

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")
        return v


class LifecycleFieldPermission(BaseModel):
    standard_fields: dict[str, StandardFieldPermission] = {}
    custom_fields: Optional[dict[str, CustomFieldPermission]] = None

    @field_validator("standard_fields")
    @classmethod
    def validate_field_names(cls, v: dict) -> dict:
        invalid = set(v.keys()) - VALID_STANDARD_FIELD_NAMES
        if invalid:
            raise ValueError(f"Invalid standard field names: {invalid}. Must be one of {VALID_STANDARD_FIELD_NAMES}")
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

    @model_validator(mode="after")
    def validate_mandatory_fields_in_initial_state(self) -> "LifecycleDefinition":
        initial = next((s for s in self.states if s.is_initial), None)
        if initial is None:
            return self  # validate_one_initial will catch this
        perm = self.field_permissions.get(initial.key)
        if perm is None:
            raise ValueError(
                f"Initial state '{initial.key}' has no field_permissions entry. "
                f"Mandatory fields {MANDATORY_STANDARD_FIELDS} must each have at least one editable role."
            )
        for field in MANDATORY_STANDARD_FIELDS:
            sf = perm.standard_fields.get(field)
            if sf is None or len(sf.editable_by) == 0:
                raise ValueError(
                    f"Mandatory field '{field}' in initial state '{initial.key}' "
                    f"must have at least one role in editable_by."
                )
        return self


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
