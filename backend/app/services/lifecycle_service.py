import copy

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.booking_lifecycle import BookingType
from app.api.v1.schemas.booking_lifecycle import (
    ENTITY_FIELD_SPECS,
    LifecycleDefinition,
    LifecycleTemplateCreate,
    LifecycleTemplateUpdate,
    VALID_STANDARD_FIELD_NAMES,
    validate_definition_for_entity,
)


def migrate_field_permissions(definition: dict, entity_type: str = "booking") -> dict:
    """Convert old editable_fields/editable_by shape to standard_fields per-field shape.
    A definition is old-shape if ANY state entry in field_permissions contains 'editable_fields'.
    Every such state entry is converted; entries already in new shape are left untouched.
    Returns the mutated definition dict.

    Conversion rule: fields listed in `editable_fields` inherit the state's
    `editable_by`; all other standard field names for the given entity_type
    get editable_by: []. Falls back to the booking spec if `entity_type`
    isn't in ENTITY_FIELD_SPECS, so legacy data paths keep working.
    """
    spec = ENTITY_FIELD_SPECS.get(entity_type) or ENTITY_FIELD_SPECS["booking"]
    valid_fields = spec["valid"]
    field_perms = definition.get("field_permissions", {})
    for state_key, perm in field_perms.items():
        if "editable_fields" not in perm:
            continue  # already new shape
        old_editable_fields = perm.get("editable_fields", [])
        old_editable_by = perm.get("editable_by", [])
        # Iterate over ALL valid standard field names so no field is silently dropped
        standard_fields = {
            f: {"editable_by": old_editable_by if f in old_editable_fields else []}
            for f in valid_fields
        }
        new_perm = {"standard_fields": standard_fields}
        if "custom_fields" in perm:
            new_perm["custom_fields"] = perm["custom_fields"]
        field_perms[state_key] = new_perm
    return definition


async def create_template(
    db: AsyncSession, data: LifecycleTemplateCreate, tenant_id: int, entity_type: str
) -> LifecycleTemplate:
    # Validate JSONB shape + enforce entity-specific field rules (-> 422)
    try:
        validate_definition_for_entity(data.definition, entity_type, applies_to_kind=data.applies_to_kind)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    definition_dict = migrate_field_permissions(data.definition.model_dump(), entity_type)
    template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type=entity_type,
        name=data.name,
        description=data.description,
        is_default=data.is_default,
        applies_to_kind=data.applies_to_kind,
        definition=definition_dict,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def list_templates(
    db: AsyncSession, tenant_id: int, entity_type: str | None = None
) -> list[LifecycleTemplate]:
    """List lifecycle templates for a tenant.

    If `entity_type` is provided, results are filtered to that type; otherwise
    returns all templates for the tenant (useful for admin tooling / migrations).
    """
    stmt = select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == tenant_id,
        LifecycleTemplate.deleted_at.is_(None),
    )
    if entity_type is not None:
        stmt = stmt.where(LifecycleTemplate.entity_type == entity_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_template(
    db: AsyncSession, template_id: int, tenant_id: int
) -> LifecycleTemplate:
    result = await db.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.id == template_id,
            LifecycleTemplate.tenant_id == tenant_id,
            LifecycleTemplate.deleted_at.is_(None),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lifecycle template not found")
    return template


async def update_template(
    db: AsyncSession, template_id: int, data: LifecycleTemplateUpdate, tenant_id: int
) -> LifecycleTemplate:
    template = await get_template(db, template_id, tenant_id)
    if data.name is not None:
        template.name = data.name
    if data.description is not None:
        template.description = data.description
    if data.is_default is not None:
        template.is_default = data.is_default
    if data.applies_to_kind is not None:
        template.applies_to_kind = data.applies_to_kind
    if data.definition is not None:
        effective_kind = data.applies_to_kind if data.applies_to_kind is not None else template.applies_to_kind
        try:
            validate_definition_for_entity(data.definition, template.entity_type, applies_to_kind=effective_kind)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
        template.definition = migrate_field_permissions(
            data.definition.model_dump(), template.entity_type
        )
    await db.flush()
    await db.refresh(template)
    return template


async def delete_template(db: AsyncSession, template_id: int, tenant_id: int) -> None:
    template = await get_template(db, template_id, tenant_id)
    # Guard: refuse if any active booking type references this template
    in_use = (
        await db.execute(
            select(BookingType).where(
                BookingType.lifecycle_template_id == template_id,
                BookingType.tenant_id == tenant_id,
                BookingType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete: template is in use by one or more booking types",
        )
    from datetime import datetime, timezone

    template.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def copy_template(
    db: AsyncSession, template_id: int, new_name: str, tenant_id: int
) -> LifecycleTemplate:
    original = await get_template(db, template_id, tenant_id)
    new_template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type=original.entity_type,
        applies_to_kind=original.applies_to_kind,
        name=new_name,
        description=original.description,
        is_default=False,
        definition=migrate_field_permissions(
            copy.deepcopy(original.definition), original.entity_type
        ),
    )
    db.add(new_template)
    await db.flush()
    await db.refresh(new_template)
    return new_template


def validate_transition(
    definition: dict,
    from_state: str,
    to_state: str,
    user_role: str,
    record_values: dict | None = None,
) -> tuple[bool, str | None]:
    """Return (allowed, reason). `reason` is None when allowed.

    Role check is authoritative and evaluated first. If the role passes,
    `required_fields` on the destination state are checked against
    `record_values` (flat keys for standard fields; custom fields live under
    record_values['custom_fields']). An empty or missing value blocks.
    """
    transition = next(
        (t for t in definition.get("transitions", [])
         if t["from_state"] == from_state and t["to_state"] == to_state),
        None,
    )
    if transition is None:
        return False, f"No transition from '{from_state}' to '{to_state}' is defined"
    if user_role not in transition["allowed_roles"]:
        return False, f"Role '{user_role}' is not allowed to transition {from_state} → {to_state}"
    required = (
        definition.get("field_permissions", {})
        .get(to_state, {})
        .get("required_fields", [])
    )
    if required:
        values = record_values or {}
        custom_values = values.get("custom_fields") or {}
        missing: list[str] = []
        for key in required:
            v = values.get(key) if key in values else custom_values.get(key)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                missing.append(key)
        if missing:
            return False, f"Required fields empty for '{to_state}': {', '.join(missing)}"
    return True, None


def get_allowed_transitions(definition: dict, current_state: str, user_role: str) -> list[dict]:
    """Return all transitions from current_state that this role can make."""
    return [
        t
        for t in definition.get("transitions", [])
        if t["from_state"] == current_state and user_role in t["allowed_roles"]
    ]


def get_custom_field_permissions(
    definition: dict,
    current_state: str,
    user_role: str,
    active_field_keys: set[str],
) -> dict[str, dict]:
    """
    Return {field_key: {visible, editable}} for all custom fields visible in this state.
    Fields absent from the state config, or whose CustomFieldDefinition has been
    soft-deleted (not in active_field_keys), are omitted (treated as hidden).
    """
    perm = definition.get("field_permissions", {}).get(current_state, {})
    result = {}
    for key, entry in (perm.get("custom_fields") or {}).items():
        if key not in active_field_keys:
            continue  # definition was soft-deleted; skip silently
        editable_by = entry.get("editable_by", [])
        result[key] = {
            "visible": True,
            "editable": user_role in editable_by,
        }
    return result


def get_field_permissions_for_state(
    definition: dict,
    state_key: str,
    user_role: str,
    active_custom_field_keys: set[str],
    valid_standard_field_names: set[str],
) -> dict:
    """Return {custom_field_permissions, standard_field_permissions} for state+role.

    Shape (matches the existing booking response contract):
      {
        "custom_field_permissions": {field_key: {"visible": bool, "editable": bool}},
        "standard_field_permissions": {field_name: {"editable": bool}},
      }

    Behavior:
      - Custom fields: only keys configured for this state AND present in
        active_custom_field_keys appear. Missing state entry → empty dict.
      - Standard fields: every name in valid_standard_field_names appears in
        the output (always). `editable` is True only when the role is in the
        state's standard_fields[name].editable_by list; False otherwise.
      - Missing state config fails closed (everything not editable).
    """
    state_perm = definition.get("field_permissions", {}).get(state_key, {}) or {}

    # Custom fields — reuse the existing helper so its rules stay single-sourced.
    custom = get_custom_field_permissions(
        definition, state_key, user_role, active_custom_field_keys
    )

    # Standard fields — always include every valid name so clients can render
    # a stable field list; editability is role/state derived.
    standard_config = state_perm.get("standard_fields", {}) or {}
    standard: dict[str, dict] = {}
    for name in valid_standard_field_names:
        entry = standard_config.get(name) or {}
        editable_by = entry.get("editable_by", [])
        standard[name] = {"editable": user_role in editable_by}

    return {
        "custom_field_permissions": custom,
        "standard_field_permissions": standard,
    }
