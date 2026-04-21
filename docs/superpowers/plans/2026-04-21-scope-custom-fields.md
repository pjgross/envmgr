# Scope Item Custom Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let tenant admins define custom fields on scope items (`ReleaseChange`), optionally scoped to a specific `change_kind` (story / defect / task / spike), with backend validation and frontend render pluggable through the existing `CustomFieldDefinition` infrastructure.

**Architecture:** Reuse the existing `custom_field_definition` table's `entity_type` + nullable `entity_subtype`. Add `"release_change"` to `VALID_ENTITY_TYPES`. `entity_subtype IS NULL` → field applies to every kind; `entity_subtype = "defect"` (etc.) → field applies only to that kind. A thin service helper `list_definitions_for_subtype` returns the visible set; `release_scope_service.create_change` / `update_change` use it to feed `validate_custom_fields`. Frontend: add an "Any / story / defect / task / spike" subtype select to the admin dialog when `entity_type="release_change"`; extend `ScopeItemDialog` with a `<CustomFieldsSection />` whose definitions list filters reactively against the current `changeKind`.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest-asyncio (SQLite in-memory), React 18, Redux Toolkit, MUI v5, TypeScript strict.

**Spec:** `docs/superpowers/specs/2026-04-21-scope-custom-fields-design.md`.

---

## Conventions (must follow — per `CLAUDE.md`)

- Tenant scoping: `current_user.active_tenant_id`.
- Services: no `db.commit()`. Use `db.flush()` for IDs.
- No `native_enum=True`. No new migrations — this plan does not touch the schema.
- Branch: `feature/scope-custom-fields` (already created). Commits per step.
- Tests: from `backend/` run with `uv run pytest ...`. Frontend typecheck: `cd frontend && npx tsc --noEmit`.
- `main` is protected — user drives the GitLab MR flow. Do NOT open an MR automatically.

## File structure

**Backend — modify only:**
- `backend/app/api/v1/schemas/custom_field.py:9-16` — add `"release_change"` to `VALID_ENTITY_TYPES`.
- `backend/app/services/custom_field_service.py` — append `list_definitions_for_subtype(...)`.
- `backend/app/services/release_scope_service.py:123-167, 170-213` — call validation on create + update.
- `backend/tests/integration/test_custom_fields.py` — extend for `release_change` entity_type round-trip.
- `backend/tests/services/test_release_scope_service.py` — extend for validation cases.
- `backend/tests/test_custom_field_entity_subtype.py` — extend with a `release_change` case.
- `backend/tests/services/test_custom_field_service.py` (may be new — check first) or append to an existing unit test file for `list_definitions_for_subtype`.

**Frontend — modify only:**
- `frontend/src/types/customField.ts:1` — add `"release_change"` to `EntityType` union.
- `frontend/src/components/admin/CustomFieldDefinitionDialog.tsx` — expose subtype select for `release_change` entity_type; populate options from a hardcoded `CHANGE_KINDS` constant.
- `frontend/src/components/admin/CustomFieldDefinitionManager.tsx` — show the "Scope" column when `entityType === 'release_change'` (same pattern as `'release'` at line 97).
- `frontend/src/pages/admin/TenantCustomFields.tsx` (or whichever page mounts the manager) — add a "Release scope item" entry to the entity-type picker / tab bar.
- `frontend/src/components/releases/ScopeItemDialog.tsx` — fetch `release_change` definitions, reactively filter by `changeKind`, render `<CustomFieldsSection />`, include `custom_fields` in create/update payloads.

**No new files.** Every change is an edit or an append.

---

## Task 1: Allow `"release_change"` as an entity_type

**Files:**
- Modify: `backend/app/api/v1/schemas/custom_field.py`
- Extend: `backend/tests/integration/test_custom_fields.py` (add one test case)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_custom_fields.py`:

```python
@pytest.mark.asyncio
async def test_release_change_entity_type_is_accepted(client, auth_headers):
    """Admin can create a custom field definition for entity_type='release_change'."""
    resp = await client.post(
        "/api/v1/tenant/fields",
        headers=auth_headers,
        json={
            "entity_type": "release_change",
            "label": "Theme",
            "field_type": "text",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["entity_type"] == "release_change"
    assert data["field_key"] == "theme"
    assert data["entity_subtype"] is None


@pytest.mark.asyncio
async def test_release_change_entity_type_accepts_subtype(client, auth_headers):
    """Admin can scope a release_change field to a specific change_kind."""
    resp = await client.post(
        "/api/v1/tenant/fields",
        headers=auth_headers,
        json={
            "entity_type": "release_change",
            "entity_subtype": "defect",
            "label": "Production bug reference",
            "field_type": "text",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["entity_subtype"] == "defect"
```

- [ ] **Step 2: Run — verify the failure**

Run: `cd backend && uv run pytest tests/integration/test_custom_fields.py::test_release_change_entity_type_is_accepted tests/integration/test_custom_fields.py::test_release_change_entity_type_accepts_subtype -v`

Expected: both fail with `entity_type must be one of: ...` (422).

- [ ] **Step 3: Extend the allowlist**

Edit `backend/app/api/v1/schemas/custom_field.py`. Replace the `VALID_ENTITY_TYPES` set (lines 9-16) with:

```python
VALID_ENTITY_TYPES = {
    "system",
    "subsystem",
    "environment",
    "booking",
    "change_request",
    "release",
    "release_change",
}
```

- [ ] **Step 4: Run — verify both pass + no regressions**

Run: `cd backend && uv run pytest tests/integration/test_custom_fields.py -v`

Expected: all existing cases still pass; both new cases pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/custom_field.py backend/tests/integration/test_custom_fields.py
git commit -m "feat(scope): allow release_change as a custom_field entity_type"
```

---

## Task 2: `list_definitions_for_subtype` service helper

**Files:**
- Modify: `backend/app/services/custom_field_service.py` (append)
- Create OR extend: `backend/tests/services/test_custom_field_service.py` — if the file doesn't already exist, create it; otherwise append.

Before writing the test, confirm the file's state:

Run: `ls backend/tests/services/test_custom_field_service.py && head -5 backend/tests/services/test_custom_field_service.py`

If the file exists, APPEND the test below. If not, CREATE it with the test as the first content (plus imports).

- [ ] **Step 1: Write the failing test**

Test body (wrap with file-level imports if creating new):

```python
import pytest
from app.db.models.custom_field import CustomFieldDefinition
from app.services import custom_field_service


@pytest.mark.asyncio
async def test_list_definitions_for_subtype_returns_unscoped_and_matching(
    db_session, tenant
):
    """list_definitions_for_subtype returns definitions with entity_subtype IS NULL
    OR entity_subtype == the given subtype. Non-matching subtypes are excluded."""
    any_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="theme", label="Theme", field_type="text", required=False, display_order=0,
    )
    defect_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text", required=False, display_order=1,
    )
    story_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="story",
        field_key="story_points", label="Points", field_type="number", required=False, display_order=2,
    )
    db_session.add_all([any_def, defect_def, story_def])
    await db_session.flush()

    defect_rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", "defect",
    )
    assert {d.field_key for d in defect_rows} == {"theme", "prod_bug_ref"}

    story_rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", "story",
    )
    assert {d.field_key for d in story_rows} == {"theme", "story_points"}


@pytest.mark.asyncio
async def test_list_definitions_for_subtype_ignores_soft_deleted(
    db_session, tenant
):
    from datetime import datetime, timezone
    d = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="retired", label="Retired", field_type="text", required=False, display_order=0,
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(d)
    await db_session.flush()
    rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", "defect",
    )
    assert rows == []


@pytest.mark.asyncio
async def test_list_definitions_for_subtype_null_subtype_returns_only_unscoped(
    db_session, tenant
):
    """Calling with subtype=None returns ONLY entity_subtype IS NULL rows."""
    any_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="theme", label="Theme", field_type="text", required=False, display_order=0,
    )
    defect_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text", required=False, display_order=1,
    )
    db_session.add_all([any_def, defect_def])
    await db_session.flush()
    rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", None,
    )
    assert [r.field_key for r in rows] == ["theme"]
```

- [ ] **Step 2: Run — verify AttributeError**

Run: `cd backend && uv run pytest tests/services/test_custom_field_service.py -v`

Expected: AttributeError — `list_definitions_for_subtype` does not exist.

- [ ] **Step 3: Implement the helper**

Append to `backend/app/services/custom_field_service.py` (after `list_definitions` around line 40):

```python
async def list_definitions_for_subtype(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str,
    subtype: Optional[str],
) -> list[CustomFieldDefinition]:
    """Return active definitions for entity_type where entity_subtype IS NULL
    OR (if subtype is not None) entity_subtype == subtype.

    When subtype is None, returns only unscoped ('applies to all') definitions.
    Ordered by display_order, id — matches list_definitions.
    """
    from sqlalchemy import or_

    conditions = [CustomFieldDefinition.entity_subtype.is_(None)]
    if subtype is not None:
        conditions.append(CustomFieldDefinition.entity_subtype == subtype)

    result = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.deleted_at.is_(None),
            or_(*conditions),
        ).order_by(CustomFieldDefinition.display_order, CustomFieldDefinition.id)
    )
    return list(result.scalars().all())
```

The `or_` import lives inside the function to avoid disturbing the module-top imports; it's a single-site use.

- [ ] **Step 4: Run — verify 3 passed**

Run: `cd backend && uv run pytest tests/services/test_custom_field_service.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/custom_field_service.py backend/tests/services/test_custom_field_service.py
git commit -m "feat(scope): list_definitions_for_subtype service helper"
```

---

## Task 3: Validate custom fields on scope item create + update

**Files:**
- Modify: `backend/app/services/release_scope_service.py:123-167, 170-213`
- Extend: `backend/tests/services/test_release_scope_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/services/test_release_scope_service.py` (adjust imports if needed — the file already imports service + models; look at the existing test functions for the fixture pattern and follow it):

```python
import pytest
from app.db.models.custom_field import CustomFieldDefinition
from app.api.v1.schemas.release_change import ReleaseChangeCreate, ReleaseChangeUpdate
from app.services import release_scope_service


@pytest.mark.asyncio
async def test_create_change_persists_valid_custom_fields(
    db_session, tenant, user, release_lifecycle_template,
):
    from app.db.models.release import Release
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    # Define an unscoped field
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="theme", label="Theme", field_type="text", required=False, display_order=0,
    ))
    await db_session.flush()

    change = await release_scope_service.create_change(
        db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
        data=ReleaseChangeCreate(
            title="X", change_kind="story",
            custom_fields={"theme": "Onboarding"},
        ),
    )
    assert change.custom_fields == {"theme": "Onboarding"}


@pytest.mark.asyncio
async def test_create_change_enforces_required_visible_field(
    db_session, tenant, user, release_lifecycle_template,
):
    """A defect-only required field is enforced on defect items."""
    from app.db.models.release import Release
    from fastapi import HTTPException
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text",
        required=True, display_order=0,
    ))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await release_scope_service.create_change(
            db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
            data=ReleaseChangeCreate(title="X", change_kind="defect"),
        )
    assert exc.value.status_code == 422
    assert "prod_bug_ref" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_change_ignores_required_field_for_other_subtype(
    db_session, tenant, user, release_lifecycle_template,
):
    """A required field on entity_subtype='defect' is NOT required for story items."""
    from app.db.models.release import Release
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text",
        required=True, display_order=0,
    ))
    await db_session.flush()

    # Should NOT raise
    change = await release_scope_service.create_change(
        db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
        data=ReleaseChangeCreate(title="Y", change_kind="story"),
    )
    assert change.id is not None


@pytest.mark.asyncio
async def test_update_change_validates_type(
    db_session, tenant, user, release_lifecycle_template,
):
    from app.db.models.release import Release
    from fastapi import HTTPException
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="points", label="Points", field_type="number",
        required=False, display_order=0,
    ))
    await db_session.flush()
    change = await release_scope_service.create_change(
        db_session, release.id, tenant.id, user.id,
        ReleaseChangeCreate(title="Z", change_kind="story"),
    )

    with pytest.raises(HTTPException) as exc:
        await release_scope_service.update_change(
            db_session, change_id=change.id, tenant_id=tenant.id, user_id=user.id,
            data=ReleaseChangeUpdate(custom_fields={"points": "not-a-number"}),
        )
    assert exc.value.status_code == 422
```

If the test file's existing `create_change` / `update_change` calls use different positional args than the ones shown here, adjust the fixtures above to match — the service signature uses `db, release_id, data, tenant_id, user_id` in the module today. (In tests I've written as keyword args for clarity.)

- [ ] **Step 2: Run — all four fail**

Run: `cd backend && uv run pytest tests/services/test_release_scope_service.py -v`

Expected: the four new tests fail (no validation yet).

- [ ] **Step 3: Wire validation into `create_change`**

Edit `backend/app/services/release_scope_service.py`. Add this import near the top (look for the existing service imports; place alongside `publish_event`):

```python
from app.services import custom_field_service
```

In `create_change` (lines ~123-167), add just above `change = ReleaseChange(...)`:

```python
    # Validate custom_fields against definitions for this change_kind.
    defs = await custom_field_service.list_definitions_for_subtype(
        db, tenant_id, "release_change", data.change_kind,
    )
    visible_keys = {d.field_key for d in defs}
    await custom_field_service.validate_custom_fields(
        db, tenant_id, "release_change", data.custom_fields, visible_field_keys=visible_keys,
    )
```

- [ ] **Step 4: Wire validation into `update_change`**

In `update_change` (lines ~170-213), after the `_JIRA_READONLY_FIELDS` check and before `for field, value in update_data.items():`, add:

```python
    # If custom_fields are being updated, re-validate against the current change_kind.
    if "custom_fields" in update_data:
        defs = await custom_field_service.list_definitions_for_subtype(
            db, tenant_id, "release_change", change.change_kind,
        )
        visible_keys = {d.field_key for d in defs}
        await custom_field_service.validate_custom_fields(
            db, tenant_id, "release_change", update_data["custom_fields"],
            visible_field_keys=visible_keys,
        )
```

- [ ] **Step 5: Run — 4 pass, existing tests still green**

Run: `cd backend && uv run pytest tests/services/test_release_scope_service.py tests/integration/test_custom_fields.py -v`

Expected: all pass. Note count for comparison in Step 7.

- [ ] **Step 6: Run full backend suite as safety net**

Run: `cd backend && uv run pytest -q`

Expected: all tests pass. If any previously-green test breaks, stop and investigate — do not suppress.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/release_scope_service.py backend/tests/services/test_release_scope_service.py
git commit -m "feat(scope): validate custom_fields on scope item create + update"
```

---

## Task 4: Admin UI — expose release_change entity_type with subtype select

**Files:**
- Modify: `frontend/src/types/customField.ts`
- Modify: `frontend/src/components/admin/CustomFieldDefinitionDialog.tsx`
- Modify: `frontend/src/components/admin/CustomFieldDefinitionManager.tsx`
- Modify: wherever the admin page picks entity_type (search below)

- [ ] **Step 1: Add `"release_change"` to the `EntityType` union**

Edit `frontend/src/types/customField.ts` line 1. Replace:

```ts
export type EntityType = 'system' | 'subsystem' | 'environment' | 'booking' | 'change_request' | 'release';
```

with:

```ts
export type EntityType = 'system' | 'subsystem' | 'environment' | 'booking' | 'change_request' | 'release' | 'release_change';
```

- [ ] **Step 2: Support subtype select for release_change in the dialog**

Edit `frontend/src/components/admin/CustomFieldDefinitionDialog.tsx`.

Replace line 71 (`const showSubtypeField = entityType === 'release';`) with:

```ts
const CHANGE_KINDS = ['story', 'defect', 'task', 'spike'] as const;
const showSubtypeField = entityType === 'release' || entityType === 'release_change';
```

In the existing subtype `TextField select` element in the dialog, the current `MenuItem` list uses `releaseTemplates` for `entity_type === 'release'`. We need to branch on `entityType` — for `release`, keep using `releaseTemplates`; for `release_change`, use `CHANGE_KINDS`.

Find the JSX for the subtype select (look for `showSubtypeField &&` — it wraps a MUI `TextField select` with `value={entitySubtype}`). Replace the MenuItem children with a conditional. Concrete edit:

```tsx
{showSubtypeField && (
  <TextField
    select
    label="Scope (optional)"
    value={entitySubtype}
    onChange={(e) => setEntitySubtype(e.target.value)}
    fullWidth
    helperText="Leave blank to apply to all types"
  >
    <MenuItem value="">All types</MenuItem>
    {entityType === 'release' &&
      releaseTemplates.map((t) => (
        <MenuItem key={t.name} value={t.name}>{t.name}</MenuItem>
      ))}
    {entityType === 'release_change' &&
      CHANGE_KINDS.map((k) => (
        <MenuItem key={k} value={k}>{k}</MenuItem>
      ))}
  </TextField>
)}
```

Also update the `useEffect` that fetches `releaseTemplates` to only fire for `entity_type === 'release'` — the templates endpoint is irrelevant to `release_change`. Change:

```ts
useEffect(() => {
  if (open && showSubtypeField) {
    dispatch(fetchLifecycleTemplates('release'));
  }
}, [open, showSubtypeField, dispatch]);
```

to:

```ts
useEffect(() => {
  if (open && entityType === 'release') {
    dispatch(fetchLifecycleTemplates('release'));
  }
}, [open, entityType, dispatch]);
```

- [ ] **Step 3: Show the "Scope" column for release_change in the manager**

Edit `frontend/src/components/admin/CustomFieldDefinitionManager.tsx`. Replace every occurrence of `entityType === 'release'` in the table JSX (lines 97 and 113 per grep) with `(entityType === 'release' || entityType === 'release_change')`.

Run `grep -n "entityType === 'release'" frontend/src/components/admin/CustomFieldDefinitionManager.tsx` first to confirm only those two lines; make both substitutions.

- [ ] **Step 4: Add the entity tab to the admin page**

Find the page that mounts `<CustomFieldDefinitionManager />`:

Run: `grep -rn "CustomFieldDefinitionManager" frontend/src/pages frontend/src/components | grep -v node_modules | head -10`

Open the component(s) that pick `entityType`. Where the current entity-type picker renders (likely a Tabs or a Select), add a new entry labelled **"Release scope item"** with value `"release_change"`. Keep positioning next to `"release"`.

If the picker is a `<Tabs>`:

```tsx
<Tab label="Release scope item" value="release_change" />
```

If it's a `<Select>`:

```tsx
<MenuItem value="release_change">Release scope item</MenuItem>
```

- [ ] **Step 5: Typecheck + smoke-run**

Run: `cd frontend && npx tsc --noEmit`

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/customField.ts frontend/src/components/admin/CustomFieldDefinitionDialog.tsx frontend/src/components/admin/CustomFieldDefinitionManager.tsx frontend/src/pages/admin/
git commit -m "feat(scope): admin UI for release_change custom fields + subtype select"
```

If the edited admin page lives somewhere outside `frontend/src/pages/admin/`, adjust the `git add` path accordingly (or use `git add -u` after confirming no unrelated files are staged).

---

## Task 5: ScopeItemDialog renders CustomFieldsSection scoped by change_kind

**Files:**
- Modify: `frontend/src/components/releases/ScopeItemDialog.tsx`

- [ ] **Step 1: Wire fetch + filter + render + payload**

Replace the entire body of `ScopeItemDialog.tsx` — current content is at `frontend/src/components/releases/ScopeItemDialog.tsx:1-167`. New content:

```tsx
/**
 * ScopeItemDialog — create or edit a scope item (release change).
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import type { AppDispatch, RootState } from '../../store';
import {
  createReleaseChange,
  updateReleaseChange,
} from '../../store/releaseSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import CustomFieldsSection from '../CustomFieldsSection';
import type { ReleaseChangeResponse } from '../../types/releaseChange';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  item?: ReleaseChangeResponse | null;
}

const CHANGE_KINDS = ['story', 'defect', 'task', 'spike'];

export default function ScopeItemDialog({ open, onClose, releaseId, item }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const isEdit = !!item;

  const [title, setTitle] = useState('');
  const [changeKind, setChangeKind] = useState('story');
  const [externalKey, setExternalKey] = useState('');
  const [description, setDescription] = useState('');
  const [externalStatus, setExternalStatus] = useState('');
  const [customFields, setCustomFields] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);

  const allDefs = useSelector(
    (s: RootState) => s.customField.definitions['release_change'] ?? []
  );
  const visibleDefs = useMemo(
    () => allDefs.filter((d) => d.entity_subtype == null || d.entity_subtype === changeKind),
    [allDefs, changeKind],
  );

  useEffect(() => {
    if (open) {
      dispatch(fetchDefinitions('release_change'));
    }
  }, [open, dispatch]);

  useEffect(() => {
    if (open) {
      setTitle(item?.title ?? '');
      setChangeKind(item?.change_kind ?? 'story');
      setExternalKey(item?.external_key ?? '');
      setDescription(item?.description ?? '');
      setExternalStatus(item?.external_status ?? '');
      setCustomFields((item?.custom_fields as Record<string, unknown>) ?? {});
    }
  }, [open, item]);

  const requiredMissing = visibleDefs.some((d) => {
    if (!d.required) return false;
    const v = customFields[d.field_key];
    return v == null || (typeof v === 'string' && v.trim() === '');
  });

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSave = async () => {
    if (!title.trim() || requiredMissing) return;
    setSubmitting(true);
    try {
      if (isEdit && item) {
        await dispatch(
          updateReleaseChange({
            changeId: item.id,
            data: {
              title: title.trim(),
              description: description || null,
              external_key: externalKey || null,
              external_status: externalStatus || null,
              custom_fields: customFields,
            },
          })
        ).unwrap();
        snackbar.success('Scope item updated');
      } else {
        await dispatch(
          createReleaseChange({
            releaseId,
            data: {
              title: title.trim(),
              change_kind: changeKind,
              description: description || null,
              external_key: externalKey || null,
              external_status: externalStatus || null,
              custom_fields: customFields,
            },
          })
        ).unwrap();
        snackbar.success('Scope item added');
      }
      handleClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save scope item');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Scope Item' : 'Add Scope Item'}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            label="Title"
            required
            fullWidth
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={submitting}
          />
          <TextField
            select
            label="Kind"
            fullWidth
            value={changeKind}
            onChange={(e) => setChangeKind(e.target.value)}
            disabled={submitting || isEdit}
          >
            {CHANGE_KINDS.map((k) => (
              <MenuItem key={k} value={k}>
                {k}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="External Key (e.g. Jira issue)"
            fullWidth
            value={externalKey}
            onChange={(e) => setExternalKey(e.target.value)}
            disabled={submitting}
          />
          <TextField
            label="External Status"
            fullWidth
            value={externalStatus}
            onChange={(e) => setExternalStatus(e.target.value)}
            disabled={submitting}
          />
          <TextField
            label="Description"
            multiline
            rows={2}
            fullWidth
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={submitting}
          />

          <CustomFieldsSection
            definitions={visibleDefs}
            values={customFields}
            onChange={setCustomFields}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={!title.trim() || requiredMissing || submitting}
          onClick={handleSave}
        >
          {isEdit ? 'Save' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

Key changes from the current file:
- Imports `useSelector` + `fetchDefinitions` + `CustomFieldsSection`.
- `allDefs` comes from `state.customField.definitions['release_change']`.
- `visibleDefs` is memoised and reactively re-filters on `changeKind` change.
- `customFields` state is seeded from `item?.custom_fields` on open (edit) and reset to `{}` on create.
- `requiredMissing` blocks the Save button when a visible required field is empty.
- Create + update payloads now include `custom_fields`.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/releases/ScopeItemDialog.tsx
git commit -m "feat(scope): render custom fields in ScopeItemDialog, scoped by change_kind"
```

---

## Task 6: End-to-end integration test

**Files:**
- Create: `backend/tests/integration/test_scope_custom_fields.py`

- [ ] **Step 1: Write the HTTP integration test**

Create `backend/tests/integration/test_scope_custom_fields.py`:

```python
"""End-to-end: admin defines a release_change custom field, scope item create/update
round-trips the value, and subtype-scoped fields only apply to their kind."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate


@pytest_asyncio.fixture
async def release_lifecycle(db_session: AsyncSession, test_tenant):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Standard Release",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "done", "label": "Done", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "done", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


async def _setup_release(client, headers) -> int:
    r = await client.post(
        "/api/v1/releases", headers=headers,
        json={"name": "R", "release_type": "Major"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_unscoped_field_applies_to_every_kind(client: AsyncClient, auth_headers, release_lifecycle):
    """A field with entity_subtype=null shows up on story AND defect items."""
    # Define an unscoped field
    f = await client.post(
        "/api/v1/tenant/fields", headers=auth_headers,
        json={"entity_type": "release_change", "label": "Theme", "field_type": "text"},
    )
    assert f.status_code == 201, f.text

    rid = await _setup_release(client, auth_headers)

    # Story item — value persists
    s = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "S", "change_kind": "story", "custom_fields": {"theme": "Onboarding"}},
    )
    assert s.status_code == 201, s.text
    assert s.json()["custom_fields"]["theme"] == "Onboarding"

    # Defect item — value also persists
    d = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "D", "change_kind": "defect", "custom_fields": {"theme": "Perf"}},
    )
    assert d.status_code == 201, d.text
    assert d.json()["custom_fields"]["theme"] == "Perf"


@pytest.mark.asyncio
async def test_subtype_required_field_is_enforced_on_matching_kind(
    client: AsyncClient, auth_headers, release_lifecycle,
):
    """A required defect-only field blocks creating a defect without it, but not a story."""
    await client.post(
        "/api/v1/tenant/fields", headers=auth_headers,
        json={
            "entity_type": "release_change", "entity_subtype": "defect",
            "label": "Prod Bug Ref", "field_type": "text", "required": True,
        },
    )
    rid = await _setup_release(client, auth_headers)

    # Defect without the required field → 422
    d = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "D1", "change_kind": "defect"},
    )
    assert d.status_code == 422, d.text

    # Story without it → 201 (field doesn't apply)
    s = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "S1", "change_kind": "story"},
    )
    assert s.status_code == 201, s.text


@pytest.mark.asyncio
async def test_update_change_validates_type(client: AsyncClient, auth_headers, release_lifecycle):
    await client.post(
        "/api/v1/tenant/fields", headers=auth_headers,
        json={"entity_type": "release_change", "label": "Points", "field_type": "number"},
    )
    rid = await _setup_release(client, auth_headers)
    c = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "C", "change_kind": "story"},
    )
    change_id = c.json()["id"]

    # Submitting a non-numeric value for a number field → 422
    bad = await client.put(
        f"/api/v1/release-changes/{change_id}", headers=auth_headers,
        json={"custom_fields": {"points": "not-a-number"}},
    )
    assert bad.status_code == 422, bad.text

    # Submitting a valid value → 200
    ok = await client.put(
        f"/api/v1/release-changes/{change_id}", headers=auth_headers,
        json={"custom_fields": {"points": 5}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["custom_fields"]["points"] == 5
```

- [ ] **Step 2: Run — verify green**

Run: `cd backend && uv run pytest tests/integration/test_scope_custom_fields.py -v`

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_scope_custom_fields.py
git commit -m "test(scope): end-to-end integration for scope item custom fields"
```

---

## Task 7: Push branch

- [ ] **Step 1: Final full-suite pass**

Run: `cd backend && uv run pytest -q && cd ../frontend && npx tsc --noEmit`

Expected: backend all pass; typecheck exit 0.

- [ ] **Step 2: Push**

```bash
git push -u origin feature/scope-custom-fields
```

- [ ] **Step 3: Report branch name + commit list back to the user.**

Do NOT open an MR. User drives the GitLab MR flow.

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Add `"release_change"` to `VALID_ENTITY_TYPES` | Task 1 |
| `entity_subtype` semantics: `null` = all kinds; value = scoped | Tasks 1 (test_release_change_entity_type_accepts_subtype), 2 |
| `validate_custom_fields` on create | Task 3 |
| `validate_custom_fields` on update | Task 3 |
| Subtype-aware visibility filter | Task 2 (`list_definitions_for_subtype`) |
| Jira-source update guard unchanged | Task 3 (existing branch, untouched) |
| Admin UI: entity_type=release_change | Task 4 |
| Admin UI: subtype select with `(Any)/story/defect/task/spike` | Task 4 |
| Manager table: "Scope" column for release_change | Task 4 |
| ScopeItemDialog: fetch + filter + render + payload | Task 5 |
| ScopeTable: unchanged | Not in any task — by design |
| End-to-end test | Task 6 |
| No migration | Plan header explicit; no Alembic task present |

**Placeholder scan:** no TBD/TODO. Every step shows complete code. Task 4 Step 4 says "find the page that mounts ..." which LOOKS like a placeholder but the step specifies a grep command plus the two concrete JSX snippets — unavoidable because the exact file isn't pinned; the concrete edit is.

**Type consistency:**
- `list_definitions_for_subtype(db, tenant_id, entity_type, subtype)` signature matches Task 2 definition and Task 3 call sites.
- `entity_type="release_change"` used consistently across backend + frontend.
- `CHANGE_KINDS` array identical in `ScopeItemDialog.tsx` and `CustomFieldDefinitionDialog.tsx`.
- `visible_field_keys` vs `visible_keys` — note the service helper is called `validate_custom_fields`'s param is `visible_field_keys`, and Task 3 passes a local `visible_keys` variable into that param. Consistent.
