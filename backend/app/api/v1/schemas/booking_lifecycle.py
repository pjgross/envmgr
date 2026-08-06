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
    "release": {
        "valid": {
            "name",
            "description",
            "release_type",
            "target_date",
            "actual_date",
            "raised_by",
        },
        "mandatory": set(),
    },
    "environment_request": {
        "valid": {
            "kind", "justification", "needed_by", "environment_id",
            "proposed_name", "tier_id", "expires_at", "operations_group_id",
        },
        # Empty: a non-empty mandatory set here requires the initial state to
        # carry a populated field_permissions entry (a non-empty editable_by
        # list per mandatory field), and this template ships
        # field_permissions={} — deliberately plain, see
        # environment_request_defaults.py. "release" also has an empty
        # mandatory set, but for an unrelated reason: its own default
        # templates (release_defaults.py) enforce required-ness through
        # field_permissions[state]["required_fields"], read by
        # lifecycle_service at transition time, not through this mandatory
        # set at all. 'kind' and 'justification' here are enforced in
        # environment_request_service instead, which can name the missing
        # field in its message.
        "mandatory": set(),
    },
}

# Back-compat aliases — booking-specific code paths still import these names.
VALID_STANDARD_FIELD_NAMES = ENTITY_FIELD_SPECS["booking"]["valid"]
MANDATORY_STANDARD_FIELDS = ENTITY_FIELD_SPECS["booking"]["mandatory"]

VALID_ENTERPRISE_ACTION_KEYS = {"membership.admit", "membership.reject", "membership.remove"}


def validate_definition_for_entity(
    definition: "LifecycleDefinition",
    entity_type: str,
    applies_to_kind: Optional[str] = None,
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

    # C1(b): environment_request_service keys FIVE places on literal state
    # strings — create_request's initial write (now the template's own
    # is_initial state, not a literal, per C1(a)), transition()'s fulfilment
    # and submission-routing branches, build_welcome_pack's fulfilled gate,
    # and APPROVAL_TARGET_STATES. A template that renames 'submitted',
    # 'approved', 'rejected' or 'fulfilled' doesn't get a smaller version of
    # this feature — it silently loses the group-gate authorization check
    # entirely (a state the service never recognises as an
    # APPROVAL_TARGET_STATE needs no group membership to reach) and/or wedges
    # every request in a status the template has no transitions out of. A
    # tenant may still add states, add a second review step, and rewire
    # transitions freely — this only pins the four names the service's own
    # logic depends on. "Exactly one is_initial" is already enforced for
    # every entity by LifecycleDefinition.validate_one_initial above; the
    # INITIAL state's name itself is deliberately not pinned here, since
    # create_request now reads it from the template rather than assuming
    # 'draft'.
    if entity_type == "environment_request":
        required_states = {"submitted", "approved", "rejected", "fulfilled"}
        state_keys = {s.key for s in definition.states}
        missing = required_states - state_keys
        if missing:
            raise ValueError(
                "An environment_request lifecycle must define states named "
                f"{sorted(required_states)} (the service's own logic keys on "
                f"these names) — missing: {sorted(missing)}."
            )

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

    if entity_type == "release" and applies_to_kind == "enterprise":
        # Single-lockdown invariant
        lockdowns = [s for s in definition.states if s.is_admission_lockdown]
        if len(lockdowns) > 1:
            raise ValueError(
                "at most one state may have is_admission_lockdown=True"
            )
        # Action permissions keys must be recognized
        for state_key, actions in (definition.action_permissions or {}).items():
            for action_key in actions:
                if action_key not in VALID_ENTERPRISE_ACTION_KEYS:
                    raise ValueError(
                        f"unknown action_key '{action_key}' at state '{state_key}'"
                    )
    else:
        # Reject flags that are only meaningful on enterprise templates.
        for s in definition.states:
            if s.is_admission_lockdown:
                raise ValueError(
                    "is_admission_lockdown only valid on release/enterprise templates"
                )
        if definition.action_permissions:
            raise ValueError(
                "action_permissions only valid on release/enterprise templates"
            )


class LifecycleState(BaseModel):
    key: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False
    is_admission_lockdown: bool = False  # only meaningful for release/enterprise lifecycles


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
    action_permissions: Optional[dict[str, dict[str, list[str]]]] = None

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
    applies_to_kind: Optional[str] = None
    definition: LifecycleDefinition


class LifecycleTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    applies_to_kind: Optional[str] = None
    definition: Optional[LifecycleDefinition] = None


class LifecycleTemplateCopy(BaseModel):
    name: str


class LifecycleTemplateResponse(BaseModel):
    id: int
    tenant_id: int
    entity_type: str
    applies_to_kind: Optional[str] = None
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
