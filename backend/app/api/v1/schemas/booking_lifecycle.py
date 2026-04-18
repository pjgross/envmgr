from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator, ConfigDict


# ── JSONB definition sub-schemas ────────────────────────────────────────────

VALID_ROLES = {"Admin", "Release Manager", "Test Manager", "Developer", "Viewer"}

# Per-entity field specs for lifecycle definitions.
# Each entry drives two validation rules applied by the service layer on save:
#   1. "valid": `LifecycleDefinition.field_permissions[state].standard_fields`
#      may only use these keys.
#   2. "mandatory": each of these fields must appear with a non-empty
#      `editable_by` list in the initial state.
ENTITY_FIELD_SPECS: dict[str, dict[str, set[str]]] = {
    "booking": {
        "valid": {
            "project_name", "start_date", "end_date", "booking_type",
            "notes", "exclusive_use", "context_tag",
        },
        "mandatory": {"project_name", "start_date", "end_date", "booking_type"},
    },
    "change_request": {
        "valid": {
            "title", "description", "change_type",
            "scheduled_start", "scheduled_end",
            "has_outage", "outage_start", "outage_end",
            "release_id",
        },
        "mandatory": {"title", "change_type", "scheduled_start", "scheduled_end"},
    },
}

# Back-compat aliases — booking-specific code paths still import these names.
VALID_STANDARD_FIELD_NAMES = ENTITY_FIELD_SPECS["booking"]["valid"]
MANDATORY_STANDARD_FIELDS = ENTITY_FIELD_SPECS["booking"]["mandatory"]


def validate_definition_for_entity(
    definition: "LifecycleDefinition", entity_type: str
) -> None:
    """Enforce entity-specific rules on a LifecycleDefinition. Raises ValueError.

    Called from the service layer at create/update time where the owning
    template's `entity_type` is known. Pydantic model validation can't do this
    itself because `LifecycleDefinition` doesn't (and shouldn't) know what
    entity it belongs to.
    """
    spec = ENTITY_FIELD_SPECS.get(entity_type)
    if spec is None:
        # Unknown entity — skip strict checks rather than block new entity
        # types before their spec is registered.
        return

    valid = spec["valid"]
    mandatory = spec["mandatory"]

    # 1. Unknown standard-field names anywhere in field_permissions.
    for state_key, perm in definition.field_permissions.items():
        invalid = set(perm.standard_fields.keys()) - valid
        if invalid:
            raise ValueError(
                f"Invalid standard field names for entity '{entity_type}' in state "
                f"'{state_key}': {sorted(invalid)}. Must be one of {sorted(valid)}."
            )

    # 2. Mandatory fields must have ≥1 editable role in the initial state.
    initial = next((s for s in definition.states if s.is_initial), None)
    if initial is None:
        return  # validate_one_initial catches this elsewhere
    perm = definition.field_permissions.get(initial.key)
    if perm is None:
        if mandatory:
            raise ValueError(
                f"Initial state '{initial.key}' has no field_permissions entry. "
                f"Mandatory fields {sorted(mandatory)} must each have at least "
                "one editable role."
            )
        return
    for field in mandatory:
        sf = perm.standard_fields.get(field)
        if sf is None or len(sf.editable_by) == 0:
            raise ValueError(
                f"Mandatory field '{field}' in initial state '{initial.key}' "
                "must have at least one role in editable_by."
            )


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


class _FieldPermission(BaseModel):
    editable_by: list[str]


class CustomFieldPermission(_FieldPermission):
    pass


class StandardFieldPermission(_FieldPermission):
    pass


class LifecycleFieldPermission(BaseModel):
    # Entity-specific name / mandatory-in-initial-state checks happen in the
    # service layer via validate_definition_for_entity(). Pydantic can't do
    # them here without knowing which entity_type this permission belongs to.
    standard_fields: dict[str, StandardFieldPermission] = {}
    custom_fields: Optional[dict[str, CustomFieldPermission]] = None


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
    entity_type: str = "booking"
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
    entity_type: str
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
