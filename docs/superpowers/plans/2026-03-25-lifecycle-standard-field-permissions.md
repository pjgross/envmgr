# Lifecycle Standard Field Permissions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-field, per-role editability configuration for standard booking fields (project_name, start_date, end_date, booking_type, notes, exclusive_use, context_tag) to lifecycle templates, with backend enforcement on booking updates and frontend read-only gating.

**Architecture:** Replace the flat `editable_fields`/`editable_by` shape in `LifecycleFieldPermission` with a `standard_fields: Record<str, {editable_by: [roles]}>` map that mirrors the existing `custom_fields` pattern. Backend enforces permissions via a new `PATCH /bookings/{id}/standard-fields` endpoint. The `GET /bookings/{id}` response gains `standard_field_permissions` so the frontend can gate field editability without client-side logic.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, pytest + httpx + SQLite (tests), React 18, TypeScript, MUI

---

## File Map

| File | Change |
|---|---|
| `backend/app/api/v1/schemas/booking_lifecycle.py` | Replace `LifecycleFieldPermission`; add `StandardFieldPermission`, new constants, model validator |
| `backend/app/api/v1/schemas/booking.py` | Add `standard_field_permissions` to `BookingResponse` |
| `backend/app/services/booking_lifecycle_service.py` | Remove `get_editable_fields`; add `migrate_field_permissions`; call it in create/update/copy |
| `backend/app/services/booking_service.py` | Remove dead import; add `get_standard_field_permissions`, `get_standard_field_perms_for_booking`, `update_standard_fields` |
| `backend/app/api/v1/bookings.py` | Add `PATCH /standard-fields` endpoint; update `GET /{id}` to populate `standard_field_permissions` |
| `backend/tests/test_booking_standard_field_permissions.py` | **New** — unit + integration tests for standard field permissions |
| `backend/tests/test_booking_lifecycle.py` | Update `DEFAULT_DEFINITION` fixture to new shape |
| `backend/tests/test_booking_transitions.py` | Update template fixture to new shape |
| `backend/tests/test_booking_custom_field_permissions.py` | Update template fixtures to new shape |
| `backend/tests/integration/test_bookings.py` | Update template fixtures to new shape |
| `backend/tests/integration/test_custom_fields.py` | Update template fixtures to new shape |
| `backend/tests/integration/test_events.py` | Update template fixtures to new shape |
| `frontend/src/types/bookingLifecycle.ts` | Update `LifecycleFieldPermission` interface |
| `frontend/src/types/booking.ts` | Add `standard_field_permissions` to `BookingResponse` |
| `frontend/src/services/bookingService.ts` | Add `updateStandardFields` |
| `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` | Update `FieldPermState`, `handleEditOpen`, Field Permissions UI, `handleSave`, validation |
| `frontend/src/pages/bookings/BookingDetail.tsx` | Add standard fields edit button + dialog gated by `standard_field_permissions` |

---

## Task 1: Update backend schemas

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py`
- Modify: `backend/app/api/v1/schemas/booking.py`

The new `LifecycleFieldPermission` replaces `editable_fields`/`editable_by` with `standard_fields`. A `@model_validator(mode="after")` on `LifecycleDefinition` enforces that mandatory standard fields have at least one editable role in the initial state.

**Important:** After this task, any test that creates a lifecycle template via the API with the old `editable_fields`/`editable_by` shape will fail the mandatory fields validator. Test fixtures are updated in Task 2.

- [ ] **Step 1: Write failing schema tests**

Create `backend/tests/test_booking_standard_field_permissions.py`:

```python
"""Unit and integration tests for standard field permissions in lifecycle templates."""
import pytest
from pydantic import ValidationError
from app.api.v1.schemas.booking_lifecycle import (
    LifecycleDefinition,
    LifecycleFieldPermission,
    StandardFieldPermission,
    VALID_STANDARD_FIELD_NAMES,
    MANDATORY_STANDARD_FIELDS,
)

# --- Minimal valid definition with all mandatory fields editable in initial state ---

def _make_definition(draft_standard_fields: dict) -> dict:
    """Build a minimal LifecycleDefinition dict with given draft standard_fields."""
    return {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "closed", "label": "Closed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "closed", "label": "Close", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {
            "draft": {"standard_fields": draft_standard_fields},
            "closed": {"standard_fields": {}},
        },
    }


MANDATORY_EDITABLE = {
    "project_name": {"editable_by": ["Admin"]},
    "start_date": {"editable_by": ["Admin"]},
    "end_date": {"editable_by": ["Admin"]},
    "booking_type": {"editable_by": ["Admin"]},
}


def test_valid_standard_fields():
    """LifecycleDefinition with all mandatory fields editable in initial state validates."""
    d = _make_definition(MANDATORY_EDITABLE)
    obj = LifecycleDefinition.model_validate(d)
    assert obj.states[0].is_initial is True


def test_invalid_standard_field_name():
    """standard_fields with unknown key is rejected with 422-style ValidationError."""
    fields = {**MANDATORY_EDITABLE, "nonexistent_field": {"editable_by": ["Admin"]}}
    d = _make_definition(fields)
    with pytest.raises(ValidationError, match="Invalid standard field names"):
        LifecycleDefinition.model_validate(d)


def test_invalid_role_in_standard_field():
    """standard_fields with invalid role raises ValidationError."""
    fields = {**MANDATORY_EDITABLE, "notes": {"editable_by": ["NotARealRole"]}}
    d = _make_definition(fields)
    with pytest.raises(ValidationError):
        LifecycleDefinition.model_validate(d)


def test_mandatory_field_missing_from_initial_state():
    """Initial state with a mandatory field missing from standard_fields is rejected."""
    incomplete = {k: v for k, v in MANDATORY_EDITABLE.items() if k != "start_date"}
    d = _make_definition(incomplete)
    with pytest.raises(ValidationError, match="start_date"):
        LifecycleDefinition.model_validate(d)


def test_mandatory_field_no_roles_in_initial_state():
    """Mandatory field with empty editable_by in initial state is rejected."""
    fields = {**MANDATORY_EDITABLE, "start_date": {"editable_by": []}}
    d = _make_definition(fields)
    with pytest.raises(ValidationError, match="start_date"):
        LifecycleDefinition.model_validate(d)


def test_non_mandatory_field_can_be_readonly():
    """Non-mandatory field (notes) with no roles does not fail validation."""
    fields = {**MANDATORY_EDITABLE, "notes": {"editable_by": []}}
    d = _make_definition(fields)
    LifecycleDefinition.model_validate(d)  # should not raise


def test_valid_standard_field_names_constant():
    """VALID_STANDARD_FIELD_NAMES contains the 7 expected keys."""
    assert VALID_STANDARD_FIELD_NAMES == {
        "project_name", "start_date", "end_date", "booking_type",
        "notes", "exclusive_use", "context_tag",
    }


def test_mandatory_standard_fields_constant():
    """MANDATORY_STANDARD_FIELDS contains the 4 expected mandatory keys."""
    assert MANDATORY_STANDARD_FIELDS == {"project_name", "start_date", "end_date", "booking_type"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py::test_valid_standard_fields tests/test_booking_standard_field_permissions.py::test_invalid_standard_field_name -v
```

Expected: FAIL with `ImportError` (constants don't exist yet) or `ValidationError` not raised.

- [ ] **Step 3: Update `booking_lifecycle.py` schema**

In `backend/app/api/v1/schemas/booking_lifecycle.py`:

1. Add after `VALID_ROLES`:
```python
VALID_STANDARD_FIELD_NAMES = {
    "project_name", "start_date", "end_date", "booking_type",
    "notes", "exclusive_use", "context_tag",
}

MANDATORY_STANDARD_FIELDS = {"project_name", "start_date", "end_date", "booking_type"}
```

2. Add `StandardFieldPermission` class after `CustomFieldPermission`:
```python
class StandardFieldPermission(BaseModel):
    editable_by: list[str]

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")
        return v
```

3. Replace `LifecycleFieldPermission` entirely (remove `editable_fields`, `editable_by`, `validate_fields`, `VALID_FIELD_NAMES`):
```python
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
```

4. Add model validator to `LifecycleDefinition` (after the existing `validate_one_initial` field validator):
```python
from pydantic import model_validator

# inside LifecycleDefinition class:
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
```

Also remove `VALID_FIELD_NAMES` constant and the old `validate_fields` validator (they are gone since we replaced `LifecycleFieldPermission`).

5. In `booking.py`, add to `BookingResponse`:
```python
standard_field_permissions: Optional[dict[str, dict]] = None
```

- [ ] **Step 4: Run schema tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py -k "not asyncio" -v
```

Expected: All 8 unit tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/api/v1/schemas/booking_lifecycle.py app/api/v1/schemas/booking.py tests/test_booking_standard_field_permissions.py
git commit -m "feat: add StandardFieldPermission schema and mandatory fields validator"
```

---

## Task 2: Update test fixtures to new schema shape

6 existing test files create lifecycle templates using the old `editable_fields`/`editable_by` shape. Now that the schema rejects the old shape (mandatory fields must be present in initial state), these fixtures must be updated.

**Files:**
- Modify: `backend/tests/test_booking_lifecycle.py`
- Modify: `backend/tests/test_booking_transitions.py`
- Modify: `backend/tests/test_booking_custom_field_permissions.py`
- Modify: `backend/tests/integration/test_bookings.py`
- Modify: `backend/tests/integration/test_custom_fields.py`
- Modify: `backend/tests/integration/test_events.py`

The standard pattern for the minimal required `standard_fields` in an initial state:

```python
"standard_fields": {
    "project_name": {"editable_by": ["Admin", "Release Manager", "Developer"]},
    "start_date": {"editable_by": ["Admin", "Release Manager", "Developer"]},
    "end_date": {"editable_by": ["Admin", "Release Manager", "Developer"]},
    "booking_type": {"editable_by": ["Admin", "Release Manager", "Developer"]},
}
```

Non-initial states: keep `"standard_fields": {}` (all read-only, which is fine for testing).

- [ ] **Step 1: Run existing tests to confirm they currently pass before schema change**

```bash
cd backend && python -m pytest tests/test_booking_lifecycle.py tests/test_booking_transitions.py tests/test_booking_custom_field_permissions.py tests/integration/test_bookings.py tests/integration/test_custom_fields.py tests/integration/test_events.py -v --tb=no -q
```

Expected: All pass (confirming baseline).

- [ ] **Step 2: Run those same tests after schema change to confirm they fail**

They should now fail with 422 because the old `editable_fields`/`editable_by` definitions don't pass the mandatory fields validator.

Expected: Multiple failures with 422 errors.

- [ ] **Step 3: Update `test_booking_lifecycle.py`**

Replace `DEFAULT_DEFINITION`'s `field_permissions` section:

```python
"field_permissions": {
    "draft": {
        "standard_fields": {
            "project_name": {"editable_by": ["Admin", "Release Manager", "Developer"]},
            "start_date": {"editable_by": ["Admin", "Release Manager", "Developer"]},
            "end_date": {"editable_by": ["Admin", "Release Manager", "Developer"]},
            "booking_type": {"editable_by": ["Admin", "Release Manager", "Developer"]},
            "notes": {"editable_by": ["Admin", "Release Manager", "Developer"]},
        }
    },
    "submitted": {"standard_fields": {}},
    "approved": {"standard_fields": {}},
    "rejected": {"standard_fields": {}},
}
```

- [ ] **Step 4: Update `test_booking_transitions.py`**

Find and update every `field_permissions` dict in this file. Use the same pattern: initial state gets all 4 mandatory fields editable, non-initial states get `"standard_fields": {}`.

- [ ] **Step 5: Update `test_booking_custom_field_permissions.py`**

Update `DEFINITION_WITH_CUSTOM_FIELDS`, `BOOKING_DEF`, and the inline definition in `test_create_template_with_invalid_role_in_custom_field` to use the new shape. For `DEFINITION_WITH_CUSTOM_FIELDS`:

```python
DEFINITION_WITH_CUSTOM_FIELDS = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin"]},
                "start_date": {"editable_by": ["Admin"]},
                "end_date": {"editable_by": ["Admin"]},
                "booking_type": {"editable_by": ["Admin"]},
            },
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "standard_fields": {},
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    },
}
```

Also update `BOOKING_DEF` similarly (remove `editable_fields`/`editable_by`, add `standard_fields` with mandatory fields in `draft` state).

For `test_create_template_with_invalid_role_in_custom_field`, update the inline `bad_def` to add mandatory `standard_fields` to the `draft` state (the test is only checking that invalid role in `custom_fields` is rejected, so `standard_fields` must be valid):

```python
"draft": {
    "standard_fields": {
        "project_name": {"editable_by": ["Admin"]},
        "start_date": {"editable_by": ["Admin"]},
        "end_date": {"editable_by": ["Admin"]},
        "booking_type": {"editable_by": ["Admin"]},
    },
    "custom_fields": {
        "my_field": {"editable_by": ["NotARealRole"]},
    },
}
```

Also update the pure-unit-test `DEFINITION` constant (used by `test_get_custom_field_permissions_*` functions) — these don't go through the API so they don't need mandatory fields, but `editable_fields`/`editable_by` keys are now ignored by Pydantic (extra fields). Those unit tests don't call `LifecycleDefinition.model_validate`, they call `get_custom_field_permissions` directly with a raw dict, so they don't need updating.

- [ ] **Step 6: Update `integration/test_bookings.py`, `integration/test_custom_fields.py`, `integration/test_events.py`**

Search for `editable_fields` in each file and update those `field_permissions` dicts to the new shape. Apply the same pattern: initial state gets all 4 mandatory fields editable, all other states get `"standard_fields": {}`.

- [ ] **Step 7: Run all updated test files to verify they pass**

```bash
cd backend && python -m pytest tests/test_booking_lifecycle.py tests/test_booking_transitions.py tests/test_booking_custom_field_permissions.py tests/integration/test_bookings.py tests/integration/test_custom_fields.py tests/integration/test_events.py -v
```

Expected: All previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add backend/tests/
git commit -m "test: update lifecycle template fixtures to new standard_fields shape"
```

---

## Task 3: Migration helper and lifecycle service cleanup

**Files:**
- Modify: `backend/app/services/booking_lifecycle_service.py`

Add `migrate_field_permissions`, remove `get_editable_fields`, call migration before save.

- [ ] **Step 1: Write failing migration tests**

Add to `backend/tests/test_booking_standard_field_permissions.py`:

```python
from app.services.booking_lifecycle_service import migrate_field_permissions


def test_migrate_old_shape_converts_to_standard_fields():
    """Old editable_fields/editable_by shape is converted per-field."""
    old = {
        "states": [{"key": "draft", "is_initial": True}],
        "field_permissions": {
            "draft": {
                "editable_fields": ["project_name", "start_date"],
                "editable_by": ["Admin", "Release Manager"],
                "custom_fields": {"release_notes": {"editable_by": ["Admin"]}},
            },
            "closed": {
                "editable_fields": [],
                "editable_by": [],
            },
        },
    }
    result = migrate_field_permissions(old)
    draft = result["field_permissions"]["draft"]
    assert draft["standard_fields"]["project_name"]["editable_by"] == ["Admin", "Release Manager"]
    assert draft["standard_fields"]["start_date"]["editable_by"] == ["Admin", "Release Manager"]
    # Fields NOT in editable_fields get empty editable_by
    assert draft["standard_fields"].get("notes", {}).get("editable_by", None) is None or \
           draft["standard_fields"].get("notes", {"editable_by": []})["editable_by"] == []
    # custom_fields preserved
    assert draft["custom_fields"]["release_notes"]["editable_by"] == ["Admin"]
    # editable_fields/editable_by removed
    assert "editable_fields" not in draft
    assert "editable_by" not in draft


def test_migrate_new_shape_is_noop():
    """Definition already using standard_fields is returned unchanged."""
    new = {
        "field_permissions": {
            "draft": {
                "standard_fields": {"project_name": {"editable_by": ["Admin"]}},
            },
        },
    }
    result = migrate_field_permissions(new)
    assert result["field_permissions"]["draft"]["standard_fields"]["project_name"]["editable_by"] == ["Admin"]
    assert "editable_fields" not in result["field_permissions"]["draft"]


def test_migrate_empty_definition():
    """Definition with no field_permissions is returned unchanged."""
    d = {"states": [], "transitions": [], "field_permissions": {}}
    result = migrate_field_permissions(d)
    assert result["field_permissions"] == {}


def test_migrate_mixed_shape():
    """Definition where some states are old shape and some are new shape — only old states converted."""
    mixed = {
        "field_permissions": {
            "draft": {
                "editable_fields": ["notes"],
                "editable_by": ["Admin"],
            },
            "submitted": {
                "standard_fields": {"project_name": {"editable_by": ["Admin"]}},
            },
        },
    }
    result = migrate_field_permissions(mixed)
    # draft converted
    assert "standard_fields" in result["field_permissions"]["draft"]
    assert "editable_fields" not in result["field_permissions"]["draft"]
    # submitted unchanged
    assert result["field_permissions"]["submitted"]["standard_fields"]["project_name"]["editable_by"] == ["Admin"]
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py::test_migrate_old_shape_converts_to_standard_fields -v
```

Expected: FAIL with `ImportError` (function doesn't exist yet).

- [ ] **Step 3: Implement `migrate_field_permissions` and remove `get_editable_fields`**

In `backend/app/services/booking_lifecycle_service.py`:

1. Remove the `get_editable_fields` function (lines ~108-115).

2. Add `migrate_field_permissions`:

```python
from app.api.v1.schemas.booking_lifecycle import VALID_STANDARD_FIELD_NAMES

def migrate_field_permissions(definition: dict) -> dict:
    """Convert old editable_fields/editable_by shape to standard_fields per-field shape.
    A definition is old-shape if ANY state entry in field_permissions contains 'editable_fields'.
    Every such state entry is converted; entries already in new shape are left untouched.
    Returns the mutated definition dict.
    Conversion rule: fields listed in editable_fields inherit editable_by;
    all other standard field names (from VALID_STANDARD_FIELD_NAMES) get editable_by: [].
    """
    field_perms = definition.get("field_permissions", {})
    for state_key, perm in field_perms.items():
        if "editable_fields" not in perm:
            continue  # already new shape
        old_editable_fields = perm.get("editable_fields", [])
        old_editable_by = perm.get("editable_by", [])
        # Iterate over ALL valid standard field names so no field is silently dropped
        standard_fields = {
            f: {"editable_by": old_editable_by if f in old_editable_fields else []}
            for f in VALID_STANDARD_FIELD_NAMES
        }
        new_perm = {"standard_fields": standard_fields}
        if "custom_fields" in perm:
            new_perm["custom_fields"] = perm["custom_fields"]
        field_perms[state_key] = new_perm
    return definition
```

3. Call `migrate_field_permissions` before save in `create_template`, `update_template`, and `copy_template`:

In `create_template` — before `template.definition = data.definition.model_dump()`:
```python
definition_dict = migrate_field_permissions(data.definition.model_dump())
template = BookingLifecycleTemplate(
    ...,
    definition=definition_dict,
)
```

In `update_template` — before `template.definition = data.definition.model_dump()`:
```python
template.definition = migrate_field_permissions(data.definition.model_dump())
```

In `copy_template` — wrap the deepcopy:
```python
definition=migrate_field_permissions(copy.deepcopy(original.definition)),
```

- [ ] **Step 4: Run migration tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py -k "migrate" -v
```

Expected: All 4 migration tests PASS.

- [ ] **Step 5: Remove `get_editable_fields` import from `booking_service.py`**

In `backend/app/services/booking_service.py`, remove `get_editable_fields` from the import of `booking_lifecycle_service`:

Before:
```python
from app.services.booking_lifecycle_service import (
    validate_transition,
    get_allowed_transitions,
    get_editable_fields,
    get_custom_field_permissions,
)
```

After:
```python
from app.services.booking_lifecycle_service import (
    validate_transition,
    get_allowed_transitions,
    get_custom_field_permissions,
)
```

- [ ] **Step 6: Run full test suite to verify nothing broken**

```bash
cd backend && python -m pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/booking_lifecycle_service.py backend/app/services/booking_service.py backend/tests/test_booking_standard_field_permissions.py
git commit -m "feat: add migrate_field_permissions and remove dead get_editable_fields"
```

---

## Task 4: Standard field permission helpers in booking_service

**Files:**
- Modify: `backend/app/services/booking_service.py`

Add `get_standard_field_permissions` (pure function) and `get_standard_field_perms_for_booking` (async, loads template).

- [ ] **Step 1: Write failing unit tests**

Add to `backend/tests/test_booking_standard_field_permissions.py`:

```python
from app.services.booking_lifecycle_service import get_custom_field_permissions
# get_standard_field_permissions is a pure function — import directly
from app.services.booking_service import get_standard_field_permissions

SF_DEFINITION = {
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin", "Developer"]},
                "start_date": {"editable_by": ["Admin"]},
                "end_date": {"editable_by": ["Admin"]},
                "booking_type": {"editable_by": ["Admin"]},
                "notes": {"editable_by": []},
            }
        },
        "submitted": {
            "standard_fields": {}
        },
    }
}


def test_get_standard_field_permissions_editable_role():
    """Admin in draft can edit project_name and start_date."""
    result = get_standard_field_permissions(SF_DEFINITION, "draft", "Admin")
    assert "project_name" in result
    assert "start_date" in result


def test_get_standard_field_permissions_non_editable_field():
    """notes has empty editable_by — not in result for any role."""
    result = get_standard_field_permissions(SF_DEFINITION, "draft", "Admin")
    assert "notes" not in result


def test_get_standard_field_permissions_role_without_access():
    """Developer in draft can edit project_name but not start_date."""
    result = get_standard_field_permissions(SF_DEFINITION, "draft", "Developer")
    assert "project_name" in result
    assert "start_date" not in result


def test_get_standard_field_permissions_non_initial_state():
    """submitted state has no standard_fields — empty set returned."""
    result = get_standard_field_permissions(SF_DEFINITION, "submitted", "Admin")
    assert result == set()


def test_get_standard_field_permissions_unknown_state():
    """State not in field_permissions returns empty set (fail-closed)."""
    result = get_standard_field_permissions(SF_DEFINITION, "nonexistent", "Admin")
    assert result == set()
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py::test_get_standard_field_permissions_editable_role -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `get_standard_field_permissions` in `booking_service.py`**

Add after the existing `get_custom_field_perms_for_booking` function:

```python
def get_standard_field_permissions(
    definition: dict, state_key: str, user_role: str
) -> set[str]:
    """Return the set of standard permission keys editable by user_role in state_key.
    Fail-closed: returns empty set if state not configured."""
    perm = definition.get("field_permissions", {}).get(state_key)
    if not perm:
        return set()
    standard_fields = perm.get("standard_fields", {})
    return {
        field_key
        for field_key, config in standard_fields.items()
        if user_role in config.get("editable_by", [])
    }
```

- [ ] **Step 4: Run unit tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py -k "get_standard_field_permissions" -v
```

Expected: All 5 unit tests PASS.

- [ ] **Step 5: Implement `get_standard_field_perms_for_booking` in `booking_service.py`**

Add after `get_standard_field_permissions`:

```python
from app.api.v1.schemas.booking_lifecycle import VALID_STANDARD_FIELD_NAMES

async def get_standard_field_perms_for_booking(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict[str, dict]:
    """Return editable status for all 7 standard fields for the booking's current state and user role.
    All 7 standard fields are always present in the response.
    Returns {"project_name": {"editable": True}, "start_date": {"editable": False}, ...}"""
    # Re-use the template-loading logic already in get_custom_field_perms_for_booking
    from sqlalchemy import select
    from app.db.models.booking_lifecycle import BookingType, BookingLifecycleTemplate
    bt_result = await db.execute(
        select(BookingType).where(BookingType.id == booking.booking_type_id)
    )
    bt = bt_result.scalar_one_or_none()
    if not bt:
        return {f: {"editable": False} for f in VALID_STANDARD_FIELD_NAMES}
    template_result = await db.execute(
        select(BookingLifecycleTemplate).where(BookingLifecycleTemplate.id == bt.lifecycle_template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        return {f: {"editable": False} for f in VALID_STANDARD_FIELD_NAMES}
    editable = get_standard_field_permissions(template.definition, booking.status, user_role)
    return {f: {"editable": f in editable} for f in VALID_STANDARD_FIELD_NAMES}
```

- [ ] **Step 6: Run full test suite to verify no regressions**

```bash
cd backend && python -m pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/booking_service.py backend/tests/test_booking_standard_field_permissions.py
git commit -m "feat: add get_standard_field_permissions and get_standard_field_perms_for_booking"
```

---

## Task 5: update_standard_fields service + endpoint

**Files:**
- Modify: `backend/app/services/booking_service.py`
- Modify: `backend/app/api/v1/bookings.py`

Add the `update_standard_fields` service function, the `PATCH /standard-fields` endpoint, and update `GET /{id}` to include `standard_field_permissions`.

The permission key `booking_type` maps to model column `booking_type_id`. The service accepts `booking_type_id` in the body and translates internally.

- [ ] **Step 1: Write failing integration tests**

Add to `backend/tests/test_booking_standard_field_permissions.py`:

```python
from httpx import AsyncClient

# Template definition with per-field standard field permissions
SF_TEMPLATE_DEF = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin"]},
                "start_date": {"editable_by": ["Admin"]},
                "end_date": {"editable_by": ["Admin"]},
                "booking_type": {"editable_by": ["Admin"]},
                "notes": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "standard_fields": {
                "notes": {"editable_by": ["Admin"]},
            },
        },
    },
}


async def _setup_sf_booking(client, auth_headers):
    """Create template, booking type, environment, and booking. Return booking_id."""
    tmpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "SF Template", "definition": SF_TEMPLATE_DEF},
    )
    assert tmpl.status_code == 201, tmpl.text
    template_id = tmpl.json()["id"]
    bt = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "SF Type", "lifecycle_template_id": template_id},
    )
    bt_id = bt.json()["id"]
    env = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "SFTestEnv", "environment_type": "testing"},
    )
    env_id = env.json()["id"]
    booking = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "SF Project",
            "start_date": "2026-04-01T09:00:00Z",
            "end_date": "2026-04-01T17:00:00Z",
            "booking_type_id": bt_id,
        },
    )
    assert booking.status_code == 201, booking.text
    return booking.json()["booking"]["id"]


@pytest.mark.asyncio
async def test_get_booking_includes_standard_field_permissions(client: AsyncClient, auth_headers: dict):
    """GET /bookings/{id} includes standard_field_permissions for all 7 fields."""
    booking_id = await _setup_sf_booking(client, auth_headers)
    resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "standard_field_permissions" in data
    sfp = data["standard_field_permissions"]
    # All 7 fields present
    for field in ["project_name", "start_date", "end_date", "booking_type", "notes", "exclusive_use", "context_tag"]:
        assert field in sfp, f"Missing field: {field}"
    # Admin in draft can edit project_name
    assert sfp["project_name"]["editable"] is True
    # exclusive_use has no editable_by configured → read-only
    assert sfp["exclusive_use"]["editable"] is False


@pytest.mark.asyncio
async def test_patch_standard_fields_updates_booking(client: AsyncClient, auth_headers: dict):
    """PATCH /bookings/{id}/standard-fields updates notes successfully."""
    booking_id = await _setup_sf_booking(client, auth_headers)
    resp = await client.patch(
        f"/api/v1/bookings/{booking_id}/standard-fields",
        headers=auth_headers,
        json={"notes": "updated notes"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notes"] == "updated notes"
    # Response includes standard_field_permissions
    assert "standard_field_permissions" in resp.json()


@pytest.mark.asyncio
async def test_patch_standard_fields_readonly_field_rejected(client: AsyncClient, auth_headers: dict):
    """PATCH /bookings/{id}/standard-fields returns 403 for a field with no editable roles."""
    booking_id = await _setup_sf_booking(client, auth_headers)
    # exclusive_use has no editable_by configured in the template
    resp = await client.patch(
        f"/api/v1/bookings/{booking_id}/standard-fields",
        headers=auth_headers,
        json={"exclusive_use": True},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_patch_standard_fields_unknown_field_rejected(client: AsyncClient, auth_headers: dict):
    """PATCH /bookings/{id}/standard-fields returns 403 for an unknown field name."""
    booking_id = await _setup_sf_booking(client, auth_headers)
    resp = await client.patch(
        f"/api/v1/bookings/{booking_id}/standard-fields",
        headers=auth_headers,
        json={"foobar": "invalid"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_patch_standard_fields_locked_after_transition(client: AsyncClient, auth_headers: dict):
    """After transition to submitted, project_name is read-only (not in submitted standard_fields)."""
    booking_id = await _setup_sf_booking(client, auth_headers)
    await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    resp = await client.patch(
        f"/api/v1/bookings/{booking_id}/standard-fields",
        headers=auth_headers,
        json={"project_name": "trying to change"},
    )
    assert resp.status_code == 403, resp.text
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py -k "asyncio" -v
```

Expected: FAIL (endpoint and service function don't exist yet).

- [ ] **Step 3: Implement `update_standard_fields` in `booking_service.py`**

```python
# Mapping from permission key to model column name (only differs for booking_type)
_STANDARD_FIELD_COLUMN_MAP = {
    "project_name": "project_name",
    "start_date": "start_date",
    "end_date": "end_date",
    "booking_type": "booking_type_id",
    "notes": "notes",
    "exclusive_use": "exclusive_use",
    "context_tag": "context_tag",
}

# Reverse map: body column name → permission key
_COLUMN_TO_PERMISSION_KEY = {v: k for k, v in _STANDARD_FIELD_COLUMN_MAP.items()}

async def update_standard_fields(
    db: AsyncSession, booking_id: int, values: dict, current_user
) -> "Booking":
    """Update standard fields on a booking subject to lifecycle permissions.
    values: dict of model column names e.g. {"booking_type_id": 3, "notes": "..."}.
    Raises HTTP 403 for unknown fields or fields not editable for this role in this state.
    """
    from fastapi import HTTPException, status as http_status
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    editable_keys = await get_standard_field_perms_for_booking(db, booking, current_user.role)
    # editable_keys maps permission_key -> {"editable": bool}

    for col_name in values:
        perm_key = _COLUMN_TO_PERMISSION_KEY.get(col_name)
        if perm_key is None or not editable_keys.get(perm_key, {}).get("editable", False):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"Field '{col_name}' is not editable in the current state for your role.",
            )

    for col_name, value in values.items():
        setattr(booking, col_name, value)

    await db.flush()
    await db.refresh(booking)
    return booking
```

- [ ] **Step 4: Add `PATCH /standard-fields` endpoint and update `GET /{id}` in `bookings.py`**

In `backend/app/api/v1/bookings.py`, add import:
```python
from app.services.booking_service import (
    ...,
    get_standard_field_perms_for_booking,
)
```

Update `get_booking` endpoint to also populate `standard_field_permissions`:

```python
@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    booking = await booking_service.get_booking(db, booking_id, current_user.active_tenant_id)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp
```

Add new endpoint after `update_custom_fields`:

```python
@router.patch("/{booking_id}/standard-fields", response_model=BookingResponse)
async def update_standard_fields(
    booking_id: int,
    values: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.update_standard_fields(db, booking_id, values, current_user)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp
```

- [ ] **Step 5: Run integration tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_booking_standard_field_permissions.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
cd backend && python -m pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/booking_service.py backend/app/api/v1/bookings.py backend/tests/test_booking_standard_field_permissions.py
git commit -m "feat: add update_standard_fields service and PATCH /bookings/{id}/standard-fields endpoint"
```

---

## Task 6: Frontend type updates

No automated tests. Verify by running `npm run build` which performs TypeScript type checking.

**Files:**
- Modify: `frontend/src/types/bookingLifecycle.ts`
- Modify: `frontend/src/types/booking.ts`

- [ ] **Step 1: Update `LifecycleFieldPermission` in `bookingLifecycle.ts`**

Replace:
```typescript
export interface LifecycleFieldPermission {
  editable_fields: string[];
  editable_by: string[];
  custom_fields?: Record<string, { editable_by: string[] }>;
}
```

With:
```typescript
export interface LifecycleFieldPermission {
  standard_fields: Record<string, { editable_by: string[] }>;
  custom_fields?: Record<string, { editable_by: string[] }>;
}
```

- [ ] **Step 2: Add `StandardFieldPermission` and `standard_field_permissions` to `booking.ts`**

Add interface:
```typescript
export interface StandardFieldPermission {
  editable: boolean;
}
```

In `BookingResponse`, add:
```typescript
standard_field_permissions?: Record<string, StandardFieldPermission>;
```

- [ ] **Step 3: Add `updateStandardFields` to `bookingService.ts`**

```typescript
updateStandardFields: (id: number, values: Record<string, unknown>): Promise<BookingResponse> =>
  api.patch(`/bookings/${id}/standard-fields`, values).then((r) => r.data),
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | head -30
```

Expected: Build succeeds (or fails only on pre-existing errors, not new ones from our changes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/bookingLifecycle.ts frontend/src/types/booking.ts frontend/src/services/bookingService.ts
git commit -m "feat: update frontend types and service for standard field permissions"
```

---

## Task 7: Lifecycle editor UI — standard fields section

**File:**
- Modify: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`

- [ ] **Step 1: Add `STANDARD_FIELDS` constant and update `FieldPermState`**

At the top of the file, add:
```typescript
const STANDARD_FIELDS = [
  { key: 'project_name', label: 'Project Name', mandatory: true },
  { key: 'start_date', label: 'Start Date', mandatory: true },
  { key: 'end_date', label: 'End Date', mandatory: true },
  { key: 'booking_type', label: 'Booking Type', mandatory: true },
  { key: 'notes', label: 'Notes', mandatory: false },
  { key: 'exclusive_use', label: 'Exclusive Use', mandatory: false },
  { key: 'context_tag', label: 'Context Tag', mandatory: false },
] as const;
```

Replace `FieldPermState`:
```typescript
interface FieldPermState {
  standard_fields: Record<string, { editable_by: string[] }>;
  custom_fields: Record<string, { editable_by: string[] }>;
}
```

- [ ] **Step 2: Update `handleEditOpen` with migration shim**

Replace the `fp` population loop inside `handleEditOpen`:

```typescript
const fp: Record<string, FieldPermState> = {};
for (const [stateKey, perm] of Object.entries(template.definition.field_permissions ?? {})) {
  // Migration shim: handle old editable_fields/editable_by shape
  const rawPerm = perm as Record<string, unknown>;
  if (rawPerm.editable_fields !== undefined) {
    const oldEditableBy = (rawPerm.editable_by as string[]) ?? [];
    const oldEditableFields = (rawPerm.editable_fields as string[]) ?? [];
    fp[stateKey] = {
      standard_fields: Object.fromEntries(
        STANDARD_FIELDS.map((f) => [
          f.key,
          { editable_by: oldEditableFields.includes(f.key) ? oldEditableBy : [] },
        ])
      ),
      custom_fields: (rawPerm.custom_fields as Record<string, { editable_by: string[] }>) ?? {},
    };
  } else {
    fp[stateKey] = {
      standard_fields: (perm.standard_fields as Record<string, { editable_by: string[] }>) ?? {},
      custom_fields: (perm.custom_fields as Record<string, { editable_by: string[] }>) ?? {},
    };
  }
}
setFieldPerms(fp);
```

- [ ] **Step 3: Update `handleSave` to write `standard_fields`**

In `handleSave`, replace the `field_permissions` build:

```typescript
field_permissions: Object.fromEntries(
  stateKeys.map((key) => {
    const perm = fieldPerms[key] ?? { standard_fields: {}, custom_fields: {} };
    return [key, { standard_fields: perm.standard_fields, custom_fields: perm.custom_fields }];
  })
),
```

- [ ] **Step 4: Add mandatory fields validation to `validate()`**

In the `validate()` function, after existing checks, add:

```typescript
// Mandatory standard fields must have at least one editable role in the initial state
const initialState = states.find((s) => s.is_initial);
if (initialState) {
  const initKey = initialState.key.trim();
  const initPerm = fieldPerms[initKey] ?? { standard_fields: {}, custom_fields: {} };
  const mandatoryFields = STANDARD_FIELDS.filter((f) => f.mandatory);
  for (const f of mandatoryFields) {
    const sf = initPerm.standard_fields[f.key];
    if (!sf || sf.editable_by.length === 0) {
      return `Mandatory field "${f.label}" in initial state "${initialState.label}" must have at least one editable role.`;
    }
  }
}
```

- [ ] **Step 5: Replace Field Permissions UI section**

Find the `{/* Field Permissions */}` section and replace its content. For each state block, render Standard Fields first (always all 7, no checkbox), then Custom Fields (unchanged):

```tsx
{/* Field Permissions */}
<Box>
  <Typography variant="subtitle2" sx={{ mb: 1 }}>Field Permissions (per state)</Typography>
  {stateKeys.length === 0 ? (
    <Typography variant="body2" color="text.secondary">Add states first.</Typography>
  ) : stateKeys.map((stateKey) => {
    const perm = fieldPerms[stateKey] ?? { standard_fields: {}, custom_fields: {} };
    const cfPerms = perm.custom_fields ?? {};
    return (
      <Box key={stateKey} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, mb: 1 }}>
        <Typography variant="caption" fontWeight="bold" color="text.primary">{stateKey}</Typography>

        {/* Standard Fields — always shown, all 7 */}
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">Standard Fields</Typography>
          {STANDARD_FIELDS.map((fieldDef) => {
            const sf = perm.standard_fields[fieldDef.key] ?? { editable_by: [] };
            const editableBy = sf.editable_by;
            return (
              <Box key={fieldDef.key} sx={{ ml: 1, mt: 0.5 }}>
                <Typography variant="caption" sx={{ display: 'inline-block', width: 130, color: 'text.primary' }}>
                  {fieldDef.label}{fieldDef.mandatory ? ' *' : ''}
                </Typography>
                {editableBy.length === 0 ? (
                  <Typography variant="caption" color="text.disabled" sx={{ fontStyle: 'italic' }}>
                    read-only in this state
                  </Typography>
                ) : null}
                <Box sx={{ display: 'inline-flex', gap: 0.5, flexWrap: 'wrap', ml: editableBy.length === 0 ? 0 : 0 }}>
                  {ROLES.map((role) => (
                    <Chip
                      key={role}
                      label={role}
                      size="small"
                      clickable
                      color={editableBy.includes(role) ? 'primary' : 'default'}
                      variant={editableBy.includes(role) ? 'filled' : 'outlined'}
                      onClick={() => {
                        setFieldPerms((fp) => {
                          const statePerm = fp[stateKey] ?? { standard_fields: {}, custom_fields: {} };
                          const current = statePerm.standard_fields[fieldDef.key]?.editable_by ?? [];
                          return {
                            ...fp,
                            [stateKey]: {
                              ...statePerm,
                              standard_fields: {
                                ...statePerm.standard_fields,
                                [fieldDef.key]: {
                                  editable_by: current.includes(role)
                                    ? current.filter((r) => r !== role)
                                    : [...current, role],
                                },
                              },
                            },
                          };
                        });
                      }}
                    />
                  ))}
                </Box>
              </Box>
            );
          })}
        </Box>

        {/* Custom Fields — unchanged */}
        {customFieldDefs.length > 0 && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">Custom Fields</Typography>
            {customFieldDefs.map((defn) => {
              const included = defn.field_key in cfPerms;
              const editableBy = cfPerms[defn.field_key]?.editable_by ?? [];
              return (
                <Box key={defn.field_key} sx={{ ml: 1, mt: 0.5 }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={included}
                        onChange={(e) => {
                          setFieldPerms((fp) => {
                            const statePerm = fp[stateKey] ?? { standard_fields: {}, custom_fields: {} };
                            const cf = { ...statePerm.custom_fields };
                            if (e.target.checked) {
                              cf[defn.field_key] = { editable_by: [] };
                            } else {
                              delete cf[defn.field_key];
                            }
                            return { ...fp, [stateKey]: { ...statePerm, custom_fields: cf } };
                          });
                        }}
                      />
                    }
                    label={defn.label}
                  />
                  {included && (
                    <Box sx={{ ml: 3, display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.5 }}>
                      {ROLES.map((role) => (
                        <Chip
                          key={role}
                          label={role}
                          size="small"
                          clickable
                          color={editableBy.includes(role) ? 'primary' : 'default'}
                          variant={editableBy.includes(role) ? 'filled' : 'outlined'}
                          onClick={() => {
                            setFieldPerms((fp) => {
                              const statePerm = fp[stateKey] ?? { standard_fields: {}, custom_fields: {} };
                              const cf = { ...statePerm.custom_fields };
                              const current = cf[defn.field_key]?.editable_by ?? [];
                              cf[defn.field_key] = {
                                editable_by: current.includes(role)
                                  ? current.filter((r) => r !== role)
                                  : [...current, role],
                              };
                              return { ...fp, [stateKey]: { ...statePerm, custom_fields: cf } };
                            });
                          }}
                        />
                      ))}
                    </Box>
                  )}
                </Box>
              );
            })}
          </Box>
        )}
      </Box>
    );
  })}
</Box>
```

- [ ] **Step 6: Verify TypeScript compiles and test manually**

```bash
cd frontend && npm run build 2>&1 | head -30
```

Then start the dev server and open the lifecycle template editor:
```bash
cd frontend && npm run dev
```

- Open http://localhost:5173 → Admin → Lifecycle Templates → New Template
- Add two states (one initial), add a transition
- Verify the Field Permissions section shows all 7 standard fields per state
- Verify clicking role chips toggles them
- Try saving without a role on a mandatory field — should show validation error
- Try saving with all mandatory fields covered — should succeed

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/admin/LifecycleTemplatesPanel.tsx
git commit -m "feat: add standard fields editor to lifecycle template field permissions UI"
```

---

## Task 8: Booking detail — standard fields read-only gating

**Files:**
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

The booking detail page currently shows all standard fields as read-only display text. We add an "Edit Standard Fields" button that appears when at least one standard field is editable for the current user, opening a dialog with editable fields.

- [ ] **Step 1: Add state and handler for standard fields edit**

In `BookingDetail.tsx`, alongside the existing custom fields state, add:

```typescript
const [editingStandardFields, setEditingStandardFields] = useState(false)
const [sfEditValues, setSfEditValues] = useState<Record<string, unknown>>({})
const [sfSaving, setSfSaving] = useState(false)
```

Add a `STANDARD_FIELD_LABELS` map (for display in the edit dialog):
```typescript
const STANDARD_FIELD_LABELS: Record<string, string> = {
  project_name: 'Project Name',
  start_date: 'Start Date',
  end_date: 'End Date',
  booking_type_id: 'Booking Type',
  notes: 'Notes',
  exclusive_use: 'Exclusive Use',
  context_tag: 'Context Tag',
}

// Map from permission key to the body key the PATCH endpoint accepts
const SF_PERM_TO_BODY_KEY: Record<string, string> = {
  project_name: 'project_name',
  start_date: 'start_date',
  end_date: 'end_date',
  booking_type: 'booking_type_id',
  notes: 'notes',
  exclusive_use: 'exclusive_use',
  context_tag: 'context_tag',
}
```

- [ ] **Step 2: Add "Edit Standard Fields" button to the booking details Paper**

In the booking details `Paper` section, after the grid, add:

```tsx
{(() => {
  const sfp = booking.standard_field_permissions ?? {};
  const hasEditable = Object.values(sfp).some((p) => p.editable);
  if (!hasEditable) return null;
  return (
    <Box sx={{ mt: 1.5, display: 'flex', justifyContent: 'flex-end' }}>
      <Button
        size="small"
        onClick={() => {
          const editableKeys = Object.entries(sfp)
            .filter(([, p]) => p.editable)
            .map(([permKey]) => SF_PERM_TO_BODY_KEY[permKey]);
          setSfEditValues(
            Object.fromEntries(
              editableKeys.map((col) => [col, (booking as Record<string, unknown>)[col] ?? ''])
            )
          );
          setEditingStandardFields(true);
        }}
      >
        Edit
      </Button>
    </Box>
  );
})()}
```

- [ ] **Step 3: Add standard fields edit dialog**

After the custom fields edit dialog, add:

```tsx
{/* Edit Standard Fields Dialog */}
<Dialog open={editingStandardFields} onClose={() => setEditingStandardFields(false)} maxWidth="sm" fullWidth>
  <DialogTitle>Edit Booking Details</DialogTitle>
  <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
    {Object.entries(sfEditValues).map(([colKey, value]) => (
      <TextField
        key={colKey}
        label={STANDARD_FIELD_LABELS[colKey] ?? colKey}
        value={value as string}
        onChange={(e) => setSfEditValues((prev) => ({ ...prev, [colKey]: e.target.value }))}
        size="small"
        fullWidth
      />
    ))}
  </DialogContent>
  <DialogActions>
    <Button onClick={() => setEditingStandardFields(false)}>Cancel</Button>
    <Button
      variant="contained"
      disabled={sfSaving}
      onClick={async () => {
        setSfSaving(true);
        try {
          const updated = await bookingService.updateStandardFields(bookingId, sfEditValues);
          setBooking(updated);
          setEditingStandardFields(false);
        } catch (err: unknown) {
          const msg =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Save failed';
          setError(msg);
        } finally {
          setSfSaving(false);
        }
      }}
    >
      {sfSaving ? 'Saving...' : 'Save'}
    </Button>
  </DialogActions>
</Dialog>
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | head -30
```

Expected: No new TypeScript errors.

- [ ] **Step 5: Manual smoke test**

Start backend + frontend:
```bash
# Terminal 1
cd backend && uvicorn app.main:app --reload

# Terminal 2
cd frontend && npm run dev
```

1. Log in as admin (admin / admin123, tenant: demo)
2. Go to Admin → Lifecycle Templates, create or edit a template
3. Verify Standard Fields section shows all 7 fields with role chips in each state
4. Configure project_name and notes as editable by Admin in the initial state; leave start_date read-only
5. Create a booking using that template
6. Open the booking detail → verify "Edit" button appears
7. Click Edit → only project_name and notes appear in the dialog
8. Change project_name → save → verify the booking updates
9. Try directly calling `PATCH /api/v1/bookings/{id}/standard-fields` with `{"start_date": "..."}` (via browser console or curl) → expect 403

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "feat: add standard fields edit to booking detail page"
```

---

## Done

All 8 tasks complete. The feature is fully implemented:
- Backend schema enforces per-field role config for standard fields
- Backend enforces permissions on `PATCH /bookings/{id}/standard-fields`
- `GET /bookings/{id}` returns `standard_field_permissions` for all 7 fields
- Lifecycle template editor shows and configures standard field permissions
- Booking detail page gates standard field editing based on API response
