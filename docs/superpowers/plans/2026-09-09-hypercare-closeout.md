# Phase 9 C6 — Hyper-care and Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hyper-care phase on a release, a "declared stable" audit flag, an operations group plus a "handover confirmed" audit flag, per-state `is_closed` / `marks_deployed` / `requires_*` lifecycle flags, and the first deliberate refusal in Phase 9: a close gate that fires only when a closed state asks for it.

**Architecture:** Lifecycle flags live in the template JSON and are declared on the Pydantic `LifecycleState` (which also stops `is_failed` being dropped). `TestPhase.kind` marks the hyper-care phase. Five nullable columns on `release` carry the group and two audit pairs. One service, `release_closeout_service`, computes hyper-care state, the incident window, the per-closed-state requirements, and raises the gate's 422 from `transition_release`. A composite `GET /releases/{id}/closeout`, four audit routes, a sixth `/me/work` queue, and a thirteenth release tab.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (manual DDL) + pytest (SQLite and PostgreSQL legs); React 18 + TS + MUI + Redux Toolkit + vitest.

**Spec:** `docs/superpowers/specs/2026-09-09-hypercare-closeout-design.md`

## Global Constraints

- Migration revision id `closeout`, `down_revision = 'gonogo'`, DDL written by hand (never `--autogenerate`).
- Project releases only: every new route answers **422** on `release_kind == "enterprise"`; all four new lifecycle flags are **refused** on `applies_to_kind == "enterprise"` templates.
- `is_closed` requires `is_terminal`; `requires_pir_complete` / `requires_handover_confirmed` require `is_closed`. Each refusal names the state.
- `transition_release` stamps `actual_date` on a state with `marks_deployed` when `actual_date` is null; the by-name set `_DEPLOYED_TERMINAL_STATES` is deleted.
- "PIR complete" is `pir.status == "complete"`; no PIR counts as incomplete.
- The gate lives in `release_closeout_service.assert_may_close`, called from `transition_release` after `validate_transition` and before the status write; **nothing is added to `release_readiness_service`**.
- Hyper-care state order: `stable`, `none`, `planned`, `overdue`, `active`; day comparisons through `app.core.day_boundaries.expiry_boundary`.
- Audit routes: Admin or Release Manager (`require_role(Role.RELEASE_MANAGER)` — Admin passes); 409 on setting an already-set flag; handover confirm 422 without `operations_group_id`.
- `_by` usernames resolved **without** a tenant filter.
- At most one live hyper-care phase per release, enforced in code, never by a partial index.
- Frontend thunks that can be refused use `rejectWithValue(formatApiError(err))`; components read `result.payload`. Tests mock refusals as an `AxiosError` shape, never a plain `Error`.
- Every new Pydantic request schema sets `model_config = ConfigDict(extra="forbid")`.
- Commit messages end with the session's `Co-Authored-By` / `Claude-Session` trailers.

---

## File structure

**Backend — modify**
- `backend/app/api/v1/schemas/booking_lifecycle.py` — `LifecycleState` gains five flags; `validate_definition_for_entity` gains the rules.
- `backend/app/services/release_defaults.py` — `deployed` state + flags on Major/Minor/Emergency; four event types.
- `backend/app/services/release_service.py` — `marks_deployed` stamping, `assert_may_close` call, `operations_group_id` on create/update.
- `backend/app/db/models/release.py`, `backend/app/db/models/test_phase.py` — new columns.
- `backend/app/api/v1/schemas/release.py`, `backend/app/api/v1/schemas/test_phase.py`, `backend/app/api/v1/schemas/release_template.py` — new fields.
- `backend/app/api/v1/releases.py` — phase create/update enforce one hyper-care phase; `_release_with_permissions` resolves the new names.
- `backend/app/services/release_template_service.py` — hyper-care phases laid forward.
- `backend/app/services/my_work_service.py` — sixth queue.
- `backend/app/api/v1/schemas/my_work.py` — no change needed (`queues: dict`).
- `backend/app/main.py` — mount the new router.
- `backend/tests/test_pir_records_never_refuses.py` — one test amended.

**Backend — create**
- `backend/app/db/migrations/versions/20260909_1000_closeout_hypercare_and_closeout.py`
- `backend/app/services/release_closeout_service.py` — all C6 computation and the gate.
- `backend/app/api/v1/schemas/closeout.py` — response/request schemas.
- `backend/app/api/v1/release_closeout.py` — the five routes.
- `backend/tests/test_lifecycle_state_flags.py`, `backend/tests/test_release_deploy_stamp.py`, `backend/tests/test_closeout_migration.py`, `backend/tests/test_hypercare_phase.py`, `backend/tests/test_release_closeout_service.py`, `backend/tests/test_c6_refuses_only_at_close.py`, `backend/tests/test_release_closeout_api.py`.

**Frontend — modify**
- `frontend/src/types/bookingLifecycle.ts`, `frontend/src/types/release.ts`, `frontend/src/types/releaseTemplate.ts`, `frontend/src/types/myWork.ts`.
- `frontend/src/store/releaseSlice.ts` (`transitionRelease` → `rejectWithValue`), `frontend/src/store/index.ts` (register `closeout`).
- `frontend/src/components/releases/ReleaseMainTab.tsx` — read `result.payload`.
- `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` — four checkboxes, payload.
- `frontend/src/components/releases/PhasesTable.tsx`, `PhaseGanttEditor.tsx`, `frontend/src/pages/admin/release-templates/ReleaseTemplateForm.tsx` — kind.
- `frontend/src/pages/releases/ReleaseDetail.tsx` — thirteenth tab + header comment.
- `frontend/src/pages/MyWork.tsx` — sixth card.

**Frontend — create**
- `frontend/src/types/closeout.ts`, `frontend/src/services/closeoutService.ts`, `frontend/src/store/closeoutSlice.ts`, `frontend/src/components/releases/CloseoutTab.tsx`, and tests beside each.

---

### Task 1: Lifecycle state flags — schema, validation, defaults

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py:72-183`
- Modify: `backend/app/services/release_defaults.py:15-118, 183-188`
- Test: `backend/tests/test_lifecycle_state_flags.py`, `backend/tests/test_release_defaults_seed.py`

**Interfaces:**
- Produces: `LifecycleState` fields `is_failed`, `marks_deployed`, `is_closed`, `requires_pir_complete`, `requires_handover_confirmed` (all `bool = False`). Seeded project templates now contain a `deployed` state and the flags in §3.1 of the spec. Seeded event types `Declared stable`, `Stability declaration withdrawn`, `Ops handover confirmed`, `Ops handover withdrawn`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_lifecycle_state_flags.py
"""The five lifecycle state flags survive a save and obey their rules.

`is_failed` was silently dropped on every save before C6: it was read by the
DORA change-failure rate but never declared on `LifecycleState`, and both
create and update store `definition.model_dump()`. The first test here is the
regression test for that.
"""
import pytest


def _definition(states, transitions=None):
    keys = [s["key"] for s in states]
    return {
        "states": states,
        "transitions": transitions or [
            {"from_state": keys[0], "to_state": keys[-1], "label": "Go",
             "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {k: {"standard_fields": {}, "custom_fields": {}} for k in keys},
    }


DRAFT = {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}


async def _post(client, headers, states, applies_to_kind="project"):
    return await client.post(
        "/api/v1/tenant/lifecycle-templates", headers=headers,
        json={"name": "Flags", "entity_type": "release",
              "applies_to_kind": applies_to_kind, "definition": _definition(states)},
    )


@pytest.mark.asyncio
async def test_all_five_flags_survive_create_read_update_and_copy(client, auth_headers):
    done = {"key": "done", "label": "Done", "is_terminal": True, "is_failed": True,
            "marks_deployed": True, "is_closed": True,
            "requires_pir_complete": True, "requires_handover_confirmed": True}
    resp = await _post(client, auth_headers, [DRAFT, done])
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]

    def _done(body):
        return next(s for s in body["definition"]["states"] if s["key"] == "done")

    for flag in ("is_failed", "marks_deployed", "is_closed",
                 "requires_pir_complete", "requires_handover_confirmed"):
        assert _done(resp.json())[flag] is True, flag

    got = await client.get(f"/api/v1/tenant/lifecycle-templates/{tid}", headers=auth_headers)
    assert _done(got.json())["is_failed"] is True

    put = await client.put(f"/api/v1/tenant/lifecycle-templates/{tid}", headers=auth_headers,
                           json={"definition": _definition([DRAFT, done])})
    assert put.status_code == 200, put.text
    assert _done(put.json())["is_failed"] is True

    copy = await client.post(f"/api/v1/tenant/lifecycle-templates/{tid}/copy",
                             headers=auth_headers, json={"name": "Flags copy"})
    assert copy.status_code == 201, copy.text
    assert _done(copy.json())["requires_pir_complete"] is True


@pytest.mark.asyncio
async def test_is_closed_requires_is_terminal(client, auth_headers):
    bad = {"key": "mid", "label": "Mid", "is_terminal": False, "is_closed": True}
    resp = await _post(client, auth_headers, [DRAFT, bad])
    assert resp.status_code == 422, resp.text
    assert "mid" in resp.text and "is_closed" in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["requires_pir_complete", "requires_handover_confirmed"])
async def test_requirements_need_is_closed(client, auth_headers, flag):
    bad = {"key": "done", "label": "Done", "is_terminal": True, flag: True}
    resp = await _post(client, auth_headers, [DRAFT, bad])
    assert resp.status_code == 422, resp.text
    assert "done" in resp.text and flag in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["marks_deployed", "is_closed",
                                  "requires_pir_complete", "requires_handover_confirmed"])
async def test_enterprise_templates_refuse_every_new_flag(client, auth_headers, flag):
    done = {"key": "done", "label": "Done", "is_terminal": True,
            "is_closed": True, "requires_pir_complete": flag == "requires_pir_complete",
            "requires_handover_confirmed": flag == "requires_handover_confirmed",
            "marks_deployed": flag == "marks_deployed"}
    resp = await _post(client, auth_headers, [DRAFT, done], applies_to_kind="enterprise")
    assert resp.status_code == 422, resp.text
    assert "enterprise" in resp.text.lower()


@pytest.mark.asyncio
async def test_a_state_with_no_new_flags_is_unchanged_on_a_project_template(client, auth_headers):
    done = {"key": "done", "label": "Done", "is_terminal": True}
    resp = await _post(client, auth_headers, [DRAFT, done])
    assert resp.status_code == 201, resp.text
    state = next(s for s in resp.json()["definition"]["states"] if s["key"] == "done")
    assert state["is_closed"] is False and state["marks_deployed"] is False
```

Add to `backend/tests/test_release_defaults_seed.py` (keep the existing tests):

```python
@pytest.mark.asyncio
async def test_default_project_templates_carry_the_c6_flags(db_session, test_tenant):
    from app.services.release_defaults import seed_release_defaults_for_tenant
    from app.db.models.lifecycle import LifecycleTemplate
    from app.db.models.release_event import ReleaseEventType
    from sqlalchemy import select

    await seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    rows = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id,
        LifecycleTemplate.entity_type == "release"))).scalars().all()
    by_name = {r.name: r for r in rows}
    for name in ("Major", "Minor", "Emergency"):
        states = {s["key"]: s for s in by_name[name].definition["states"]}
        assert states["deployed"]["marks_deployed"] is True
        assert states["deployed"]["is_terminal"] is False
        assert states["completed"]["is_closed"] is True
        assert states["completed"]["marks_deployed"] is True
        assert states["backed_out"]["is_closed"] is True
        assert states["backed_out"].get("marks_deployed", False) is False
        assert states["cancelled"].get("is_closed", False) is False
        pairs = {(t["from_state"], t["to_state"]) for t in by_name[name].definition["transitions"]}
        assert ("deployed", "completed") in pairs
        assert ("deployed", "backed_out") in pairs
    major_pairs = {(t["from_state"], t["to_state"]) for t in by_name["Major"].definition["transitions"]}
    assert ("ready_for_release", "deployed") in major_pairs
    assert ("ready_for_release", "completed") in major_pairs  # the direct path stays
    enterprise = by_name["Enterprise Release — default"].definition["states"]
    assert not any(s.get("is_closed") or s.get("marks_deployed") for s in enterprise)

    names = {r.name for r in (await db_session.execute(select(ReleaseEventType).where(
        ReleaseEventType.tenant_id == test_tenant.id, ReleaseEventType.is_system.is_(True)
    ))).scalars().all()}
    assert {"Declared stable", "Stability declaration withdrawn",
            "Ops handover confirmed", "Ops handover withdrawn"} <= names
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/test_lifecycle_state_flags.py tests/test_release_defaults_seed.py -q`
Expected: the flag round-trip fails on `KeyError: 'is_failed'` (dropped); the rule tests get 201 instead of 422; the seed test fails on `KeyError: 'deployed'`.

- [ ] **Step 3: Declare the flags and the rules**

In `backend/app/api/v1/schemas/booking_lifecycle.py` replace `LifecycleState`:

```python
class LifecycleState(BaseModel):
    key: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False
    is_admission_lockdown: bool = False  # only meaningful for release/enterprise lifecycles
    # DORA: reaching this terminal state counts as a failed delivery. Read by
    # dora_service since Phase 5; declared here only since C6 — before that
    # every save through the admin editor dropped it (model_dump of an
    # undeclared field), so any template edited through the UI lost it.
    is_failed: bool = False
    # C6 (project release templates only; refused on enterprise):
    marks_deployed: bool = False            # entering stamps release.actual_date once
    is_closed: bool = False                 # the release is formally closed here; requires is_terminal
    requires_pir_complete: bool = False     # close gate; requires is_closed
    requires_handover_confirmed: bool = False  # close gate; requires is_closed
```

In `validate_definition_for_entity`, inside the `if entity_type == "release" and applies_to_kind == "enterprise":` branch add, before the lockdown check:

```python
        for s in definition.states:
            for flag in ("marks_deployed", "is_closed",
                         "requires_pir_complete", "requires_handover_confirmed"):
                if getattr(s, flag):
                    raise ValueError(
                        f"{flag} is not valid on an enterprise release template (state '{s.key}')"
                    )
```

And add a block that runs for **every** entity type, immediately after the `spec = ENTITY_FIELD_SPECS.get(entity_type)` line (these are rules about the flags themselves, not about the entity):

```python
    for s in definition.states:
        if s.is_closed and not s.is_terminal:
            raise ValueError(f"state '{s.key}': is_closed requires is_terminal")
        for flag in ("requires_pir_complete", "requires_handover_confirmed"):
            if getattr(s, flag) and not s.is_closed:
                raise ValueError(f"state '{s.key}': {flag} requires is_closed")
```

Check how the router turns `ValueError` into a 422 (`booking_lifecycle.py:33-42` wraps `create_template`, which raises `ValueError` from `validate_definition_for_entity`; confirm the existing tests in `tests/test_booking_lifecycle.py` get 422 for a bad definition and mirror that path). If it surfaces as 400 there, the assertions above must match whatever that existing path returns — do not add a second error path.

- [ ] **Step 4: Update the defaults**

In `backend/app/services/release_defaults.py`:

`_MAJOR_DEFINITION["states"]`: insert after `ready_for_release`
```python
        {"key": "deployed",              "label": "Deployed (hyper-care)", "is_initial": False, "is_terminal": False, "marks_deployed": True},
```
and change the three deployed terminals to
```python
        {"key": "completed",             "label": "Completed",             "is_initial": False, "is_terminal": True, "marks_deployed": True, "is_closed": True},
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True, "is_failed": True, "marks_deployed": True, "is_closed": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True, "is_failed": True, "is_closed": True},
```
`_MAJOR_DEFINITION["transitions"]`: add (keep every existing line)
```python
        {"from_state": "ready_for_release", "to_state": "deployed",              "label": "Deploy",               "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "deployed",          "to_state": "completed",             "label": "Complete",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "deployed",          "to_state": "completed_with_issues", "label": "Complete with Issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "deployed",          "to_state": "backed_out",            "label": "Back Out",             "allowed_roles": ["Admin", "ReleaseManager"]},
```
`_MAJOR_DEFINITION["field_permissions"]`: add `"deployed": {"standard_fields": {}, "custom_fields": {}},`.

`_MINOR_DEFINITION`: same state insert after `ready_for_release`, same flag edits on `completed` / `completed_with_issues` / `backed_out`, transitions `ready_for_release → deployed` plus `deployed → completed | completed_with_issues | backed_out`, and the `field_permissions` entry.

`_EMERGENCY_DEFINITION` (no `ready_for_release`; its deploying state is `in_progress`): insert `deployed` after `in_progress`; flags on `completed` (`marks_deployed`, `is_closed`) and `backed_out` (`is_closed`); transitions `in_progress → deployed` ("Deploy") and `deployed → completed | backed_out`; `field_permissions["deployed"]`.

`_ENTERPRISE_DEFINITION`: untouched.

`_DEFAULT_EVENT_TYPES`: append
```python
    {"name": "Declared stable",                 "display_color": "#2e7d32"},
    {"name": "Stability declaration withdrawn", "display_color": "#ed6c02"},
    {"name": "Ops handover confirmed",          "display_color": "#1976d2"},
    {"name": "Ops handover withdrawn",          "display_color": "#ed6c02"},
```

- [ ] **Step 5: Run the tests to verify they pass, plus the lifecycle neighbours**

Run: `cd backend && uv run pytest tests/test_lifecycle_state_flags.py tests/test_release_defaults_seed.py tests/test_booking_lifecycle.py tests/test_release_field_permissions.py tests/services/test_release_defaults_failed_flag.py tests/services/test_dora_service.py -q`
Expected: all pass. If a test compares a stored definition to the posted dict by equality and now fails on the added `False` flags, update that assertion to compare the keys it cares about — the extra keys are the fix, not a regression.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/schemas/booking_lifecycle.py backend/app/services/release_defaults.py backend/tests/test_lifecycle_state_flags.py backend/tests/test_release_defaults_seed.py
git commit -m "feat(c6): declare lifecycle state flags (fixes dropped is_failed), add deployed state to default release templates"
```

---

### Task 2: `marks_deployed` replaces the by-name deploy set

**Files:**
- Modify: `backend/app/services/release_service.py:27, 459-512`
- Test: `backend/tests/test_release_deploy_stamp.py`

**Interfaces:**
- Produces: `transition_release` resolves `target_state = next((s for s in tpl.definition.get("states", []) if s.get("key") == to_state), None)` and stamps on `target_state.get("marks_deployed")`. Task 5 inserts its gate call right after this lookup.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_release_deploy_stamp.py
"""`actual_date` is stamped by the `marks_deployed` flag, not by a state's name.

Before C6 `release_service._DEPLOYED_TERMINAL_STATES = {"completed",
"completed_with_issues"}` decided this, so a tenant that renamed either state
never got a deploy date, and an enterprise release never got one at all.
"""
import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release


def _template(tenant_id, states, transitions):
    return LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="Stamp", is_default=False,
        applies_to_kind="project",
        definition={"states": states, "transitions": transitions,
                    "field_permissions": {s["key"]: {"standard_fields": {}, "custom_fields": {}}
                                          for s in states}},
    )


@pytest_asyncio.fixture
async def release_with(db_session, test_tenant, test_user):
    async def _make(states, transitions):
        tpl = _template(test_tenant.id, states, transitions)
        db_session.add(tpl)
        await db_session.flush()
        rel = Release(tenant_id=test_tenant.id, name="R", release_type="Major",
                      release_kind="project", lifecycle_template_id=tpl.id,
                      status="draft", raised_by=test_user.id)
        db_session.add(rel)
        await db_session.commit()
        await db_session.refresh(rel)
        return rel
    return _make


DRAFT = {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}


@pytest.mark.asyncio
async def test_a_renamed_state_with_the_flag_stamps_actual_date(client, auth_headers, release_with):
    live = {"key": "live", "label": "Live", "is_terminal": False, "marks_deployed": True}
    rel = await release_with([DRAFT, live], [
        {"from_state": "draft", "to_state": "live", "label": "Go", "allowed_roles": ["Admin"]}])
    resp = await client.post(f"/api/v1/releases/{rel.id}/transition",
                             json={"to_state": "live"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["actual_date"] is not None


@pytest.mark.asyncio
async def test_completed_without_the_flag_does_not_stamp(client, auth_headers, release_with):
    completed = {"key": "completed", "label": "Completed", "is_terminal": True}
    rel = await release_with([DRAFT, completed], [
        {"from_state": "draft", "to_state": "completed", "label": "Go", "allowed_roles": ["Admin"]}])
    resp = await client.post(f"/api/v1/releases/{rel.id}/transition",
                             json={"to_state": "completed"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["actual_date"] is None


@pytest.mark.asyncio
async def test_the_stamp_happens_once(client, auth_headers, release_with):
    live = {"key": "live", "label": "Live", "is_terminal": False, "marks_deployed": True}
    done = {"key": "done", "label": "Done", "is_terminal": True, "marks_deployed": True}
    rel = await release_with([DRAFT, live, done], [
        {"from_state": "draft", "to_state": "live", "label": "Go", "allowed_roles": ["Admin"]},
        {"from_state": "live", "to_state": "done", "label": "Done", "allowed_roles": ["Admin"]}])
    first = (await client.post(f"/api/v1/releases/{rel.id}/transition",
                               json={"to_state": "live"}, headers=auth_headers)).json()["actual_date"]
    second = (await client.post(f"/api/v1/releases/{rel.id}/transition",
                                json={"to_state": "done"}, headers=auth_headers)).json()["actual_date"]
    assert first is not None and first == second
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_release_deploy_stamp.py -q`
Expected: first test fails (`actual_date is None`), second fails (stamped by name), third fails on the first assertion.

- [ ] **Step 3: Implement**

In `backend/app/services/release_service.py` delete the `_DEPLOYED_TERMINAL_STATES` line (and its comment). In `transition_release`, right after `if not allowed: raise HTTPException(...)`:

```python
    target_state = next(
        (s for s in tpl.definition.get("states", []) if s.get("key") == to_state), None
    )

    old_state = release.status
    release.status = to_state

    # Stamp actual_date the first time a `marks_deployed` state is entered.
    # A flag, not a state name: a tenant may rename or insert states.
    if target_state is not None and target_state.get("marks_deployed") and release.actual_date is None:
        release.actual_date = datetime.now(timezone.utc)
```
(replacing the old `old_state`/`release.status`/stamp block). Grep the repo for `_DEPLOYED_TERMINAL_STATES` and remove any other reference.

- [ ] **Step 4: Run the new file and the transition neighbours**

Run: `cd backend && uv run pytest tests/test_release_deploy_stamp.py tests/integration/test_release_happy_path.py tests/test_releases_api.py tests/services/test_release_metrics_service.py tests/services/test_dora_service.py -q`
Expected: all pass. `test_release_happy_path` asserts `actual_date is not None` after `completed` — its local template must gain `"marks_deployed": True` on `completed` (the by-name behaviour it relied on is gone by design; edit the fixture, not the service).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_service.py backend/tests/test_release_deploy_stamp.py backend/tests/integration/test_release_happy_path.py
git commit -m "feat(c6): stamp actual_date on the marks_deployed flag, not a state name"
```

---

### Task 3: Models and migration `closeout`

**Files:**
- Modify: `backend/app/db/models/release.py:14-42`, `backend/app/db/models/test_phase.py`
- Create: `backend/app/db/migrations/versions/20260909_1000_closeout_hypercare_and_closeout.py`
- Test: `backend/tests/test_closeout_migration.py`, existing `backend/tests/test_migration_schema_drift.py`

**Interfaces:**
- Produces: `Release.operations_group_id`, `Release.declared_stable_at`, `Release.declared_stable_by`, `Release.handover_confirmed_at`, `Release.handover_confirmed_by`; `TestPhase.kind` (`"test"` | `"hypercare"`, default `"test"`).

- [ ] **Step 1: Add the model columns**

`backend/app/db/models/release.py`, inside `Release` after `scope_deadline`:

```python
    # C6 — hyper-care and closeout. The group a release is handed to in
    # operation (a UserGroup: "anything that needs a group adds its own FK").
    operations_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
    # Two audit pairs, set/cleared through release_closeout_service only.
    # `_by` renders through a NON-tenant-qualified username lookup.
    declared_stable_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    declared_stable_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    handover_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    handover_confirmed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
```

`backend/app/db/models/test_phase.py`, after `status`:

```python
    # C6: "test" (the default, every phase before C6) or "hypercare" — the
    # window after go-live. At most one live hypercare phase per release,
    # enforced in code (a partial unique index is inert on SQLite).
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="test", server_default="test")
```

- [ ] **Step 2: Write the migration**

```python
# backend/app/db/migrations/versions/20260909_1000_closeout_hypercare_and_closeout.py
"""closeout hypercare and closeout

Revision ID: closeout
Revises: gonogo
Create Date: 2026-09-09 10:00:00

Five nullable columns on `release`, `test_phase.kind`, then two data steps:
flag the three deployed terminal states of every existing PROJECT release
template (by state KEY — a renamed key gets nothing and the closeout tab
says so), and seed four system release event types per tenant. Neither
inserts a state or a transition into any template.
"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'closeout'
down_revision: Union[str, None] = 'gonogo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_FLAGS = ("marks_deployed", "is_closed", "requires_pir_complete", "requires_handover_confirmed")

# A literal copy, never an import from release_defaults: the migration must
# reproduce what was seeded on 2026-09-09 even after the module changes.
_EVENT_TYPES = [
    ("Declared stable", "#2e7d32"),
    ("Stability declaration withdrawn", "#ed6c02"),
    ("Ops handover confirmed", "#1976d2"),
    ("Ops handover withdrawn", "#ed6c02"),
]

_PROJECT_RELEASE_TEMPLATES = sa.text(
    "SELECT id, definition FROM lifecycle_template "
    "WHERE entity_type = 'release' "
    "AND (applies_to_kind IS NULL OR applies_to_kind <> 'enterprise')"
)
_UPDATE_DEFINITION = sa.text(
    "UPDATE lifecycle_template SET definition = :d WHERE id = :i"
).bindparams(sa.bindparam("d", type_=sa.JSON()))


def _load(raw):
    return raw if isinstance(raw, dict) else json.loads(raw)


def upgrade() -> None:
    op.add_column("release", sa.Column("operations_group_id", sa.Integer(),
                                       sa.ForeignKey("user_group.id"), nullable=True))
    op.create_index("ix_release_operations_group_id", "release", ["operations_group_id"])
    op.add_column("release", sa.Column("declared_stable_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("release", sa.Column("declared_stable_by", sa.Integer(),
                                       sa.ForeignKey("user.id"), nullable=True))
    op.add_column("release", sa.Column("handover_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("release", sa.Column("handover_confirmed_by", sa.Integer(),
                                       sa.ForeignKey("user.id"), nullable=True))
    op.add_column("test_phase", sa.Column("kind", sa.String(20), nullable=False, server_default="test"))

    conn = op.get_bind()
    for tid, raw in conn.execute(_PROJECT_RELEASE_TEMPLATES).fetchall():
        defn = _load(raw)
        changed = False
        for s in defn.get("states", []):
            if s.get("key") in ("completed", "completed_with_issues"):
                s["marks_deployed"] = True
                s["is_closed"] = True
                changed = True
            elif s.get("key") == "backed_out":
                s["is_closed"] = True
                changed = True
        if changed:
            conn.execute(_UPDATE_DEFINITION, {"d": defn, "i": tid})

    now = datetime.now(timezone.utc)
    tenant_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM tenant")).fetchall()]
    for tenant_id in tenant_ids:
        existing = {r[0] for r in conn.execute(
            sa.text("SELECT name FROM release_event_type WHERE tenant_id = :t AND is_system = :s"),
            {"t": tenant_id, "s": True}).fetchall()}
        for name, color in _EVENT_TYPES:
            if name in existing:
                continue
            conn.execute(sa.text(
                "INSERT INTO release_event_type (tenant_id, name, display_color, is_system, "
                "created_at, updated_at) VALUES (:t, :n, :c, :s, :now, :now)"),
                {"t": tenant_id, "n": name, "c": color, "s": True, "now": now})


def downgrade() -> None:
    conn = op.get_bind()
    for tid, raw in conn.execute(sa.text(
            "SELECT id, definition FROM lifecycle_template WHERE entity_type = 'release'")).fetchall():
        defn = _load(raw)
        changed = False
        for s in defn.get("states", []):
            for flag in NEW_FLAGS:
                if flag in s:
                    s.pop(flag)
                    changed = True
        if changed:
            conn.execute(_UPDATE_DEFINITION, {"d": defn, "i": tid})
    # The four event types are left in place: a release event may reference them.
    op.drop_column("test_phase", "kind")
    op.drop_column("release", "handover_confirmed_by")
    op.drop_column("release", "handover_confirmed_at")
    op.drop_column("release", "declared_stable_by")
    op.drop_column("release", "declared_stable_at")
    op.drop_index("ix_release_operations_group_id", table_name="release")
    op.drop_column("release", "operations_group_id")
```

Note the downgrade strips the four NEW flags only; `is_failed` predates C6 and stays.

- [ ] **Step 3: Write the migration rehearsal test**

```python
# backend/tests/test_closeout_migration.py
"""The `closeout` revision flags existing project release templates by state
KEY and leaves renamed keys alone; it inserts no state and no transition.

Same harness as test_pir_backfill_migration.py: a scratch PostgreSQL database
pinned at the previous revision, rows inserted with raw SQL, one upgrade,
read back. Skips when there is no PostgreSQL server.
"""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.test_migration_schema_drift import ADMIN_URL, SCRATCH_DB, _alembic, _scratch_url

_DEFAULT_SHAPE = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "ready_for_release", "label": "Ready", "is_initial": False, "is_terminal": False},
        {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
        {"key": "completed_with_issues", "label": "CWI", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "cancelled", "label": "Cancelled", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [{"from_state": "draft", "to_state": "completed", "label": "Go", "allowed_roles": ["Admin"]}],
    "field_permissions": {},
}
_RENAMED_SHAPE = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "live", "label": "Live", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [], "field_permissions": {},
}


@pytest.fixture
def scratch_db_at_gonogo(request):
    name = f"{SCRATCH_DB}_closeout_{abs(hash(request.node.name)) % 10_000}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.skip(f"no PostgreSQL server for the closeout migration rehearsal: {exc}")
    result = _alembic("gonogo", name)
    assert result.returncode == 0, f"alembic upgrade gonogo failed:\n{result.stderr}"
    yield name
    with admin.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def _insert_template(conn, tenant_id, name, kind, shape):
    return conn.execute(text(
        "INSERT INTO lifecycle_template (tenant_id, entity_type, name, is_default, applies_to_kind, "
        "definition, created_at, updated_at) VALUES (:t, 'release', :n, false, :k, :d, now(), now()) "
        "RETURNING id"), {"t": tenant_id, "n": name, "k": kind, "d": json.dumps(shape)}).scalar_one()


def test_flags_land_on_the_named_states_only(scratch_db_at_gonogo):
    name = scratch_db_at_gonogo
    engine = create_engine(_scratch_url("psycopg2", name))
    with engine.begin() as conn:
        tenant_id = conn.execute(text(
            "INSERT INTO tenant (name, slug, created_at, updated_at) "
            "VALUES ('T', 't-closeout', now(), now()) RETURNING id")).scalar_one()
        default_id = _insert_template(conn, tenant_id, "Major", "project", _DEFAULT_SHAPE)
        renamed_id = _insert_template(conn, tenant_id, "Renamed", "project", _RENAMED_SHAPE)
        enterprise_id = _insert_template(conn, tenant_id, "Ent", "enterprise", _DEFAULT_SHAPE)

    result = _alembic("closeout", name)
    assert result.returncode == 0, f"alembic upgrade closeout failed:\n{result.stderr}"

    with engine.connect() as conn:
        def states(tid):
            raw = conn.execute(text("SELECT definition FROM lifecycle_template WHERE id = :i"),
                               {"i": tid}).scalar_one()
            defn = raw if isinstance(raw, dict) else json.loads(raw)
            return {s["key"]: s for s in defn["states"]}, defn

        by_key, defn = states(default_id)
        assert by_key["completed"]["is_closed"] is True and by_key["completed"]["marks_deployed"] is True
        assert by_key["completed_with_issues"]["is_closed"] is True
        assert by_key["completed_with_issues"]["is_failed"] is True  # untouched
        assert by_key["backed_out"]["is_closed"] is True
        assert "marks_deployed" not in by_key["backed_out"]
        assert "is_closed" not in by_key["cancelled"]
        assert len(defn["states"]) == 6 and len(defn["transitions"]) == 1  # nothing inserted

        renamed, _ = states(renamed_id)
        assert "is_closed" not in renamed["live"]

        ent, _ = states(enterprise_id)
        assert "is_closed" not in ent["completed"]

        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM release_event_type WHERE tenant_id = :t AND is_system"), {"t": tenant_id})}
        assert {"Declared stable", "Stability declaration withdrawn",
                "Ops handover confirmed", "Ops handover withdrawn"} <= names

        assert conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'test_phase' AND column_name = 'kind'")).scalar_one().startswith("'test'")

    down = _alembic("gonogo", name, command="downgrade")
    assert down.returncode == 0, down.stderr
    with engine.connect() as conn:
        by_key, _ = states(default_id) if False else (None, None)
        raw = conn.execute(text("SELECT definition FROM lifecycle_template WHERE id = :i"),
                           {"i": default_id}).scalar_one()
        defn = raw if isinstance(raw, dict) else json.loads(raw)
        completed = next(s for s in defn["states"] if s["key"] == "completed")
        assert "is_closed" not in completed and "marks_deployed" not in completed
        cwi = next(s for s in defn["states"] if s["key"] == "completed_with_issues")
        assert cwi["is_failed"] is True  # pre-C6 flag survives the downgrade
    engine.dispose()
```

Remove the stray `by_key, _ = states(default_id) if False else (None, None)` line before committing — it is here only to make the intent (re-read after downgrade) explicit; the three lines after it are the real read.

- [ ] **Step 4: Run the migration on the dev database and the drift check**

Run: `cd backend && uv run alembic current && uv run alembic upgrade head && uv run alembic current`
Expected: head moves from `gonogo` to `closeout`. (Do NOT run `downgrade -1` against the dev database — see CLAUDE.md.)

Run: `cd backend && uv run pytest tests/test_closeout_migration.py tests/test_migration_schema_drift.py -q`
Expected: pass (or skip if no PostgreSQL server — then run with the server up before the PR).

- [ ] **Step 5: Run the SQLite suite subset that touches releases and phases**

Run: `cd backend && uv run pytest tests/test_releases_api.py tests/integration -q -x`
Expected: pass. (`create_all` builds the new columns; `TestPhase(...)` construction sites without `kind` get the default.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/release.py backend/app/db/models/test_phase.py backend/app/db/migrations/versions/20260909_1000_closeout_hypercare_and_closeout.py backend/tests/test_closeout_migration.py
git commit -m "feat(c6): release closeout columns, test_phase.kind, migration closeout with flag + event-type data steps"
```

---

### Task 4: Hyper-care phase kind — schema, one-per-release rule, template skeleton, instantiation

**Files:**
- Modify: `backend/app/api/v1/schemas/test_phase.py`, `backend/app/api/v1/schemas/release_template.py:7-11`
- Modify: `backend/app/api/v1/releases.py:730-767` (phase create/update)
- Modify: `backend/app/services/release_template_service.py:278-308`
- Create: `backend/app/services/release_closeout_service.py` (first two functions only; Task 5 fills the rest)
- Test: `backend/tests/test_hypercare_phase.py`

**Interfaces:**
- Produces: `release_closeout_service.PHASE_KINDS = frozenset({"test", "hypercare"})`, `HYPERCARE = "hypercare"`, `async def live_hypercare_phase(db, release_id, tenant_id) -> Optional[TestPhase]`, `async def assert_hypercare_slot_free(db, release_id, tenant_id, *, exclude_phase_id=None) -> None` (422 naming the existing phase). `TestPhaseCreate.kind: Literal["test","hypercare"] = "test"`, `TestPhaseUpdate.kind: Optional[Literal[...]] = None`, `TestPhaseRead.kind: str`, `ReleaseTemplatePhase.kind: Literal["test","hypercare"] = "test"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_hypercare_phase.py
"""One live hyper-care phase per release; template hyper-care phases are laid
FORWARD from target_date while test phases still end on it."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id, entity_type="release", name="HC", is_default=True,
        applies_to_kind="project",
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
                    "transitions": [], "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}}},
    )
    db_session.add(tpl)
    await db_session.flush()
    rel = Release(tenant_id=test_tenant.id, name="R", release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    return rel


@pytest.mark.asyncio
async def test_kind_defaults_to_test_and_round_trips(client, auth_headers, release):
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "SIT"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "test"
    hc = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                           json={"name": "Hyper-care", "kind": "hypercare"})
    assert hc.status_code == 201, hc.text
    assert hc.json()["kind"] == "hypercare"
    listed = (await client.get(f"/api/v1/releases/{release.id}/phases", headers=auth_headers)).json()
    assert {p["name"]: p["kind"] for p in listed} == {"SIT": "test", "Hyper-care": "hypercare"}


@pytest.mark.asyncio
async def test_an_unknown_kind_is_a_422(client, auth_headers, release):
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "X", "kind": "warranty"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_second_live_hypercare_phase_is_refused_naming_the_first(client, auth_headers, release):
    first = (await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                               json={"name": "Hyper-care", "kind": "hypercare"})).json()
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "Second", "kind": "hypercare"})
    assert resp.status_code == 422, resp.text
    assert first["name"] in resp.json()["detail"]


@pytest.mark.asyncio
async def test_changing_a_test_phase_to_hypercare_obeys_the_rule(client, auth_headers, release):
    await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                      json={"name": "Hyper-care", "kind": "hypercare"})
    sit = (await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "SIT"})).json()
    resp = await client.put(f"/api/v1/phases/{sit['id']}", headers=auth_headers, json={"kind": "hypercare"})
    assert resp.status_code == 422, resp.text
    # Updating the hyper-care phase itself (same row) is not a second one.
    hc = next(p for p in (await client.get(f"/api/v1/releases/{release.id}/phases",
                                           headers=auth_headers)).json() if p["kind"] == "hypercare")
    ok = await client.put(f"/api/v1/phases/{hc['id']}", headers=auth_headers,
                          json={"kind": "hypercare", "name": "Hyper-care (2 weeks)"})
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_a_soft_deleted_hypercare_phase_frees_the_slot(client, auth_headers, release):
    first = (await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                               json={"name": "Hyper-care", "kind": "hypercare"})).json()
    assert (await client.delete(f"/api/v1/phases/{first['id']}", headers=auth_headers)).status_code == 204
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "Again", "kind": "hypercare"})
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_template_hypercare_phase_runs_forward_from_target_date(client, auth_headers, db_session, test_tenant):
    from app.services.release_defaults import seed_release_defaults_for_tenant
    await seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    tpl = await client.post("/api/v1/release-templates", headers=auth_headers, json={
        "name": "With hyper-care", "release_type": "Major",
        "phases": [
            {"name": "SIT", "order": 1, "default_duration_days": 5, "activities": []},
            {"name": "UAT", "order": 2, "default_duration_days": 3, "activities": []},
            {"name": "Hyper-care", "order": 3, "default_duration_days": 14, "activities": [],
             "kind": "hypercare"},
        ],
        "gates": [],
    })
    assert tpl.status_code == 201, tpl.text
    target = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    rel = await client.post(f"/api/v1/release-templates/{tpl.json()['id']}/instantiate",
                            headers=auth_headers,
                            json={"name": "R1", "target_date": target.isoformat()})
    assert rel.status_code == 201, rel.text
    phases = {p["name"]: p for p in (await client.get(
        f"/api/v1/releases/{rel.json()['id']}/phases", headers=auth_headers)).json()}
    assert datetime.fromisoformat(phases["UAT"]["end_date"]) == target
    assert datetime.fromisoformat(phases["SIT"]["end_date"]) == target - timedelta(days=3)
    assert phases["Hyper-care"]["kind"] == "hypercare"
    assert datetime.fromisoformat(phases["Hyper-care"]["start_date"]) == target
    assert datetime.fromisoformat(phases["Hyper-care"]["end_date"]) == target + timedelta(days=14)
```

Check the release-template create and instantiate routes' exact paths and payload names in `backend/app/api/v1/release_templates.py` (grep `instantiate` and `@router.post`) and in `tests/` for an existing instantiate test to copy the body shape; adjust the two POSTs above to match — the assertions are the contract.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_hypercare_phase.py -q`
Expected: `KeyError: 'kind'`, 201 where 422 expected, and the forward-laid dates wrong.

- [ ] **Step 3: Schemas**

`backend/app/api/v1/schemas/test_phase.py`: add `from typing import Literal, Optional`, then
- `TestPhaseCreate`: `kind: Literal["test", "hypercare"] = "test"`
- `TestPhaseUpdate`: `kind: Optional[Literal["test", "hypercare"]] = None`
- `TestPhaseRead`: `kind: str`

`backend/app/api/v1/schemas/release_template.py`: in `ReleaseTemplatePhase` add `kind: Literal["test", "hypercare"] = "test"` (import `Literal`).

- [ ] **Step 4: Service — first two functions**

```python
# backend/app/services/release_closeout_service.py
"""Phase 9 C6 — hyper-care and closeout.

THE ONE PLACE IN PHASE 9 THAT REFUSES. `assert_may_close` (Task 5) raises a
422 from `release_service.transition_release` when the target state is
flagged `is_closed` and asks for something that is not there. Everything
else here computes on read and stores nothing.
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.test_phase import TestPhase

PHASE_KINDS = frozenset({"test", "hypercare"})
HYPERCARE = "hypercare"


async def live_hypercare_phase(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Optional[TestPhase]:
    """The release's one live hyper-care phase, or None."""
    return (
        await db.execute(
            select(TestPhase).where(
                TestPhase.release_id == release_id,
                TestPhase.tenant_id == tenant_id,
                TestPhase.kind == HYPERCARE,
                TestPhase.deleted_at.is_(None),
            ).order_by(TestPhase.id).limit(1)
        )
    ).scalar_one_or_none()


async def assert_hypercare_slot_free(
    db: AsyncSession, release_id: int, tenant_id: int, *, exclude_phase_id: Optional[int] = None
) -> None:
    """At most one live hyper-care phase per release. In code, not a partial
    unique index — that would be inert on SQLite and untested there."""
    existing = await live_hypercare_phase(db, release_id, tenant_id)
    if existing is not None and existing.id != exclude_phase_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This release already has a hyper-care phase ('{existing.name}'); "
            "edit or delete it rather than adding a second.",
        )
```

- [ ] **Step 5: Endpoints**

In `backend/app/api/v1/releases.py` import `from app.services import release_closeout_service` (beside the other service imports). In `create_phase`, before `phase = TestPhase(...)`:
```python
    if data.kind == release_closeout_service.HYPERCARE:
        await release_closeout_service.assert_hypercare_slot_free(db, release_id, tenant_id)
```
and add `kind=data.kind,` to the constructor. In `update_phase`, before the setattr loop:
```python
    if update_data.get("kind") == release_closeout_service.HYPERCARE:
        await release_closeout_service.assert_hypercare_slot_free(
            db, phase.release_id, tenant_id, exclude_phase_id=phase.id
        )
```

- [ ] **Step 6: Instantiation**

In `backend/app/services/release_template_service.py` replace the phase loop (`if phases_config:` … `cursor = start_date`) with:

```python
    if phases_config:
        def _cfg(p):
            if isinstance(p, dict):
                return (p.get("name", "Phase"), p.get("order", 0),
                        p.get("default_duration_days", 5), p.get("kind", "test"))
            return (p.name, p.order, p.default_duration_days, getattr(p, "kind", "test"))

        test_cfgs = [c for c in map(_cfg, phases_config) if c[3] != "hypercare"]
        hypercare_cfgs = [c for c in map(_cfg, phases_config) if c[3] == "hypercare"]

        # Test phases: backwards, so the last one ends on target_date (unchanged).
        cursor = data.target_date
        for name, order, duration_days, kind in reversed(test_cfgs):
            end_date = cursor
            start_date = cursor - timedelta(days=duration_days)
            phase = TestPhase(tenant_id=tenant_id, release_id=release.id, name=name, order=order,
                              start_date=start_date, end_date=end_date, status="pending", kind=kind)
            db.add(phase)
            await db.flush()
            phase_objects[name] = phase
            cursor = start_date

        # Hyper-care phases: FORWARD from target_date, in template order — the
        # window starts on the planned deploy day. C6 §3.3.
        cursor = data.target_date
        for name, order, duration_days, kind in hypercare_cfgs:
            start_date = cursor
            end_date = cursor + timedelta(days=duration_days)
            phase = TestPhase(tenant_id=tenant_id, release_id=release.id, name=name, order=order,
                              start_date=start_date, end_date=end_date, status="pending", kind=kind)
            db.add(phase)
            await db.flush()
            phase_objects[name] = phase
            cursor = end_date
```

- [ ] **Step 7: Run**

Run: `cd backend && uv run pytest tests/test_hypercare_phase.py tests/test_releases_api.py tests/integration/test_release_happy_path.py -q` plus whatever file covers `release_templates` instantiate (`grep -rl instantiate backend/tests`).
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/schemas/test_phase.py backend/app/api/v1/schemas/release_template.py backend/app/api/v1/releases.py backend/app/services/release_template_service.py backend/app/services/release_closeout_service.py backend/tests/test_hypercare_phase.py
git commit -m "feat(c6): hyper-care phase kind, one per release, laid forward from target_date"
```

---

### Task 5: The gate — `assert_may_close`, hyper-care state, and the two guard files

**Files:**
- Modify: `backend/app/services/release_closeout_service.py` (add the functions below)
- Modify: `backend/app/services/release_service.py` (`transition_release`, after the `target_state` lookup from Task 2)
- Modify: `backend/tests/test_pir_records_never_refuses.py:143-148` and its module docstring
- Create: `backend/tests/test_c6_refuses_only_at_close.py`, `backend/tests/test_release_closeout_service.py`

**Interfaces:**
- Produces:
  - `HYPERCARE_STATES = ("none", "planned", "active", "overdue", "stable")`
  - `def hypercare_state(phase: Optional[TestPhase], declared_stable_at: Optional[datetime], now: datetime) -> str`
  - `def state_for_key(definition: dict, key: str) -> Optional[dict]`
  - `def unmet_requirements(state: dict, pir: Optional[PIR], release: Release) -> list[str]` — reason strings, same wording the 422 and the tab use
  - `async def assert_may_close(db, release: Release, target_state: Optional[dict], tenant_id: int) -> None`
  - `PIR_INCOMPLETE = "the post-implementation review is not complete"`, `HANDOVER_UNCONFIRMED = "ops handover is not confirmed"`

- [ ] **Step 1: Write the pure-function tests**

```python
# backend/tests/test_release_closeout_service.py
"""Hyper-care state and close requirements, computed on read.

Day rule: the END of a hyper-care window is a day, compared through
`expiry_boundary` — 23:59 UTC on the end day is still `active`; 00:00 the
next day is `overdue`. `stable` wins over every date."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import release_closeout_service as svc

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _phase(start=None, end=None):
    return SimpleNamespace(id=1, name="HC", start_date=start, end_date=end)


def test_no_phase_is_none():
    assert svc.hypercare_state(None, None, NOW) == "none"


def test_declared_stable_wins_over_every_date():
    assert svc.hypercare_state(None, NOW, NOW) == "stable"
    assert svc.hypercare_state(_phase(NOW + timedelta(days=5), NOW + timedelta(days=9)), NOW, NOW) == "stable"


def test_start_after_today_is_planned():
    assert svc.hypercare_state(_phase(NOW + timedelta(days=1), NOW + timedelta(days=10)), None, NOW) == "planned"


def test_start_later_today_is_already_active():
    later_today = NOW.replace(hour=23)
    assert svc.hypercare_state(_phase(later_today, NOW + timedelta(days=10)), None, NOW) == "active"


def test_undated_phase_is_active():
    assert svc.hypercare_state(_phase(), None, NOW) == "active"


def test_end_day_is_still_active_until_midnight():
    end = NOW.replace(hour=0, minute=0)  # ends "today"
    assert svc.hypercare_state(_phase(NOW - timedelta(days=10), end), None, NOW.replace(hour=23, minute=59)) == "active"


def test_the_day_after_the_end_is_overdue():
    end = NOW - timedelta(days=1)
    assert svc.hypercare_state(_phase(NOW - timedelta(days=10), end), None, NOW.replace(hour=0, minute=0)) == "overdue"


def test_naive_sqlite_datetimes_are_normalised():
    end = (NOW - timedelta(days=1)).replace(tzinfo=None)
    assert svc.hypercare_state(_phase(None, end), None, NOW) == "overdue"


def _release(**kw):
    base = dict(handover_confirmed_at=None, operations_group_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_unmet_requirements_names_each_missing_thing():
    state = {"key": "completed", "is_closed": True,
             "requires_pir_complete": True, "requires_handover_confirmed": True}
    assert svc.unmet_requirements(state, None, _release()) == [svc.PIR_INCOMPLETE, svc.HANDOVER_UNCONFIRMED]
    draft = SimpleNamespace(status="draft")
    assert svc.unmet_requirements(state, draft, _release()) == [svc.PIR_INCOMPLETE, svc.HANDOVER_UNCONFIRMED]
    complete = SimpleNamespace(status="complete")
    assert svc.unmet_requirements(state, complete, _release(handover_confirmed_at=NOW)) == []


def test_a_closed_state_with_no_requirements_is_always_enterable():
    assert svc.unmet_requirements({"key": "done", "is_closed": True}, None, _release()) == []


def test_a_non_closed_state_has_no_requirements_even_if_flags_are_set():
    state = {"key": "mid", "is_closed": False, "requires_pir_complete": True}
    assert svc.unmet_requirements(state, None, _release()) == []
```

- [ ] **Step 2: Write the guard file**

```python
# backend/tests/test_c6_refuses_only_at_close.py
"""C6 REFUSES EXACTLY AT A CLOSED STATE THAT ASKS FOR IT, AND NOWHERE ELSE.

The first deliberate refusal in Phase 9, after eight sub-projects whose
central promise was a named test asserting an ABSENCE (A3, A4, B2, B4, C2,
C4, the PIR work, C3). This file is the same kind of promise inverted: the
gate fires in ONE function (`release_closeout_service.assert_may_close`),
only on a state flagged `is_closed`, only for the `requires_*` flags that
state carries, and everything else in the product is byte-for-byte what it
was with the flags on.

Proved non-vacuous: deleting the `assert_may_close` call from
`release_service.transition_release` makes
`test_a_closed_state_requiring_a_pir_refuses_a_draft_pir` fail, and
restoring it makes it pass. A guard nobody has watched fail is a guard
nobody knows works.
"""
import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from tests.factories import ensure_user_group, make_incident

DRAFT = {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}
LIVE = {"key": "live", "label": "Live", "is_initial": False, "is_terminal": False}


def _definition(closed_flags: dict, *, also_on_live: dict | None = None):
    closed = {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True,
              "is_closed": True, **closed_flags}
    live = {**LIVE, **(also_on_live or {})}
    return {
        "states": [DRAFT, live, closed],
        "transitions": [
            {"from_state": "draft", "to_state": "live", "label": "Go live", "allowed_roles": ["Admin"]},
            {"from_state": "live", "to_state": "completed", "label": "Close", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {k: {"standard_fields": {}, "custom_fields": {}} for k in ("draft", "live", "completed")},
    }


@pytest_asyncio.fixture
async def make_release(db_session, test_tenant, test_user):
    async def _make(closed_flags: dict, status="live"):
        tpl = LifecycleTemplate(tenant_id=test_tenant.id, entity_type="release", name="C6",
                                is_default=False, applies_to_kind="project",
                                definition=_definition(closed_flags))
        db_session.add(tpl)
        await db_session.flush()
        rel = Release(tenant_id=test_tenant.id, name="R-c6", release_type="Major", release_kind="project",
                      lifecycle_template_id=tpl.id, status=status, raised_by=test_user.id)
        db_session.add(rel)
        await db_session.commit()
        await db_session.refresh(rel)
        return rel
    return _make


async def _close(client, headers, rid):
    return await client.post(f"/api/v1/releases/{rid}/transition",
                             json={"to_state": "completed"}, headers=headers)


@pytest.mark.asyncio
async def test_a_closed_state_with_no_requirements_closes_over_a_draft_pir(client, auth_headers, make_release):
    rel = await make_release({})
    assert (await client.post(f"/api/v1/releases/{rel.id}/pir", json={"summary": "s"},
                              headers=auth_headers)).status_code == 201
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_closed_state_requiring_a_pir_refuses_a_draft_pir(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True})
    await client.post(f"/api/v1/releases/{rel.id}/pir", json={"summary": "s"}, headers=auth_headers)
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 422, resp.text
    assert "post-implementation review is not complete" in resp.json()["detail"]
    still = (await client.get(f"/api/v1/releases/{rel.id}", headers=auth_headers)).json()
    assert still["status"] == "live"


@pytest.mark.asyncio
async def test_no_pir_at_all_is_incomplete(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True})
    assert (await _close(client, auth_headers, rel.id)).status_code == 422


@pytest.mark.asyncio
async def test_completing_the_pir_lets_the_release_close(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True})
    await client.post(f"/api/v1/releases/{rel.id}/pir", json={"summary": "s"}, headers=auth_headers)
    assert (await client.patch(f"/api/v1/releases/{rel.id}/pir", json={"status": "complete"},
                               headers=auth_headers)).status_code == 200
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_handover_requirement_refuses_until_confirmed(client, auth_headers, make_release, db_session, test_tenant):
    rel = await make_release({"requires_handover_confirmed": True})
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 422 and "ops handover is not confirmed" in resp.json()["detail"]
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    assert (await client.put(f"/api/v1/releases/{rel.id}", json={"operations_group_id": group.id},
                             headers=auth_headers)).status_code == 200
    assert (await client.post(f"/api/v1/releases/{rel.id}/confirm-handover", json={},
                              headers=auth_headers)).status_code == 200
    assert (await _close(client, auth_headers, rel.id)).status_code == 200


@pytest.mark.asyncio
async def test_both_requirements_are_named_in_one_refusal(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True, "requires_handover_confirmed": True})
    detail = (await _close(client, auth_headers, rel.id)).json()["detail"]
    assert "post-implementation review is not complete" in detail
    assert "ops handover is not confirmed" in detail


@pytest.mark.asyncio
async def test_the_gate_never_touches_a_non_closed_transition(client, auth_headers, make_release):
    """draft -> live is not a close, whatever the closed state demands."""
    rel = await make_release({"requires_pir_complete": True, "requires_handover_confirmed": True},
                             status="draft")
    resp = await client.post(f"/api/v1/releases/{rel.id}/transition",
                             json={"to_state": "live"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_with_both_flags_on_nothing_else_in_the_product_changes(
    client, auth_headers, make_release, db_session, test_tenant
):
    """A booking, an incident transition, readiness and can-deploy are what
    they were. Readiness in particular still says nothing about PIRs — the
    gate is NOT folded into `release_readiness_service`."""
    from app.services.incident_defaults import seed_incident_defaults_for_tenant
    await seed_incident_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    rel = await make_release({"requires_pir_complete": True, "requires_handover_confirmed": True})

    readiness = (await client.get(f"/api/v1/releases/{rel.id}/readiness", headers=auth_headers)).json()
    blob = str(readiness).lower()
    assert "pir" not in blob and "handover" not in blob and "closeout" not in blob

    incident = await make_incident(db_session, test_tenant.id, title="hc incident", status="new")
    moved = await client.post(f"/api/v1/incidents/{incident.id}/transition",
                              json={"to_state": "investigating"}, headers=auth_headers)
    assert moved.status_code == 200, moved.text

    from tests.factories import ensure_environment, make_booking
    env = await ensure_environment(db_session, test_tenant.id)
    booking = await make_booking(db_session, test_tenant.id, booked_by=(await client.get(
        "/api/v1/auth/me", headers=auth_headers)).json()["id"], environment=env)
    assert booking.id is not None
```

Check `/api/v1/auth/me` exists (grep `"/me"` in `backend/app/api/v1/auth.py`); if the current-user route has another path, use it — or simply pass `test_user.id` by adding `test_user` to the test's fixtures, which is the simpler option.

- [ ] **Step 3: Amend the PIR guard**

In `backend/tests/test_pir_records_never_refuses.py` replace `test_a_release_with_an_overdue_action_still_transitions` with:

```python
@pytest.mark.asyncio
async def test_a_release_with_an_overdue_action_still_transitions(client, auth_headers, bad_pir):
    """The release moves, with an incomplete review and an overdue action on
    it — because THIS template's `completed` state carries no
    `requires_pir_complete` flag, which is every template that existed before
    C6. The configurable gate §2.5 asks for now exists, in
    `release_closeout_service.assert_may_close`, and is guarded by
    tests/test_c6_refuses_only_at_close.py; it fires only where a closed
    state asks for it."""
    resp = await client.post(f"/api/v1/releases/{bad_pir}/transition",
                             json={"to_state": "completed"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"
```

And in the module docstring replace the sentence starting "requirements.md §2.5 asks for a configurable" through "by accident." with:

```
requirements.md §2.5's configurable "PIR complete" gate before a release is
formally closed was built by Phase 9 C6 (2026-09), deliberately, in ONE
function — release_closeout_service.assert_may_close — and only for a
lifecycle state flagged `is_closed` + `requires_pir_complete`. Every other
promise in this file still holds and is still guarded here: no PIR state
touches readiness, incidents, bookings, `can-deploy`, or a transition into a
state that does not ask.
```

- [ ] **Step 4: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_release_closeout_service.py tests/test_c6_refuses_only_at_close.py -q`
Expected: `AttributeError: module has no attribute 'hypercare_state'`, and the refusal tests get 200.

- [ ] **Step 5: Implement the service functions**

Append to `backend/app/services/release_closeout_service.py` (extend the imports: `from app.core.day_boundaries import expiry_boundary`, `from app.db.models.pir import PIR`, `from app.db.models.release import Release`, `from app.services import pir_service`):

```python
HYPERCARE_STATES = ("none", "planned", "active", "overdue", "stable")
PIR_INCOMPLETE = "the post-implementation review is not complete"
HANDOVER_UNCONFIRMED = "ops handover is not confirmed"


def _day(value: Optional[datetime]) -> Optional[datetime]:
    """Start of the UTC day `value` falls in, tolerant of SQLite's naive datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return expiry_boundary(value)


def hypercare_state(phase, declared_stable_at: Optional[datetime], now: datetime) -> str:
    """First match wins: stable, none, planned, overdue, active. A window's
    bounds are DAYS — the end day itself still reads active."""
    if declared_stable_at is not None:
        return "stable"
    if phase is None:
        return "none"
    today = _day(now)
    start, end = _day(phase.start_date), _day(phase.end_date)
    if start is not None and start > today:
        return "planned"
    if end is not None and end < today:
        return "overdue"
    return "active"


def state_for_key(definition: dict, key: str) -> Optional[dict]:
    return next((s for s in definition.get("states", []) if s.get("key") == key), None)


def unmet_requirements(state: dict, pir: Optional[PIR], release: Release) -> list[str]:
    """Reasons a closed state cannot be entered. ONE wording, used by the 422
    and by GET /closeout, so the tab and the refusal cannot disagree."""
    if not state.get("is_closed"):
        return []
    unmet: list[str] = []
    if state.get("requires_pir_complete") and (pir is None or pir.status != "complete"):
        unmet.append(PIR_INCOMPLETE)
    if state.get("requires_handover_confirmed") and release.handover_confirmed_at is None:
        unmet.append(HANDOVER_UNCONFIRMED)
    return unmet


async def assert_may_close(
    db: AsyncSession, release: Release, target_state: Optional[dict], tenant_id: int
) -> None:
    """THE ONE REFUSAL IN PHASE 9. Returns at once unless `target_state` is
    flagged `is_closed`; then raises one 422 naming everything unmet."""
    if not target_state or not target_state.get("is_closed"):
        return
    pir = await pir_service.get_for_release(db, tenant_id, release.id)
    unmet = unmet_requirements(target_state, pir, release)
    if unmet:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Cannot close this release: " + "; ".join(unmet) + ".",
        )
```
(add `timezone` to the `datetime` import.)

- [ ] **Step 6: Wire the gate**

In `backend/app/services/release_service.py`, import `from app.services import release_closeout_service` (check for an import cycle: `release_closeout_service` must not import `release_service`; it does not). Immediately after the `target_state = next(...)` lookup added in Task 2 and BEFORE `old_state = release.status`:

```python
    # C6: the one place Phase 9 refuses. No-op unless the target is a closed
    # state that asks for something. See release_closeout_service.
    await release_closeout_service.assert_may_close(db, release, target_state, tenant_id)
```

- [ ] **Step 7: Run, then prove the guard non-vacuous**

Run: `cd backend && uv run pytest tests/test_release_closeout_service.py tests/test_c6_refuses_only_at_close.py tests/test_pir_records_never_refuses.py -q`
Expected: all pass, except `test_handover_requirement_refuses_until_confirmed` which needs Task 6's routes — mark it `@pytest.mark.xfail(strict=True, reason="Task 6 adds PUT operations_group_id and confirm-handover")` for this commit and remove the mark in Task 6.

Then comment out the `assert_may_close` call, run `tests/test_c6_refuses_only_at_close.py` and confirm `test_a_closed_state_requiring_a_pir_refuses_a_draft_pir` FAILS; restore the line; confirm `git diff backend/app/services/release_service.py` shows only the intended change. Record the failing test name in the commit body.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/release_closeout_service.py backend/app/services/release_service.py backend/tests/test_release_closeout_service.py backend/tests/test_c6_refuses_only_at_close.py backend/tests/test_pir_records_never_refuses.py
git commit -m "feat(c6): close gate in release_closeout_service.assert_may_close; hyper-care state; amend PIR never-refuses guard"
```

---

### Task 6: Operations group on the release, and the four audit routes

**Files:**
- Modify: `backend/app/api/v1/schemas/release.py` (`ReleaseCreate`, `ReleaseUpdate`, `ReleaseRead`)
- Modify: `backend/app/services/release_service.py` (`create_release`, `update_release`)
- Modify: `backend/app/api/v1/releases.py:153-176` (`_release_with_permissions`)
- Modify: `backend/app/services/release_closeout_service.py` (audit functions + `usernames_for`)
- Create: `backend/app/api/v1/schemas/closeout.py` (`AuditNote` only for now), `backend/app/api/v1/release_closeout.py`
- Modify: `backend/app/main.py` (mount)
- Test: `backend/tests/test_release_closeout_api.py`

**Interfaces:**
- Produces: `ReleaseRead.operations_group_id`, `.operations_group_name`, `.declared_stable_at`, `.declared_stable_by_username`, `.handover_confirmed_at`, `.handover_confirmed_by_username`. Service: `async def declare_stable(db, release, *, tenant_id, user_id, note) -> Release`, `withdraw_stable(...)`, `confirm_handover(...)`, `withdraw_handover(...)`, `async def usernames_for(db, user_ids: set[int]) -> dict[int, str]`. Event type names as constants `EVENT_DECLARED_STABLE = "Declared stable"`, `EVENT_STABLE_WITHDRAWN = "Stability declaration withdrawn"`, `EVENT_HANDOVER_CONFIRMED = "Ops handover confirmed"`, `EVENT_HANDOVER_WITHDRAWN = "Ops handover withdrawn"`. Routes `POST/DELETE /releases/{id}/declare-stable`, `POST/DELETE /releases/{id}/confirm-handover` returning `ReleaseRead`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_release_closeout_api.py
"""Declared stable and handover confirmed: audit pairs set and cleared through
their own routes, 409 on re-set, events on every change, Admin/RM only,
project releases only, usernames resolved WITHOUT a tenant filter."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.event_log import EventLog
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.user import User
from app.services.release_defaults import seed_release_defaults_for_tenant
from tests.factories import ensure_user_group


@pytest_asyncio.fixture
async def seeded(db_session, test_tenant):
    await seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user, seeded):
    tpl = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id, LifecycleTemplate.name == "Major"))).scalar_one()
    rel = Release(tenant_id=test_tenant.id, name="R", release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="deployed", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    return rel


@pytest_asyncio.fixture
async def enterprise_release(db_session, test_tenant, test_user, seeded):
    tpl = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id,
        LifecycleTemplate.applies_to_kind == "enterprise"))).scalar_one()
    rel = Release(tenant_id=test_tenant.id, name="E", release_type="Enterprise", release_kind="enterprise",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    return rel


async def _rm_headers(client, db_session, test_tenant):
    user = User(tenant_id=test_tenant.id, username="c6rm", email="c6rm@test.com",
                password_hash=get_password_hash("password123"), role="Release Manager", is_active=True)
    db_session.add(user)
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login", json={
        "username": "c6rm", "password": "password123", "tenant_slug": test_tenant.slug})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _event_names(db_session, release_id):
    rows = (await db_session.execute(
        select(ReleaseEventType.name).join(ReleaseEvent, ReleaseEvent.event_type_id == ReleaseEventType.id)
        .where(ReleaseEvent.release_id == release_id))).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_declare_stable_sets_the_pair_and_records_an_event(client, auth_headers, release, db_session, test_user):
    resp = await client.post(f"/api/v1/releases/{release.id}/declare-stable",
                             json={"note": "no P1 in 14 days"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["declared_stable_at"] is not None
    assert body["declared_stable_by_username"] == test_user.username
    assert "Declared stable" in await _event_names(db_session, release.id)
    outbox = (await db_session.execute(select(EventLog).where(
        EventLog.event_type == "ReleaseDeclaredStable", EventLog.aggregate_id == release.id))).scalars().all()
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_declaring_twice_is_a_409(client, auth_headers, release):
    await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    resp = await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_withdraw_clears_the_pair_and_keeps_the_history(client, auth_headers, release, db_session):
    await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    resp = await client.delete(f"/api/v1/releases/{release.id}/declare-stable", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["declared_stable_at"] is None
    assert resp.json()["declared_stable_by_username"] is None
    names = await _event_names(db_session, release.id)
    assert "Declared stable" in names and "Stability declaration withdrawn" in names


@pytest.mark.asyncio
async def test_withdrawing_nothing_is_a_409(client, auth_headers, release):
    assert (await client.delete(f"/api/v1/releases/{release.id}/declare-stable",
                                headers=auth_headers)).status_code == 409


@pytest.mark.asyncio
async def test_confirm_handover_needs_a_group(client, auth_headers, release, db_session, test_tenant):
    resp = await client.post(f"/api/v1/releases/{release.id}/confirm-handover", json={}, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    put = await client.put(f"/api/v1/releases/{release.id}", json={"operations_group_id": group.id},
                           headers=auth_headers)
    assert put.status_code == 200, put.text
    assert put.json()["operations_group_name"] == "Platform Ops"
    resp = await client.post(f"/api/v1/releases/{release.id}/confirm-handover",
                             json={"note": "runbook handed over"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["handover_confirmed_at"] is not None
    assert "Ops handover confirmed" in await _event_names(db_session, release.id)
    assert (await client.delete(f"/api/v1/releases/{release.id}/confirm-handover",
                                headers=auth_headers)).status_code == 200
    assert "Ops handover withdrawn" in await _event_names(db_session, release.id)


@pytest.mark.asyncio
async def test_a_release_manager_may_declare_and_a_developer_may_not(client, member_headers, release, db_session, test_tenant):
    assert (await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={},
                              headers=member_headers)).status_code == 403
    rm = await _rm_headers(client, db_session, test_tenant)
    assert (await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={},
                              headers=rm)).status_code == 200


@pytest.mark.asyncio
async def test_enterprise_releases_are_refused(client, auth_headers, enterprise_release):
    assert (await client.post(f"/api/v1/releases/{enterprise_release.id}/declare-stable", json={},
                              headers=auth_headers)).status_code == 422


@pytest.mark.asyncio
async def test_the_declarers_name_resolves_from_outside_the_releases_tenant(client, auth_headers, release, db_session, second_tenant_factory):
    """Master-admin impersonation: the actor legitimately sits outside the
    release's tenant. A tenant-qualified username join renders them as nobody."""
    other_tenant, other_user = await second_tenant_factory()
    release.declared_stable_by = other_user.id
    from datetime import datetime, timezone
    release.declared_stable_at = datetime.now(timezone.utc)
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}", headers=auth_headers)).json()
    assert body["declared_stable_by_username"] == other_user.username


@pytest.mark.asyncio
async def test_an_archived_group_survives_a_full_form_save(client, auth_headers, release, db_session, test_tenant):
    group = await ensure_user_group(db_session, test_tenant.id, name="Old Ops")
    await client.put(f"/api/v1/releases/{release.id}", json={"operations_group_id": group.id}, headers=auth_headers)
    from datetime import datetime, timezone
    group.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    resend = await client.put(f"/api/v1/releases/{release.id}",
                              json={"name": "R renamed", "operations_group_id": group.id}, headers=auth_headers)
    assert resend.status_code == 200, resend.text
    other = await ensure_user_group(db_session, test_tenant.id, name="Fresh")
    other.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    new_assign = await client.put(f"/api/v1/releases/{release.id}",
                                  json={"operations_group_id": other.id}, headers=auth_headers)
    assert new_assign.status_code == 404
```

Check `second_tenant_factory`'s return shape in `conftest.py:272-292` and that `PUT /api/v1/releases/{id}` is the update route (grep `@router.put("/{release_id}"` in `releases.py`); adjust if it is `PATCH`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_release_closeout_api.py -q`
Expected: 404s on the new routes; `KeyError: 'operations_group_name'`.

- [ ] **Step 3: Schemas**

`backend/app/api/v1/schemas/release.py`:
- `ReleaseCreate`: add `operations_group_id: Optional[int] = None`
- `ReleaseUpdate`: add `operations_group_id: Optional[int] = None`
- `ReleaseRead`: add after `scope_deadline`
```python
    operations_group_id: Optional[int] = None
    operations_group_name: Optional[str] = None
    declared_stable_at: Optional[datetime] = None
    declared_stable_by_username: Optional[str] = None
    handover_confirmed_at: Optional[datetime] = None
    handover_confirmed_by_username: Optional[str] = None
```

Create `backend/app/api/v1/schemas/closeout.py`:
```python
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditNote(BaseModel):
    """Body of the four audit routes. `extra="forbid"`: the lifecycle-template
    endpoint's silent-drop history is why every new request schema forbids."""
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(None, max_length=2000)
```

- [ ] **Step 4: `create_release` / `update_release`**

In `create_release`, after the `owning_project_id` validation:
```python
    if data.operations_group_id is not None:
        await user_group_service.get_group(db, data.operations_group_id, tenant_id)
```
and `operations_group_id=data.operations_group_id,` in the `Release(...)` constructor. Import `from app.services import user_group_service`.

In `update_release`, after the `owning_project_id` block:
```python
    if (
        "operations_group_id" in update_data
        and update_data["operations_group_id"] is not None
        and update_data["operations_group_id"] != release.operations_group_id
    ):
        # Same archived-value carve-out as owning_project_id above: a full-form
        # save re-sending the stored group must not 404 once it is archived.
        await user_group_service.get_group(db, update_data["operations_group_id"], tenant_id)
```

- [ ] **Step 5: Names on `ReleaseRead`**

In `release_closeout_service.py` add:
```python
async def usernames_for(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """DELIBERATELY NOT TENANT-QUALIFIED — see gate_waiver_service.usernames_for."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {r.id: r.username for r in rows}
```
(import `from app.db.models.user import User`.)

In `releases.py::_release_with_permissions`, after the `owning_project_name` block:
```python
    if release.operations_group_id is not None:
        group_names = await user_group_service.get_group_names(db, {release.operations_group_id})
        resp.operations_group_name = group_names.get(release.operations_group_id)
    names = await release_closeout_service.usernames_for(
        db, {release.declared_stable_by, release.handover_confirmed_by}
    )
    resp.declared_stable_by_username = names.get(release.declared_stable_by)
    resp.handover_confirmed_by_username = names.get(release.handover_confirmed_by)
```
Check `user_group_service` has a `get_group_names(db, ids)` read-rendering lookup that does NOT filter `deleted_at` (grep; A2/A4 established it for groups). If it is absent, add one in `user_group_service.py` shaped like `project_service.get_project_names`, and note in its docstring that it deliberately ignores `deleted_at`.

- [ ] **Step 6: Audit functions**

Append to `release_closeout_service.py` (imports: `from app.core.events import publish_event`, `from app.services import release_event_service`):

```python
EVENT_DECLARED_STABLE = "Declared stable"
EVENT_STABLE_WITHDRAWN = "Stability declaration withdrawn"
EVENT_HANDOVER_CONFIRMED = "Ops handover confirmed"
EVENT_HANDOVER_WITHDRAWN = "Ops handover withdrawn"


def _require_project_release(release: Release) -> None:
    if release.release_kind == "enterprise":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Hyper-care and closeout apply to project releases only")


async def _audit(db, release, tenant_id, user_id, event_name, note):
    await release_event_service.record_auto_event(
        db, release_id=release.id, tenant_id=tenant_id, user_id=user_id,
        event_type_name=event_name, description=note or event_name,
    )


async def declare_stable(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                         note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.declared_stable_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This release is already declared stable; withdraw the declaration first")
    release.declared_stable_at = datetime.now(timezone.utc)
    release.declared_stable_by = user_id
    await db.flush()
    await _audit(db, release, tenant_id, user_id, EVENT_DECLARED_STABLE, note)
    await publish_event(db, event_type="ReleaseDeclaredStable", aggregate_id=release.id,
                        aggregate_type="Release",
                        payload={"id": release.id, "name": release.name, "note": note},
                        tenant_id=tenant_id)
    return release


async def withdraw_stable(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                          note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.declared_stable_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This release is not declared stable")
    release.declared_stable_at = None
    release.declared_stable_by = None
    await db.flush()
    await _audit(db, release, tenant_id, user_id, EVENT_STABLE_WITHDRAWN, note)
    return release


async def confirm_handover(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                           note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.operations_group_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Set the release's operations group before confirming the handover")
    if release.handover_confirmed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Handover is already confirmed; withdraw it first")
    release.handover_confirmed_at = datetime.now(timezone.utc)
    release.handover_confirmed_by = user_id
    await db.flush()
    await _audit(db, release, tenant_id, user_id, EVENT_HANDOVER_CONFIRMED, note)
    return release


async def withdraw_handover(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                            note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.handover_confirmed_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Handover is not confirmed")
    release.handover_confirmed_at = None
    release.handover_confirmed_by = None
    await db.flush()
    await _audit(db, release, tenant_id, user_id, EVENT_HANDOVER_WITHDRAWN, note)
    return release
```

- [ ] **Step 7: Router**

```python
# backend/app/api/v1/release_closeout.py
"""Phase 9 C6 — declared stable, ops handover, and (Task 7) the closeout read.

Its own router rather than more lines in releases.py, the way go_no_go.py and
pir.py are. Mounted in main.py under /api/v1; every path starts /releases/{id}/
so no literal segment can collide with releases.py's `/{release_id}` catch-all.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.releases import _release_with_permissions
from app.api.v1.schemas.closeout import AuditNote
from app.api.v1.schemas.release import ReleaseRead
from app.core.security import Role, get_current_user, require_role
from app.db.base import get_db
from app.services import release_closeout_service, release_service

router = APIRouter(prefix="/releases", tags=["Closeout"])


async def _run(db, release_id, current_user, fn, note: Optional[str]) -> ReleaseRead:
    tenant_id = current_user.active_tenant_id
    release = await release_service.get_release(db, release_id, tenant_id)
    release = await fn(db, release, tenant_id=tenant_id, user_id=current_user.id, note=note)
    return await _release_with_permissions(db, release, current_user.role, current_user)


@router.post("/{release_id}/declare-stable", response_model=ReleaseRead)
async def declare_stable(release_id: int, data: AuditNote, db: AsyncSession = Depends(get_db),
                         current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.declare_stable, data.note)


@router.delete("/{release_id}/declare-stable", response_model=ReleaseRead)
async def withdraw_stable(release_id: int, db: AsyncSession = Depends(get_db),
                          current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.withdraw_stable, None)


@router.post("/{release_id}/confirm-handover", response_model=ReleaseRead)
async def confirm_handover(release_id: int, data: AuditNote, db: AsyncSession = Depends(get_db),
                           current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.confirm_handover, data.note)


@router.delete("/{release_id}/confirm-handover", response_model=ReleaseRead)
async def withdraw_handover(release_id: int, db: AsyncSession = Depends(get_db),
                            current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.withdraw_handover, None)
```

In `backend/app/main.py`, beside the go_no_go mount:
```python
from app.api.v1 import release_closeout as release_closeout_router
app.include_router(release_closeout_router.router, prefix="/api/v1", tags=["Closeout"])
```

- [ ] **Step 8: Run; remove Task 5's xfail**

Run: `cd backend && uv run pytest tests/test_release_closeout_api.py tests/test_c6_refuses_only_at_close.py tests/test_releases_api.py -q`
Expected: all pass, including the un-xfailed handover test.

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/v1/schemas/release.py backend/app/api/v1/schemas/closeout.py backend/app/api/v1/release_closeout.py backend/app/api/v1/releases.py backend/app/services/release_service.py backend/app/services/release_closeout_service.py backend/app/services/user_group_service.py backend/app/main.py backend/tests/test_release_closeout_api.py backend/tests/test_c6_refuses_only_at_close.py
git commit -m "feat(c6): operations group on release; declare-stable and confirm-handover audit routes with events"
```

---

### Task 7: `GET /releases/{id}/closeout` — the composite read

**Files:**
- Modify: `backend/app/api/v1/schemas/closeout.py`, `backend/app/services/release_closeout_service.py`, `backend/app/api/v1/release_closeout.py`
- Test: `backend/tests/test_release_closeout_api.py` (append)

**Interfaces:**
- Produces: schemas `HypercarePhaseRead {id, name, start_date, end_date}`, `HypercareRead {state, phase, declared_stable_at, declared_stable_by_username}`, `HandoverRead {operations_group_id, operations_group_name, confirmed_at, confirmed_by_username}`, `PirStateRead {exists, status, completed_at}`, `IncidentWindowItem {id, title, severity, status, detected_at}`, `IncidentsWindowRead {window_start, window_end, by_severity, total, items}`, `CloseTargetRead {state_key, label, requires_pir_complete, requires_handover_confirmed, unmet, can_close}`, `CloseoutRead {hypercare, handover, pir, incidents, close_targets}`. Service: `async def build_closeout(db, release, tenant_id, now) -> CloseoutRead`, `async def incidents_in_window(db, release, phase, now) -> IncidentsWindowRead`, `INCIDENT_ITEM_CAP = 50`.

- [ ] **Step 1: Append the failing tests**

```python
# append to backend/tests/test_release_closeout_api.py
from datetime import datetime, timedelta, timezone

from app.db.models.test_phase import TestPhase
from tests.factories import make_incident


async def _hypercare_phase(db_session, release, start, end):
    phase = TestPhase(tenant_id=release.tenant_id, release_id=release.id, name="Hyper-care",
                      order=9, start_date=start, end_date=end, status="pending", kind="hypercare")
    db_session.add(phase)
    await db_session.commit()
    return phase


@pytest.mark.asyncio
async def test_closeout_read_with_nothing_set(client, auth_headers, release):
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["hypercare"] == {"state": "none", "phase": None,
                                 "declared_stable_at": None, "declared_stable_by_username": None}
    assert body["handover"]["operations_group_id"] is None
    assert body["pir"] == {"exists": False, "status": None, "completed_at": None}
    assert body["incidents"]["total"] == 0 and body["incidents"]["window_start"] is None
    # Major's closed states, in template order, none requiring anything yet.
    assert [t["state_key"] for t in body["close_targets"]] == ["completed", "completed_with_issues", "backed_out"]
    assert all(t["can_close"] and t["unmet"] == [] for t in body["close_targets"])


@pytest.mark.asyncio
async def test_close_targets_reflect_the_flags_and_the_same_wording_as_the_422(
    client, auth_headers, release, db_session
):
    from app.db.models.lifecycle import LifecycleTemplate
    tpl = await db_session.get(LifecycleTemplate, release.lifecycle_template_id)
    defn = dict(tpl.definition)
    for s in defn["states"]:
        if s["key"] == "completed":
            s["requires_pir_complete"] = True
            s["requires_handover_confirmed"] = True
    tpl.definition = defn
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    completed = next(t for t in body["close_targets"] if t["state_key"] == "completed")
    assert completed["can_close"] is False
    assert completed["unmet"] == ["the post-implementation review is not complete",
                                  "ops handover is not confirmed"]
    refused = await client.post(f"/api/v1/releases/{release.id}/transition",
                                json={"to_state": "completed"}, headers=auth_headers)
    assert refused.status_code == 422
    for reason in completed["unmet"]:
        assert reason in refused.json()["detail"]


@pytest.mark.asyncio
async def test_incidents_in_the_window_and_only_those(client, auth_headers, release, db_session, test_tenant, test_user):
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=10), now + timedelta(days=4)
    await _hypercare_phase(db_session, release, start, end)
    inside = await make_incident(db_session, test_tenant.id, title="inside", severity="P1",
                                 detected_at=now - timedelta(days=2))
    inside.release_id = release.id
    before = await make_incident(db_session, test_tenant.id, title="before", severity="P2",
                                 detected_at=start - timedelta(seconds=1))
    before.release_id = release.id
    other_release = await make_incident(db_session, test_tenant.id, title="other", severity="P1",
                                        detected_at=now - timedelta(days=1))
    await db_session.commit()

    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["hypercare"]["state"] == "active"
    assert body["incidents"]["total"] == 1
    assert [i["title"] for i in body["incidents"]["items"]] == ["inside"]
    assert body["incidents"]["by_severity"] == {"P1": 1, "P2": 0, "P3": 0, "P4": 0}
    assert datetime.fromisoformat(body["incidents"]["window_start"]) == start
    # Not yet ended and not declared: the window closes at `now`.
    assert datetime.fromisoformat(body["incidents"]["window_end"]) <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_declaring_stable_closes_the_window(client, auth_headers, release, db_session, test_tenant):
    now = datetime.now(timezone.utc)
    await _hypercare_phase(db_session, release, now - timedelta(days=10), now + timedelta(days=10))
    await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    late = await make_incident(db_session, test_tenant.id, title="after stable", severity="P3",
                               detected_at=now + timedelta(minutes=5))
    late.release_id = release.id
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["hypercare"]["state"] == "stable"
    assert body["incidents"]["total"] == 0


@pytest.mark.asyncio
async def test_another_tenants_incident_is_never_counted(client, auth_headers, release, db_session, second_tenant_factory):
    other_tenant, _ = await second_tenant_factory()
    now = datetime.now(timezone.utc)
    await _hypercare_phase(db_session, release, now - timedelta(days=3), None)
    foreign = await make_incident(db_session, other_tenant.id, title="foreign", detected_at=now)
    foreign.release_id = release.id  # constructible: tenant_id and release_id are uncross-checked
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["incidents"]["total"] == 0


@pytest.mark.asyncio
async def test_a_template_with_no_closed_state_returns_an_empty_target_list(client, auth_headers, db_session, test_tenant, test_user):
    from app.db.models.lifecycle import LifecycleTemplate
    tpl = LifecycleTemplate(tenant_id=test_tenant.id, entity_type="release", name="NoClose", is_default=False,
                            applies_to_kind="project",
                            definition={"states": [{"key": "draft", "label": "D", "is_initial": True, "is_terminal": False},
                                                   {"key": "done", "label": "Done", "is_initial": False, "is_terminal": True}],
                                        "transitions": [], "field_permissions": {}})
    db_session.add(tpl)
    await db_session.flush()
    rel = Release(tenant_id=test_tenant.id, name="NC", release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{rel.id}/closeout", headers=auth_headers)).json()
    assert body["close_targets"] == []


@pytest.mark.asyncio
async def test_closeout_read_is_open_to_a_developer_and_refused_on_enterprise(client, member_headers, auth_headers, release, enterprise_release):
    assert (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=member_headers)).status_code == 200
    assert (await client.get(f"/api/v1/releases/{enterprise_release.id}/closeout", headers=auth_headers)).status_code == 422
```

Check `make_incident`'s signature accepts `severity=` and `detected_at=` (factories.py:604) — it does — and whether it commits; set `release_id` after creation as shown and commit once.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_release_closeout_api.py -q -k "closeout_read or close_targets or incidents or declaring_stable_closes or no_closed_state"`
Expected: 404 on the route.

- [ ] **Step 3: Schemas**

Append to `backend/app/api/v1/schemas/closeout.py`:
```python
from datetime import datetime


class HypercarePhaseRead(BaseModel):
    id: int
    name: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]


class HypercareRead(BaseModel):
    state: str  # none | planned | active | overdue | stable
    phase: Optional[HypercarePhaseRead]
    declared_stable_at: Optional[datetime]
    declared_stable_by_username: Optional[str]


class HandoverRead(BaseModel):
    operations_group_id: Optional[int]
    operations_group_name: Optional[str]
    confirmed_at: Optional[datetime]
    confirmed_by_username: Optional[str]


class PirStateRead(BaseModel):
    exists: bool
    status: Optional[str]
    completed_at: Optional[datetime]


class IncidentWindowItem(BaseModel):
    id: int
    title: str
    severity: str
    status: str
    detected_at: datetime


class IncidentsWindowRead(BaseModel):
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    by_severity: dict[str, int]
    total: int
    items: list[IncidentWindowItem]


class CloseTargetRead(BaseModel):
    state_key: str
    label: str
    requires_pir_complete: bool
    requires_handover_confirmed: bool
    unmet: list[str]
    can_close: bool


class CloseoutRead(BaseModel):
    hypercare: HypercareRead
    handover: HandoverRead
    pir: PirStateRead
    incidents: IncidentsWindowRead
    close_targets: list[CloseTargetRead]
```

- [ ] **Step 4: Service**

Append to `release_closeout_service.py` (imports: `from app.core.pagination import Page, Sort`, `from app.db.models.incident import Incident`, `from app.db.models.lifecycle import LifecycleTemplate`, `from app.services import incident_service, user_group_service`, and the schemas from `app.api.v1.schemas.closeout`):

```python
INCIDENT_ITEM_CAP = 50
SEVERITIES = ("P1", "P2", "P3", "P4")


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def incidents_in_window(db: AsyncSession, release: Release, phase, now: datetime) -> IncidentsWindowRead:
    """Incidents whose CAUSAL release is this one, detected inside the window.
    Window: phase start (or the phase's created_at if undated) → the earliest
    of declared_stable_at, phase end, now. No phase: no window, nothing counted."""
    if phase is None:
        return IncidentsWindowRead(window_start=None, window_end=None,
                                   by_severity={s: 0 for s in SEVERITIES}, total=0, items=[])
    start = _aware(phase.start_date) or _aware(phase.created_at)
    candidates = [v for v in (_aware(release.declared_stable_at), _aware(phase.end_date), now) if v is not None]
    end = min(candidates)
    filters = {"release_id": release.id, "date_from": start, "date_to": end}
    rows, total = await incident_service.list_incidents(
        db, release.tenant_id, filters, page=Page(limit=INCIDENT_ITEM_CAP, offset=0),
        sort=Sort(column=Incident.detected_at, descending=True),
    )
    by_severity = {s: 0 for s in SEVERITIES}
    for sev in SEVERITIES:
        _, count = await incident_service.list_incidents(
            db, release.tenant_id, {**filters, "severity": sev}, page=Page(limit=1, offset=0))
        by_severity[sev] = count
    return IncidentsWindowRead(
        window_start=start, window_end=end, by_severity=by_severity, total=total,
        items=[IncidentWindowItem(id=r.id, title=r.title, severity=r.severity, status=r.status,
                                  detected_at=r.detected_at) for r in rows],
    )


async def build_closeout(db: AsyncSession, release: Release, tenant_id: int, now: datetime) -> CloseoutRead:
    _require_project_release(release)
    phase = await live_hypercare_phase(db, release.id, tenant_id)
    pir = await pir_service.get_for_release(db, tenant_id, release.id)
    names = await usernames_for(db, {release.declared_stable_by, release.handover_confirmed_by})
    group_name = None
    if release.operations_group_id is not None:
        group_name = (await user_group_service.get_group_names(db, {release.operations_group_id})
                      ).get(release.operations_group_id)
    tpl = await db.get(LifecycleTemplate, release.lifecycle_template_id)
    targets = []
    for state in (tpl.definition.get("states", []) if tpl else []):
        if not state.get("is_closed"):
            continue
        unmet = unmet_requirements(state, pir, release)
        targets.append(CloseTargetRead(
            state_key=state["key"], label=state.get("label", state["key"]),
            requires_pir_complete=bool(state.get("requires_pir_complete")),
            requires_handover_confirmed=bool(state.get("requires_handover_confirmed")),
            unmet=unmet, can_close=not unmet,
        ))
    return CloseoutRead(
        hypercare=HypercareRead(
            state=hypercare_state(phase, release.declared_stable_at, now),
            phase=HypercarePhaseRead(id=phase.id, name=phase.name, start_date=phase.start_date,
                                     end_date=phase.end_date) if phase else None,
            declared_stable_at=release.declared_stable_at,
            declared_stable_by_username=names.get(release.declared_stable_by),
        ),
        handover=HandoverRead(
            operations_group_id=release.operations_group_id, operations_group_name=group_name,
            confirmed_at=release.handover_confirmed_at,
            confirmed_by_username=names.get(release.handover_confirmed_by),
        ),
        pir=PirStateRead(exists=pir is not None, status=pir.status if pir else None,
                         completed_at=pir.completed_at if pir else None),
        incidents=await incidents_in_window(db, release, phase, now),
        close_targets=targets,
    )
```

Check `incident_service.list_incidents` tolerates `sort=` with `page=` given together (signature at `incident_service.py:106-112` says yes) and that `Incident.title` is the column name (grep the model).

- [ ] **Step 5: Route**

Append to `release_closeout.py`:
```python
from datetime import datetime, timezone
from app.api.v1.schemas.closeout import CloseoutRead


@router.get("/{release_id}/closeout", response_model=CloseoutRead)
async def read_closeout(release_id: int, db: AsyncSession = Depends(get_db),
                        current_user=Depends(get_current_user)):
    """Open to any tenant member — the same read the transition's 422 is
    computed from, so the tab and the refusal cannot disagree."""
    tenant_id = current_user.active_tenant_id
    release = await release_service.get_release(db, release_id, tenant_id)
    return await release_closeout_service.build_closeout(db, release, tenant_id, datetime.now(timezone.utc))
```

- [ ] **Step 6: Run and commit**

Run: `cd backend && uv run pytest tests/test_release_closeout_api.py tests/test_release_closeout_service.py -q`
Expected: pass.

```bash
git add backend/app/api/v1/schemas/closeout.py backend/app/services/release_closeout_service.py backend/app/api/v1/release_closeout.py backend/tests/test_release_closeout_api.py
git commit -m "feat(c6): GET /releases/{id}/closeout composite read"
```

---

### Task 8: Sixth `/me/work` queue — hyper-care decisions

**Files:**
- Modify: `backend/app/services/release_closeout_service.py`, `backend/app/services/my_work_service.py:350-355`
- Test: `backend/tests/test_me_work_matches_worklists.py` (append), `backend/tests/test_my_work_service.py:26-50` (queue-key set)

**Interfaces:**
- Produces: `async def hypercare_queue(db, tenant_id, now, page) -> tuple[list[Row], int]` returning rows `(release_id, release_name, end_date)`; `async def hypercare_overdue_total(db, tenant_id, now) -> int`; `HORIZON_DAYS = 7`. Queue key `"hypercare"`.

- [ ] **Step 1: Append the failing test**

```python
# append to backend/tests/test_me_work_matches_worklists.py
from datetime import datetime, timedelta, timezone

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase


async def _release_in_hypercare(db_session, tenant_id, user_id, name, *, end, declared=None):
    tpl = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == tenant_id, LifecycleTemplate.entity_type == "release",
        LifecycleTemplate.applies_to_kind == "project"))).scalars().first()
    if tpl is None:
        tpl = LifecycleTemplate(tenant_id=tenant_id, entity_type="release", name="HC", is_default=True,
                                applies_to_kind="project",
                                definition={"states": [{"key": "draft", "label": "D", "is_initial": True, "is_terminal": False}],
                                            "transitions": [], "field_permissions": {}})
        db_session.add(tpl)
        await db_session.flush()
    rel = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=user_id,
                  declared_stable_at=declared, declared_stable_by=user_id if declared else None)
    db_session.add(rel)
    await db_session.flush()
    db_session.add(TestPhase(tenant_id=tenant_id, release_id=rel.id, name="HC", order=1,
                             start_date=end - timedelta(days=14), end_date=end, status="pending",
                             kind="hypercare"))
    await db_session.commit()
    return rel


@pytest.mark.asyncio
async def test_hypercare_queue_lists_overdue_first_then_ending_soon(client, auth_headers, test_tenant, test_user, db_session):
    """Overdue windows first, then windows ending within seven days; a
    declared-stable release and a window twenty days out are NOT counted."""
    now = datetime.now(timezone.utc)
    await _release_in_hypercare(db_session, test_tenant.id, test_user.id, "soon", end=now + timedelta(days=3))
    await _release_in_hypercare(db_session, test_tenant.id, test_user.id, "overdue", end=now - timedelta(days=2))
    await _release_in_hypercare(db_session, test_tenant.id, test_user.id, "stable", end=now - timedelta(days=2),
                                declared=now)
    await _release_in_hypercare(db_session, test_tenant.id, test_user.id, "far", end=now + timedelta(days=20))

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    assert mine.status_code == 200, mine.text
    queue = mine.json()["queues"]["hypercare"]
    assert [i["title"] for i in queue["items"]] == ["overdue", "soon"]
    assert queue["count"] == 2 and queue["overdue"] == 1
    assert queue["items"][0]["url"].endswith("?tab=closeout")
```

And in `backend/tests/test_my_work_service.py` add `"hypercare"` to the expected queue-key set at lines 26-50.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_me_work_matches_worklists.py tests/test_my_work_service.py -q`
Expected: `KeyError: 'hypercare'`.

- [ ] **Step 3: Service query**

Append to `release_closeout_service.py` (imports: `from datetime import timedelta`, `from sqlalchemy import and_`, `from app.core.pagination import fetch_page_rows`):

```python
HORIZON_DAYS = 7


def _hypercare_queue_query(tenant_id: int, boundary: datetime, *, overdue_only: bool):
    """Live hyper-care phases with an end DAY that is past, or within HORIZON_DAYS
    of today, on project releases not yet declared stable. `boundary` is
    `expiry_boundary(now)`, one clock per request. Tiebreaker: release id."""
    latest = boundary if overdue_only else boundary + timedelta(days=HORIZON_DAYS + 1)
    return (
        select(Release.id, Release.name, TestPhase.end_date)
        .join(TestPhase, and_(TestPhase.release_id == Release.id, TestPhase.kind == HYPERCARE,
                              TestPhase.deleted_at.is_(None)))
        .where(
            Release.tenant_id == tenant_id,
            Release.deleted_at.is_(None),
            Release.release_kind == "project",
            Release.declared_stable_at.is_(None),
            TestPhase.end_date.is_not(None),
            TestPhase.end_date < latest,
        )
        .order_by(TestPhase.end_date.asc(), Release.id.asc())
    )


async def hypercare_queue(db: AsyncSession, tenant_id: int, now: datetime, page: Page):
    return await fetch_page_rows(db, _hypercare_queue_query(tenant_id, expiry_boundary(now), overdue_only=False), page)


async def hypercare_overdue_total(db: AsyncSession, tenant_id: int, now: datetime) -> int:
    _, total = await fetch_page_rows(
        db, _hypercare_queue_query(tenant_id, expiry_boundary(now), overdue_only=True), Page(limit=1, offset=0))
    return total
```

`end < boundary` means the end day is before today (overdue). `end < boundary + 8 days` includes today through today+7 — "ending within seven days" — and everything overdue.

- [ ] **Step 4: Queue builder**

In `my_work_service.py`, add (import `from app.services import release_closeout_service`):

```python
async def _hypercare_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Hyper-care windows that are overdue for a stability decision, or end
    within seven days. Tenant-wide, like incidents: a release has no per-user
    owner to narrow on. `due` is the window's end; `overdue` is a separate
    limit=1 count sharing the same `now`."""
    rows, total = await release_closeout_service.hypercare_queue(
        db, tenant_id, now, Page(limit=ITEM_CAP, offset=0))
    overdue = await release_closeout_service.hypercare_overdue_total(db, tenant_id, now)
    items = [
        WorkItem(id=rid, title=name, subtitle="Hyper-care window ends",
                 url=f"/releases/{rid}?tab=closeout", due=end_date)
        for rid, name, end_date in rows
    ]
    return QueueResult(count=total, items=items, overdue=overdue)
```
and register `"hypercare": _hypercare_queue,` at the end of the `builders` dict in `build()`.

- [ ] **Step 5: Run both legs' my-work tests and commit**

Run: `cd backend && uv run pytest tests/test_me_work_matches_worklists.py tests/test_my_work_service.py -q` and once more with `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test` (no other PostgreSQL run in flight).
Expected: pass on both.

```bash
git add backend/app/services/release_closeout_service.py backend/app/services/my_work_service.py backend/tests/test_me_work_matches_worklists.py backend/tests/test_my_work_service.py
git commit -m "feat(c6): hyper-care decisions queue on GET /me/work"
```

---

### Task 9: Frontend types, service, slice, and the transition refusal reaching the snackbar

**Files:**
- Modify: `frontend/src/types/bookingLifecycle.ts:3-11`, `frontend/src/types/release.ts` (`ReleaseResponse`, `ReleaseUpdatePayload`, `TestPhaseResponse`, `TestPhaseCreatePayload`, `TestPhaseUpdatePayload`), `frontend/src/types/releaseTemplate.ts:1-6`, `frontend/src/types/myWork.ts`
- Modify: `frontend/src/store/releaseSlice.ts:117-126`, `frontend/src/components/releases/ReleaseMainTab.tsx:68-80`, `frontend/src/store/index.ts:39-82`
- Create: `frontend/src/types/closeout.ts`, `frontend/src/services/closeoutService.ts`, `frontend/src/store/closeoutSlice.ts`
- Test: `frontend/src/components/releases/__tests__/releaseMainTabRefusal.test.tsx`

**Interfaces:**
- Produces: `closeoutService.get(releaseId)`, `.declareStable(releaseId, note?)`, `.withdrawStable(releaseId)`, `.confirmHandover(releaseId, note?)`, `.withdrawHandover(releaseId)`; thunks `fetchCloseout`, `declareStable`, `withdrawStable`, `confirmHandover`, `withdrawHandover` (all `{ rejectValue: string }`); state `closeout: { byRelease: Record<number, CloseoutRead>, loading, error }`; `transitionRelease` now `rejectWithValue(formatApiError(err, 'Transition failed'))`.

- [ ] **Step 1: Types**

`frontend/src/types/bookingLifecycle.ts` — extend `LifecycleState`:
```ts
  /** C6, project release templates only: entering stamps actual_date once. */
  marks_deployed?: boolean;
  /** C6: this terminal state means the release is formally closed. */
  is_closed?: boolean;
  requires_pir_complete?: boolean;
  requires_handover_confirmed?: boolean;
```

`frontend/src/types/release.ts`:
- `ReleaseResponse`: add `operations_group_id: number | null; operations_group_name: string | null; declared_stable_at: string | null; declared_stable_by_username: string | null; handover_confirmed_at: string | null; handover_confirmed_by_username: string | null;`
- `ReleaseUpdatePayload`: add `operations_group_id?: number | null;`
- `export type PhaseKind = 'test' | 'hypercare';` then `kind: PhaseKind;` on `TestPhaseResponse`, `kind?: PhaseKind;` on both payloads.

`frontend/src/types/releaseTemplate.ts`: `kind?: 'test' | 'hypercare';` on `ReleaseTemplatePhase`.

`frontend/src/types/myWork.ts`: add `'hypercare'` to `MyWorkQueueKey`.

Create `frontend/src/types/closeout.ts`:
```ts
export type HypercareState = 'none' | 'planned' | 'active' | 'overdue' | 'stable';

export interface CloseTarget {
  state_key: string;
  label: string;
  requires_pir_complete: boolean;
  requires_handover_confirmed: boolean;
  unmet: string[];
  can_close: boolean;
}

export interface CloseoutRead {
  hypercare: {
    state: HypercareState;
    phase: { id: number; name: string; start_date: string | null; end_date: string | null } | null;
    declared_stable_at: string | null;
    declared_stable_by_username: string | null;
  };
  handover: {
    operations_group_id: number | null;
    operations_group_name: string | null;
    confirmed_at: string | null;
    confirmed_by_username: string | null;
  };
  pir: { exists: boolean; status: string | null; completed_at: string | null };
  incidents: {
    window_start: string | null;
    window_end: string | null;
    by_severity: Record<string, number>;
    total: number;
    items: { id: number; title: string; severity: string; status: string; detected_at: string }[];
  };
  close_targets: CloseTarget[];
}
```

- [ ] **Step 2: Service and slice**

```ts
// frontend/src/services/closeoutService.ts
import api from './api';
import type { CloseoutRead } from '../types/closeout';
import type { ReleaseResponse } from '../types/release';

export const closeoutService = {
  get: (releaseId: number): Promise<CloseoutRead> =>
    api.get(`/releases/${releaseId}/closeout`).then((r) => r.data),
  declareStable: (releaseId: number, note?: string): Promise<ReleaseResponse> =>
    api.post(`/releases/${releaseId}/declare-stable`, { note: note ?? null }).then((r) => r.data),
  withdrawStable: (releaseId: number): Promise<ReleaseResponse> =>
    api.delete(`/releases/${releaseId}/declare-stable`).then((r) => r.data),
  confirmHandover: (releaseId: number, note?: string): Promise<ReleaseResponse> =>
    api.post(`/releases/${releaseId}/confirm-handover`, { note: note ?? null }).then((r) => r.data),
  withdrawHandover: (releaseId: number): Promise<ReleaseResponse> =>
    api.delete(`/releases/${releaseId}/confirm-handover`).then((r) => r.data),
};
```

```ts
// frontend/src/store/closeoutSlice.ts
import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { closeoutService } from '../services/closeoutService';
import { formatApiError } from '../services/apiError';
import type { CloseoutRead } from '../types/closeout';

interface CloseoutState {
  byRelease: Record<number, CloseoutRead>;
  loading: boolean;
  error: string | null;
}
const initialState: CloseoutState = { byRelease: {}, loading: false, error: null };

export const fetchCloseout = createAsyncThunk<CloseoutRead, number, { rejectValue: string }>(
  'closeout/fetch',
  async (releaseId, { rejectWithValue }) => {
    try { return await closeoutService.get(releaseId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load closeout')); }
  },
);

// Every write re-fetches the composite read, so the tab renders what the
// server computed rather than a local guess. Consumers read `result.payload`.
const write = (name: string, call: (releaseId: number, note?: string) => Promise<unknown>) =>
  createAsyncThunk<CloseoutRead, { releaseId: number; note?: string }, { rejectValue: string }>(
    `closeout/${name}`,
    async ({ releaseId, note }, { rejectWithValue }) => {
      try {
        await call(releaseId, note);
        return await closeoutService.get(releaseId);
      } catch (err) {
        return rejectWithValue(formatApiError(err, `Failed to ${name}`));
      }
    },
  );

export const declareStable = write('declare stable', closeoutService.declareStable);
export const withdrawStable = write('withdraw stability declaration', (id) => closeoutService.withdrawStable(id));
export const confirmHandover = write('confirm handover', closeoutService.confirmHandover);
export const withdrawHandover = write('withdraw handover', (id) => closeoutService.withdrawHandover(id));

const closeoutSlice = createSlice({
  name: 'closeout',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchCloseout.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchCloseout.fulfilled, (s, a) => { s.loading = false; s.byRelease[a.meta.arg] = a.payload; });
    b.addCase(fetchCloseout.rejected, (s, a) => { s.loading = false; s.error = a.payload ?? 'Failed to load closeout'; });
    for (const t of [declareStable, withdrawStable, confirmHandover, withdrawHandover]) {
      b.addCase(t.fulfilled, (s, a) => { s.byRelease[a.meta.arg.releaseId] = a.payload; });
    }
  },
});
export default closeoutSlice.reducer;
```

Register in `frontend/src/store/index.ts`: `import closeoutReducer from './closeoutSlice';` and `closeout: closeoutReducer,` after `goNoGo`.

- [ ] **Step 3: The failing refusal test**

```tsx
// frontend/src/components/releases/__tests__/releaseMainTabRefusal.test.tsx
/**
 * A refused close must reach the user as the SERVER'S reason, not Axios's
 * "Request failed with status code 422". A plain Error carrying the final
 * text would pass a naive test while the app shows the generic message, so
 * the rejection here is a real AxiosError shape.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { AxiosError } from 'axios';
import { store } from '../../../store';
import { releaseService } from '../../../services/releaseService';
import ReleaseMainTab from '../ReleaseMainTab';

vi.mock('../../../services/releaseService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/releaseService')>();
  return { ...actual, releaseService: { ...actual.releaseService, transition: vi.fn(), getLifecycle: vi.fn(), get: vi.fn() } };
});

const lifecycle = {
  id: 1, definition: {
    states: [
      { key: 'live', label: 'Live', is_initial: false, is_terminal: false },
      { key: 'completed', label: 'Completed', is_initial: false, is_terminal: true, is_closed: true, requires_pir_complete: true },
    ],
    transitions: [{ from_state: 'live', to_state: 'completed', label: 'Close', allowed_roles: ['Admin'] }],
    field_permissions: { live: { standard_fields: {}, custom_fields: {} }, completed: { standard_fields: {}, custom_fields: {} } },
  },
};

describe('ReleaseMainTab — a refused close shows the server reason', () => {
  beforeEach(() => {
    vi.mocked(releaseService.getLifecycle).mockResolvedValue(lifecycle as never);
    const err = new AxiosError('Request failed with status code 422');
    (err as unknown as { response: unknown }).response = {
      status: 422, data: { detail: 'Cannot close this release: the post-implementation review is not complete.' },
    };
    vi.mocked(releaseService.transition).mockRejectedValue(err);
  });

  it('renders the 422 detail, not the Axios message', async () => {
    // Seed the release + admin user into the singleton store the way
    // releaseDetailTabs.test.tsx does (setCredentials + the release slice's
    // fulfilled action); see that file for the exact dispatches.
    render(<Provider store={store}><MemoryRouter><ReleaseMainTab releaseId={7} /></MemoryRouter></Provider>);
    await userEvent.click(await screen.findByRole('button', { name: /close/i }));
    await userEvent.click(await screen.findByRole('button', { name: /confirm/i }));
    await waitFor(() =>
      expect(screen.getByText(/post-implementation review is not complete/i)).toBeInTheDocument());
    expect(screen.queryByText(/status code 422/)).not.toBeInTheDocument();
  });
});
```

Read `ReleaseMainTab.tsx`'s props and `releaseDetailTabs.test.tsx`'s store seeding, then fill the seeding line in; the two assertions at the end are the contract. Run it: expected FAIL with "status code 422" rendered.

- [ ] **Step 4: Make the refusal reach the snackbar**

`frontend/src/store/releaseSlice.ts`:
```ts
export const transitionRelease = createAsyncThunk<
  ReleaseResponse,
  { id: number; data: ReleaseTransitionPayload },
  { rejectValue: string }
>('release/transition', async ({ id, data }, { rejectWithValue }) => {
  try { return await releaseService.transition(id, data); }
  catch (err) { return rejectWithValue(formatApiError(err, 'Transition failed')); }
});
```

`frontend/src/components/releases/ReleaseMainTab.tsx` `handleTransition`:
```ts
    const result = await dispatch(transitionRelease({ id: releaseId, data: { to_state: toState, notes } }));
    if (transitionRelease.rejected.match(result)) {
      snackbar.error(result.payload ?? 'Transition failed');
      return;
    }
    const tpl = await releaseService.getLifecycle(releaseId);
    setLifecycleTpl(tpl);
    snackbar.success(`Transitioned to ${toState}`);
```
(drop the surrounding try/catch's reliance on `err.message`; keep a catch for the lifecycle re-fetch if you like, with the fallback text.)

- [ ] **Step 5: Run, lint, typecheck, commit**

Run: `cd frontend && npx vitest run src/components/releases/__tests__/releaseMainTabRefusal.test.tsx src/pages/releases/__tests__ && npx tsc --noEmit && npm run lint`
Expected: pass, no type errors.

```bash
git add frontend/src/types frontend/src/services/closeoutService.ts frontend/src/store/closeoutSlice.ts frontend/src/store/index.ts frontend/src/store/releaseSlice.ts frontend/src/components/releases/ReleaseMainTab.tsx frontend/src/components/releases/__tests__/releaseMainTabRefusal.test.tsx
git commit -m "feat(c6): closeout types/service/slice; refused transitions show the server reason"
```

---

### Task 10: Lifecycle editor — the four checkboxes, and `is_failed` in every payload

**Files:**
- Modify: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx:95-122, 240-255, 325-340, 691-721`
- Test: `frontend/src/components/admin/__tests__/lifecycleTemplatesPanel.test.tsx` (append)

- [ ] **Step 1: The failing payload test**

Append to `lifecycleTemplatesPanel.test.tsx` (reuse its existing render + service-mock setup; it mocks `bookingLifecycleService`):

```tsx
it('saves is_failed and the C6 flags on every state, never dropping them', async () => {
  // Open the edit dialog for a project release template whose `completed`
  // state is terminal + failed + closed + requires PIR (seed the mocked list
  // with such a template the way the delete test seeds its rows).
  // ...render, open edit, tick nothing, click Save...
  const [, payload] = vi.mocked(bookingLifecycleService.updateTemplate).mock.calls[0];
  const completed = payload.definition.states.find((s) => s.key === 'completed');
  expect(completed).toMatchObject({
    is_terminal: true, is_failed: true, is_closed: true,
    requires_pir_complete: true, requires_handover_confirmed: false, marks_deployed: true,
  });
  const draft = payload.definition.states.find((s) => s.key === 'draft');
  expect(Object.keys(draft).sort()).toEqual(
    ['is_closed', 'is_failed', 'is_initial', 'is_terminal', 'key', 'label',
     'marks_deployed', 'requires_handover_confirmed', 'requires_pir_complete'].sort());
});

it('hides the C6 checkboxes on an enterprise template and shows them on a project one', async () => {
  // render with an enterprise template selected: no 'Closed' / 'Marks deployed' checkbox
  // render with a project template selected and a terminal state: 'Closed' present;
  // tick 'Closed' → 'Require PIR complete' and 'Require ops handover confirmed' appear.
});
```
Fill the two `// ...` blocks using the file's existing helpers (the delete test at `:92` shows the list seeding and dialog opening; `within(dialog).getAllByLabelText('Key')` at `:129` shows querying inside the dialog). Assertions above are the contract. Run: expected FAIL (`is_failed` absent on `draft`; no checkbox named Closed).

- [ ] **Step 2: Implement**

`StateRow`: add `marks_deployed: boolean; is_closed: boolean; requires_pir_complete: boolean; requires_handover_confirmed: boolean;` with `false` defaults in the factory (`:115-122`) and in `handleEditOpen`'s mapping (`:246-253`, `?? false` each).

Save payload (`:327-334`):
```ts
      states: states.map((s) => ({
        key: s.key.trim(),
        label: s.label.trim(),
        is_initial: s.is_initial,
        is_terminal: s.is_terminal,
        is_failed: s.is_terminal && (s.is_failed ?? false),
        ...(isEnterprise
          ? { is_admission_lockdown: s.is_admission_lockdown,
              marks_deployed: false, is_closed: false,
              requires_pir_complete: false, requires_handover_confirmed: false }
          : { marks_deployed: s.marks_deployed,
              is_closed: s.is_terminal && s.is_closed,
              requires_pir_complete: s.is_terminal && s.is_closed && s.requires_pir_complete,
              requires_handover_confirmed: s.is_terminal && s.is_closed && s.requires_handover_confirmed }),
      })),
```
(`is_failed` is now sent for every state — the fix; `false` where not applicable.)

Checkbox JSX, after the *Counts as failure* block, for `!isEnterprise` only:
```tsx
{!isEnterprise && (
  <FormControlLabel control={<Checkbox size="small" checked={s.marks_deployed}
    onChange={(e) => updateState(i, { marks_deployed: e.target.checked })} />} label="Marks deployed" />
)}
{!isEnterprise && s.is_terminal && (
  <FormControlLabel control={<Checkbox size="small" checked={s.is_closed}
    onChange={(e) => updateState(i, { is_closed: e.target.checked })} />} label="Closed" />
)}
{!isEnterprise && s.is_terminal && s.is_closed && (
  <>
    <FormControlLabel control={<Checkbox size="small" checked={s.requires_pir_complete}
      onChange={(e) => updateState(i, { requires_pir_complete: e.target.checked })} />} label="Require PIR complete" />
    <FormControlLabel control={<Checkbox size="small" checked={s.requires_handover_confirmed}
      onChange={(e) => updateState(i, { requires_handover_confirmed: e.target.checked })} />} label="Require ops handover confirmed" />
  </>
)}
```
Add a one-line `<Typography variant="caption">` under the states list on project templates: "Closed marks the states that formally close a release; the two Require options are the close gate. Marks deployed stamps the release's actual date."

- [ ] **Step 3: Run and commit**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/lifecycleTemplatesPanel.test.tsx && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/components/admin/LifecycleTemplatesPanel.tsx frontend/src/components/admin/__tests__/lifecycleTemplatesPanel.test.tsx
git commit -m "feat(c6): lifecycle editor flags (closed, marks deployed, close gates); is_failed sent on every save"
```

---

### Task 11: Phase kind in the table, dialog, Gantt and template form

**Files:**
- Modify: `frontend/src/components/releases/PhasesTable.tsx:38-50, 60-67, 133-172, 206-219`, `frontend/src/components/releases/PhaseGanttEditor.tsx:22-27, 93, 150-155`, `frontend/src/pages/admin/release-templates/ReleaseTemplateForm.tsx:43, 246-315`
- Test: `frontend/src/components/releases/__tests__/phasesTableKind.test.tsx` (create), `frontend/src/pages/admin/release-templates/__tests__/ReleaseTemplateForm.test.tsx` (append)

- [ ] **Step 1: Failing tests**

`phasesTableKind.test.tsx` (use `createDataGridMock` + `getLastDataGridProps` from `src/test/dataGridMock` as `goNoGoTab.test.tsx` does; mock `releaseSlice` thunks or the service as that file does):
```tsx
it('shows a Kind column and sends kind on create', async () => {
  // render <PhasesTable releaseId={7} phases={[{...test phase}, {...hypercare phase}]} />
  const props = getLastDataGridProps();
  expect(props.columns.map((c) => c.field)).toContain('kind');
  // open "Add phase", choose Kind = Hyper-care, name it, save:
  // expect(vi.mocked(releaseService.createPhase)).toHaveBeenCalledWith(7, expect.objectContaining({ kind: 'hypercare' }));
});
```
`ReleaseTemplateForm.test.tsx` append, following its `:183-195` key-set test:
```tsx
it('sends kind on every template phase', async () => {
  // ...render, add a phase, set its Kind to Hyper-care, save...
  const [, payload] = vi.mocked(releaseTemplateService.update).mock.calls[0];
  expect(payload.phases.every((p) => ['test', 'hypercare'].includes(p.kind))).toBe(true);
  expect(payload.phases.some((p) => p.kind === 'hypercare')).toBe(true);
});
```

- [ ] **Step 2: Implement**

`PhasesTable.tsx`:
- `const PHASE_KINDS: { value: PhaseKind; label: string }[] = [{ value: 'test', label: 'Test' }, { value: 'hypercare', label: 'Hyper-care' }];`
- dialog state `const [kind, setKind] = useState<PhaseKind>('test');`, set from `phase.kind` in `openEdit`, reset in the add path.
- a `<TextField select label="Kind">` beside Status, mapping `PHASE_KINDS`.
- include `kind` in both the create and update payloads.
- column `{ field: 'kind', headerName: 'Kind', width: 110, valueFormatter: (v) => (v === 'hypercare' ? 'Hyper-care' : 'Test') }` after `name`.

`PhaseGanttEditor.tsx`:
- `const HYPERCARE_COLOR = '#ce93d8';`; at `:93` `const color = phase.kind === 'hypercare' ? HYPERCARE_COLOR : (STATUS_COLOR[phase.status] ?? '#90caf9');`
- a legend row above the bars: one small swatch per status colour plus "Hyper-care" — `<Box sx={{ display: 'flex', gap: 2, mb: 1 }}>` of `<Box sx={{ width: 12, height: 12, bgcolor }} /> <Typography variant="caption">label</Typography>` pairs.

`ReleaseTemplateForm.tsx`:
- `emptyPhase()` returns `kind: 'test'`.
- in the phase row, a `<TextField select label="Kind" value={phase.kind ?? 'test'} onChange={(e) => updatePhase(idx, 'kind', e.target.value)}>` with the two options, and when `kind === 'hypercare'` a `<Typography variant="caption">after target date</Typography>` beside the duration field.

- [ ] **Step 3: Run and commit**

Run: `cd frontend && npx vitest run src/components/releases/__tests__/phasesTableKind.test.tsx src/pages/admin/release-templates && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/components/releases/PhasesTable.tsx frontend/src/components/releases/PhaseGanttEditor.tsx frontend/src/pages/admin/release-templates/ReleaseTemplateForm.tsx frontend/src/components/releases/__tests__/phasesTableKind.test.tsx frontend/src/pages/admin/release-templates/__tests__/ReleaseTemplateForm.test.tsx
git commit -m "feat(c6): phase kind in the phases table, Gantt legend and release template form"
```

---

### Task 12: The Closeout tab

**Files:**
- Create: `frontend/src/components/releases/CloseoutTab.tsx`
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx:1-15, 69-82, 224-236`
- Test: `frontend/src/components/releases/__tests__/closeoutTab.test.tsx`, `frontend/src/pages/releases/__tests__/releaseDetailTabs.test.tsx` (append one case)

**Interfaces:**
- Consumes: `fetchCloseout`, `declareStable`, `withdrawStable`, `confirmHandover`, `withdrawHandover` from `closeoutSlice`; `updateRelease` from `releaseSlice`; `fetchUserGroups` + `state.userGroup.groups` from `userGroupSlice`; `CloseoutRead` from `types/closeout`.
- Produces: `export default function CloseoutTab({ releaseId }: { releaseId: number })`; tab key `'closeout'`, label `Closeout`.

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/components/releases/__tests__/closeoutTab.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import { AxiosError } from 'axios';
import closeoutReducer from '../../../store/closeoutSlice';
import releaseReducer from '../../../store/releaseSlice';
import userGroupReducer from '../../../store/userGroupSlice';
import { closeoutService } from '../../../services/closeoutService';
import { userGroupService } from '../../../services/userGroupService';
import type { CloseoutRead } from '../../../types/closeout';
import CloseoutTab from '../CloseoutTab';

vi.mock('../../../services/closeoutService', () => ({
  closeoutService: { get: vi.fn(), declareStable: vi.fn(), withdrawStable: vi.fn(),
                     confirmHandover: vi.fn(), withdrawHandover: vi.fn() },
}));
vi.mock('../../../services/userGroupService', () => ({
  userGroupService: { listGroups: vi.fn().mockResolvedValue({ rows: [{ id: 3, name: 'Platform Ops' }], total: 1 }) },
}));
vi.mock('../../../services/releaseService', () => ({
  releaseService: { update: vi.fn().mockResolvedValue({}) },
}));

const base: CloseoutRead = {
  hypercare: { state: 'active', phase: { id: 1, name: 'Hyper-care', start_date: '2026-09-01T00:00:00Z', end_date: '2026-09-15T00:00:00Z' },
               declared_stable_at: null, declared_stable_by_username: null },
  handover: { operations_group_id: null, operations_group_name: null, confirmed_at: null, confirmed_by_username: null },
  pir: { exists: true, status: 'draft', completed_at: null },
  incidents: { window_start: '2026-09-01T00:00:00Z', window_end: '2026-09-10T00:00:00Z',
               by_severity: { P1: 1, P2: 0, P3: 2, P4: 0 }, total: 3,
               items: [{ id: 9, title: 'Checkout 500s', severity: 'P1', status: 'new', detected_at: '2026-09-03T00:00:00Z' }] },
  close_targets: [
    { state_key: 'completed', label: 'Completed', requires_pir_complete: true, requires_handover_confirmed: true,
      unmet: ['the post-implementation review is not complete', 'ops handover is not confirmed'], can_close: false },
    { state_key: 'backed_out', label: 'Backed Out', requires_pir_complete: false, requires_handover_confirmed: false, unmet: [], can_close: true },
  ],
};

function renderTab(role = 'Admin') {
  const store = configureStore({ reducer: {
    closeout: closeoutReducer, release: releaseReducer, userGroup: userGroupReducer,
    auth: (state = { user: { id: 1, role, is_master_admin: false } }) => state,
  }});
  return render(<Provider store={store}><MemoryRouter><CloseoutTab releaseId={7} /></MemoryRouter></Provider>);
}

describe('CloseoutTab', () => {
  beforeEach(() => { vi.mocked(closeoutService.get).mockResolvedValue(base); });

  it('renders the four cards and the requirement ticks and crosses', async () => {
    renderTab();
    expect(await screen.findByText(/active/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Checkout 500s' })).toHaveAttribute('href', '/incidents/9');
    const completed = screen.getByTestId('close-target-completed');
    expect(within(completed).getByText(/review is not complete/)).toBeInTheDocument();
    expect(within(completed).getAllByLabelText('Not met')).toHaveLength(2);
    const backedOut = screen.getByTestId('close-target-backed_out');
    expect(within(backedOut).getByText(/no requirements/i)).toBeInTheDocument();
  });

  it('declares stable with a note and re-reads', async () => {
    vi.mocked(closeoutService.declareStable).mockResolvedValue({} as never);
    vi.mocked(closeoutService.get)
      .mockResolvedValueOnce(base)
      .mockResolvedValueOnce({ ...base, hypercare: { ...base.hypercare, state: 'stable',
        declared_stable_at: '2026-09-10T09:00:00Z', declared_stable_by_username: 'testadmin' } });
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /declare stable/i }));
    await userEvent.type(screen.getByLabelText(/note/i), 'no P1 in 14 days');
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(closeoutService.declareStable).toHaveBeenCalledWith(7, 'no P1 in 14 days');
    expect(await screen.findByText(/declared stable by testadmin/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /withdraw/i })).toBeInTheDocument();
  });

  it('shows the server reason when a write is refused', async () => {
    const err = new AxiosError('Request failed with status code 409');
    (err as unknown as { response: unknown }).response = { status: 409, data: { detail: 'This release is already declared stable; withdraw the declaration first' } };
    vi.mocked(closeoutService.declareStable).mockRejectedValue(err);
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /declare stable/i }));
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(await screen.findByText(/already declared stable/)).toBeInTheDocument();
    expect(screen.queryByText(/status code 409/)).not.toBeInTheDocument();
  });

  it('disables Confirm handover until a group is set, and a Developer sees no write controls', async () => {
    renderTab();
    const btn = await screen.findByRole('button', { name: /confirm handover/i });
    expect(btn).toBeDisabled();
    renderTab('Developer');
    await waitFor(() => expect(screen.getAllByText(/hyper-care/i).length).toBeGreaterThan(0));
    expect(screen.queryByRole('button', { name: /declare stable/i })).not.toBeInTheDocument();
  });

  it('hides the incidents card when there is no window, and explains an empty target list', async () => {
    vi.mocked(closeoutService.get).mockResolvedValue({ ...base,
      hypercare: { ...base.hypercare, state: 'none', phase: null }, close_targets: [] });
    renderTab();
    expect(await screen.findByText(/no hyper-care phase/i)).toBeInTheDocument();
    expect(screen.queryByText(/incidents in the window/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no state flagged as closed/i)).toBeInTheDocument();
  });
});
```

Append to `releaseDetailTabs.test.tsx`:
```tsx
it('selects the Closeout tab from ?tab=closeout', async () => {
  renderAt('?tab=closeout');
  expect(await screen.findByRole('tab', { name: 'Closeout' })).toHaveAttribute('aria-selected', 'true');
});
```

- [ ] **Step 2: Component**

```tsx
// frontend/src/components/releases/CloseoutTab.tsx
/**
 * CloseoutTab — Phase 9 C6. Four cards in lifecycle order: hyper-care,
 * incidents in the window, ops handover, closing.
 *
 * THE SERVER DECIDES; THIS TAB REPORTS. `close_targets` is computed by the
 * same function that raises the transition's 422, so a tick here and a
 * refusal on the Main tab cannot disagree. Nothing here touches
 * TransitionControls — see ReadinessBanner's header for the standing rule.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, InputLabel, Link, List, ListItem, ListItemText, MenuItem, Paper,
  Select, Stack, TextField, Tooltip, Typography,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import type { AppDispatch, RootState } from '../../store';
import { fetchCloseout, declareStable, withdrawStable, confirmHandover, withdrawHandover } from '../../store/closeoutSlice';
import { updateRelease } from '../../store/releaseSlice';
import { fetchUserGroups } from '../../store/userGroupSlice';
import type { HypercareState } from '../../types/closeout';

interface Props { releaseId: number }

const STATE_LABEL: Record<HypercareState, string> = {
  none: 'No hyper-care phase', planned: 'Planned', active: 'Active', overdue: 'Overdue', stable: 'Stable',
};
const STATE_COLOR: Record<HypercareState, 'default' | 'info' | 'success' | 'warning'> = {
  none: 'default', planned: 'info', active: 'info', overdue: 'warning', stable: 'success',
};

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—');
const fmtDateTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—');

type Pending = 'declare' | 'withdraw-stable' | 'confirm' | 'withdraw-handover' | null;

export default function CloseoutTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const user = useSelector((s: RootState) => s.auth.user);
  const data = useSelector((s: RootState) => s.closeout.byRelease[releaseId]);
  const loadError = useSelector((s: RootState) => s.closeout.error);
  const groups = useSelector((s: RootState) => s.userGroup.groups);
  const canWrite = user?.role === 'Admin' || user?.role === 'Release Manager' || user?.is_master_admin === true;

  const [pending, setPending] = useState<Pending>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    dispatch(fetchCloseout(releaseId));
    dispatch(fetchUserGroups({}));
  }, [dispatch, releaseId]);

  const run = async () => {
    if (!pending) return;
    setSubmitting(true);
    setError(null);
    const thunk = { declare: declareStable, 'withdraw-stable': withdrawStable,
                    confirm: confirmHandover, 'withdraw-handover': withdrawHandover }[pending];
    const result = await dispatch(thunk({ releaseId, note: note.trim() || undefined }));
    setSubmitting(false);
    if (thunk.rejected.match(result)) {
      setError(result.payload ?? 'Request failed');
      return;
    }
    setPending(null);
    setNote('');
  };

  const setGroup = async (value: number | '') => {
    setError(null);
    const result = await dispatch(updateRelease({ id: releaseId, data: { operations_group_id: value === '' ? null : value } }));
    if (updateRelease.rejected.match(result)) {
      setError((result as { payload?: string }).payload ?? 'Failed to set the operations group');
      return;
    }
    dispatch(fetchCloseout(releaseId));
  };

  if (loadError && !data) return <Alert severity="error">{loadError}</Alert>;
  if (!data) return <Typography variant="body2">Loading…</Typography>;

  const { hypercare, handover, pir, incidents, close_targets } = data;
  const groupValue: number | '' = handover.operations_group_id ?? '';
  const groupIsArchived = groupValue !== '' && !groups.some((g) => g.id === groupValue);

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>Hyper-care</Typography>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
          <Chip label={STATE_LABEL[hypercare.state]} color={STATE_COLOR[hypercare.state]} size="small" />
          {hypercare.phase && (
            <Typography variant="body2">{hypercare.phase.name}: {fmt(hypercare.phase.start_date)} – {fmt(hypercare.phase.end_date)}</Typography>
          )}
        </Stack>
        {!hypercare.phase && hypercare.state !== 'stable' && (
          <Typography variant="body2" color="text.secondary">
            No hyper-care phase on this release. Add one, with kind Hyper-care, under Gates &amp; Test Phases.
          </Typography>
        )}
        {hypercare.declared_stable_at ? (
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2">Declared stable by {hypercare.declared_stable_by_username ?? 'unknown'} on {fmtDateTime(hypercare.declared_stable_at)}</Typography>
            {canWrite && <Button size="small" onClick={() => setPending('withdraw-stable')}>Withdraw</Button>}
          </Stack>
        ) : (
          canWrite && <Button variant="contained" size="small" onClick={() => setPending('declare')}>Declare stable</Button>
        )}
      </Paper>

      {hypercare.state !== 'none' && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>Incidents in the window</Typography>
          <Typography variant="caption" color="text.secondary">
            {fmt(incidents.window_start)} – {fmt(incidents.window_end)} · caused by this release
          </Typography>
          <Stack direction="row" spacing={1} sx={{ my: 1 }}>
            {Object.entries(incidents.by_severity).map(([sev, n]) => (
              <Chip key={sev} label={`${sev}: ${n}`} size="small" color={n > 0 && (sev === 'P1' || sev === 'P2') ? 'error' : 'default'} />
            ))}
          </Stack>
          {incidents.total === 0 ? (
            <Typography variant="body2" color="text.secondary">No incidents in the window.</Typography>
          ) : (
            <List dense>
              {incidents.items.map((i) => (
                <ListItem key={i.id} disableGutters>
                  <ListItemText
                    primary={<Link component={RouterLink} to={`/incidents/${i.id}`}>{i.title}</Link>}
                    secondary={`${i.severity} · ${i.status} · ${fmtDateTime(i.detected_at)}`}
                  />
                </ListItem>
              ))}
              {incidents.total > incidents.items.length && (
                <Typography variant="caption">Showing {incidents.items.length} of {incidents.total}.</Typography>
              )}
            </List>
          )}
        </Paper>
      )}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>Ops handover</Typography>
        <FormControl size="small" sx={{ minWidth: 260, mb: 1 }} disabled={!canWrite}>
          <InputLabel id="closeout-ops-group-label">Operations group</InputLabel>
          <Select labelId="closeout-ops-group-label" label="Operations group" value={groupValue}
                  onChange={(e) => setGroup(e.target.value as number | '')}>
            <MenuItem value="">No group</MenuItem>
            {groupIsArchived && (
              <MenuItem value={groupValue}>{handover.operations_group_name ?? 'Archived group'} (deleted)</MenuItem>
            )}
            {groups.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
          </Select>
        </FormControl>
        {handover.confirmed_at ? (
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2">Handover confirmed by {handover.confirmed_by_username ?? 'unknown'} on {fmtDateTime(handover.confirmed_at)}</Typography>
            {canWrite && <Button size="small" onClick={() => setPending('withdraw-handover')}>Withdraw</Button>}
          </Stack>
        ) : (
          canWrite && (
            <Tooltip title={handover.operations_group_id ? '' : 'Set the operations group first'}>
              <span>
                <Button variant="contained" size="small" disabled={!handover.operations_group_id}
                        onClick={() => setPending('confirm')}>Confirm handover</Button>
              </span>
            </Tooltip>
          )
        )}
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>Closing</Typography>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Post-implementation review: {pir.exists ? pir.status : 'none'}
        </Typography>
        {close_targets.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            This release's lifecycle has no state flagged as closed.
            {user?.role === 'Admin' && <> Flag one in the <Link component={RouterLink} to="/admin/lifecycles">lifecycle editor</Link>.</>}
          </Typography>
        ) : (
          close_targets.map((t) => (
            <Box key={t.state_key} data-testid={`close-target-${t.state_key}`} sx={{ mb: 1 }}>
              <Typography variant="subtitle2">{t.label}</Typography>
              {!t.requires_pir_complete && !t.requires_handover_confirmed ? (
                <Typography variant="body2" color="text.secondary">No requirements.</Typography>
              ) : (
                <Stack spacing={0.5}>
                  {t.requires_pir_complete && (
                    <Requirement met={!t.unmet.includes('the post-implementation review is not complete')}
                                 label="Post-implementation review complete" />
                  )}
                  {t.requires_handover_confirmed && (
                    <Requirement met={!t.unmet.includes('ops handover is not confirmed')}
                                 label="Ops handover confirmed" />
                  )}
                </Stack>
              )}
            </Box>
          ))
        )}
      </Paper>

      <Dialog open={pending !== null} onClose={() => !submitting && setPending(null)} fullWidth maxWidth="sm">
        <DialogTitle>
          {{ declare: 'Declare stable', 'withdraw-stable': 'Withdraw stability declaration',
             confirm: 'Confirm ops handover', 'withdraw-handover': 'Withdraw handover confirmation' }[pending ?? 'declare']}
        </DialogTitle>
        <DialogContent>
          <TextField label="Note (optional)" fullWidth multiline rows={3} value={note}
                     onChange={(e) => setNote(e.target.value)} sx={{ mt: 1 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPending(null)} disabled={submitting}>Cancel</Button>
          <Button variant="contained" onClick={run} disabled={submitting}>Confirm</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function Requirement({ met, label }: { met: boolean; label: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      {met ? <CheckCircleIcon color="success" fontSize="small" aria-label="Met" />
           : <CancelIcon color="error" fontSize="small" aria-label="Not met" />}
      <Typography variant="body2">{label}{met ? '' : ' — ' + (label.startsWith('Post') ? 'the post-implementation review is not complete' : 'ops handover is not confirmed')}</Typography>
    </Stack>
  );
}
```

Check the admin lifecycle editor's route (grep `LifecycleTemplatesPanel` in `frontend/src/App.tsx` or the admin routes) and use that path instead of `/admin/lifecycles` if it differs.

- [ ] **Step 3: Register the tab**

`ReleaseDetail.tsx`: add `closeout: Closeout` to the header comment's tab list (after `go-no-go`), `{ key: 'closeout', label: 'Closeout' }` to `RELEASE_TABS`, `import CloseoutTab from '../../components/releases/CloseoutTab';`, and `{activeTab === 'closeout' && <CloseoutTab releaseId={releaseId} />}`.

- [ ] **Step 4: Run and commit**

Run: `cd frontend && npx vitest run src/components/releases/__tests__/closeoutTab.test.tsx src/pages/releases/__tests__ && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/components/releases/CloseoutTab.tsx frontend/src/components/releases/__tests__/closeoutTab.test.tsx frontend/src/pages/releases/ReleaseDetail.tsx frontend/src/pages/releases/__tests__/releaseDetailTabs.test.tsx
git commit -m "feat(c6): Closeout tab on the project release page"
```

---

### Task 13: My work — the Hyper-care decisions card

**Files:**
- Modify: `frontend/src/pages/MyWork.tsx:66-149`
- Test: `frontend/src/pages/__tests__/myWork.test.tsx` (append)

- [ ] **Step 1: Failing test** (uses the file's `renderWithStore(ui, queues)` helper and its `allFive` fixture — rename that to `allSix` and add the key)

```tsx
it('renders the Hyper-care decisions card with its overdue count and view-all link', async () => {
  renderWithStore(<MyWork />, { ...allSix, hypercare: { count: 2, overdue: 1, failed: false, items: [
    { id: 7, title: 'Release 3.2', subtitle: 'Hyper-care window ends', url: '/releases/7?tab=closeout', due: '2026-09-08T00:00:00Z' },
  ] } });
  expect(await screen.findByRole('heading', { name: /hyper-care decisions/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Release 3.2' })).toHaveAttribute('href', '/releases/7?tab=closeout');
  expect(screen.getByText(/1 overdue/i)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /view all releases/i })).toHaveAttribute('href', '/releases');
});
```

- [ ] **Step 2: Implement** — append to `QUEUES`:
```ts
  {
    key: 'hypercare',
    title: 'Hyper-care decisions',
    // SUPERSET: the releases list has no hyper-care filter (the state is
    // computed per response and deliberately not filterable — spec §6.5), so
    // "view all" lands on the unfiltered list. Each row links straight to its
    // release's Closeout tab, which is where the decision is taken.
    viewAllHref: '/releases',
    viewAllLabel: 'releases',
    viewAllCaption: 'All releases; the list has no hyper-care filter',
  },
```
Confirm the overdue rendering: `QueueCard` already renders `queue.overdue` for the PIR actions card; if it does so only when the prop is present, nothing else is needed.

- [ ] **Step 3: Run and commit**

Run: `cd frontend && npx vitest run src/pages/__tests__/myWork.test.tsx && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/pages/MyWork.tsx frontend/src/pages/__tests__/myWork.test.tsx
git commit -m "feat(c6): Hyper-care decisions card on My work"
```

---

### Task 14: Documentation

**Files:**
- Modify: `docs/admin-guide.md` (near `### Status lifecycle` at 485, `## 9. Release templates` at 977), `docs/user-guide.md` (after `### Rollback plans and rehearsals` at 861; `### My work` at 67), `docs/phases/phase-9.md` (row 26 and a new `## C6` section after C4), `docs/plan.md:152-170`, `docs/gap-analysis.md:138-143`, `CLAUDE.md` (a C6 block beside C3's; the `/me/work` queue count), `docs/pagination.md` (the permanently-unsortable list gains `hypercare_state`, "computed per response; no list filter").

- [ ] **Step 1: Admin guide** — under the lifecycle section add "Closed states and the close gate": what *Closed*, *Marks deployed*, *Require PIR complete* and *Require ops handover confirmed* do; that both gates default off; that existing templates were flagged by the migration on `completed`, `completed_with_issues`, `backed_out` **by key**, and a renamed key needs the flag ticked by hand; how to add a `deployed` state to an existing template (state + two transitions); the `is_failed` note ("any template saved through this editor between July and September 2026 lost *Counts as failure* on its failed states; re-tick it — the change-failure rate undercounted meanwhile"); and the backup-restore note about the four event types (`seed_release_defaults_for_tenant` is idempotent).
- [ ] **Step 2: User guide** — "Hyper-care and closeout": the Closeout tab's four cards, who may declare/confirm, that a refused close names what is missing, that a hyper-care phase comes from the template or is added by hand with kind Hyper-care, and the My work card.
- [ ] **Step 3: phase-9.md** — row 26 → `✅ Complete`, header line 3-5 updated, and a `## C6 — Hyper-care and closeout — ✅ COMPLETE <date>` section in the C2/C3/C4 shape: what shipped, "What C6 established, and what will bite if forgotten" (the one-refusal rule and its guard; `marks_deployed` replacing the name set; `is_failed` drop fixed; day-boundary rule; usernames not tenant-qualified; close_targets and the 422 share one wording; one hyper-care phase per release; project-only).
- [ ] **Step 4: plan.md, gap-analysis.md, CLAUDE.md, pagination.md** — flip the three A8 rows to ✅ with "Phase 9 C6"; plan.md's Phase 9 paragraph lists C6 complete; CLAUDE.md gains a C6 block modelled on C3's (short) and corrects "five queues" to six where `/me/work` is described; pagination.md's unsortable set gains the entry.
- [ ] **Step 5: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs(c6): admin/user guides, phase-9, plan, gap analysis, CLAUDE.md for hyper-care and closeout"
```

---

### Task 15: Whole-branch verification, browser pass, PR

- [ ] **Step 1: All three suites**

```bash
cd backend && uv run pytest -q
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q   # alone; no other PostgreSQL run in flight
cd frontend && npx vitest run && npx tsc --noEmit && npm run lint && npm run build
```
Expected: all green. If the PostgreSQL leg reports mass `UndefinedTable`, recreate `envmgr_test` and re-run before believing it.

- [ ] **Step 2: Mutation checks, recorded in the PR body**
  - Comment out `assert_may_close` in `transition_release` → `test_c6_refuses_only_at_close.py::test_a_closed_state_requiring_a_pir_refuses_a_draft_pir` fails. Restore.
  - Remove `Incident.tenant_id` from the window query (in `incident_service.list_incidents` it is structural; instead pass `release.tenant_id + 1`) → `test_another_tenants_incident_is_never_counted` fails. Restore.
  - Drop `is_failed` from `LifecycleState` → `test_all_five_flags_survive_create_read_update_and_copy` fails. Restore.
  - `git diff` clean afterwards.

- [ ] **Step 3: Browser pass** (dev server restarted first; the dev tenant's templates went through the migration, not the seeder)
  1. Admin → lifecycle editor → Major: confirm `completed` shows Closed ticked and Marks deployed ticked (migration data step), no `deployed` state (not inserted). Add a `deployed` state and the two transitions; save; reopen; flags intact.
  2. Admin → release templates → add a phase with kind Hyper-care, 14 days. Create a release from it with a target date next week: Gantt shows the hyper-care bar starting on the target date, distinct colour, legend present.
  3. Release → Closeout tab: state Planned. Edit the phase's dates to straddle today: Active. Declare stable with a note: chip Stable, name and time shown; event visible in the release event log; Withdraw; back to Active.
  4. Set an operations group; Confirm handover; Withdraw.
  5. Lifecycle editor: tick Require PIR complete on `completed`. Release Main tab → transition to Completed: snackbar shows "Cannot close this release: the post-implementation review is not complete." Closeout tab shows the cross with the same wording. Create the PIR, mark complete; transition succeeds; `actual_date` set.
  6. Edit the hyper-care phase's end date to yesterday on another release: My work shows the Hyper-care decisions card with 1 overdue; its row links to the Closeout tab.
  7. A Developer login: Closeout tab renders read-only, no buttons.
  8. Vary the data: a template with two closed states (two rows in Closing); a hyper-care phase with no dates (Active from creation); an enterprise release (no Closeout tab).
  Record every defect found and fixed in the PR body — this is the pass that finds what the suites cannot.

- [ ] **Step 4: PR**

```bash
git push -u github feature/phase9-c6-hypercare-closeout
gh pr create --title "feat: Phase 9 C6 — hyper-care and closeout" --body-file <(cat <<'EOF'
Spec: docs/superpowers/specs/2026-09-09-hypercare-closeout-design.md
Plan: docs/superpowers/plans/2026-09-09-hypercare-closeout.md

## What
- Lifecycle state flags `is_closed`, `marks_deployed`, `requires_pir_complete`, `requires_handover_confirmed` (declared; `is_failed` no longer dropped on save)
- `deployed` state in new tenants' default project templates; existing templates flagged by key in migration `closeout`
- `test_phase.kind` — one hyper-care phase per release, laid forward from target_date
- Release: operations group + declared-stable and handover-confirmed audit pairs; four routes; four release events; `ReleaseDeclaredStable` outbox event
- `GET /releases/{id}/closeout`; the first deliberate refusal in Phase 9 in `release_closeout_service.assert_may_close`, guarded by `tests/test_c6_refuses_only_at_close.py`
- `/me/work` sixth queue; Closeout tab; lifecycle editor, phases table, Gantt, template form, My work card

## Verification
- SQLite: N passed · PostgreSQL: N passed · frontend: N passed; tsc, lint, build green
- Mutations: <the three from Task 15 step 2, each with the failing test name>
- Browser pass: <defects found and fixed>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_018XrYDmFZBtbTMoigR2hzZp
EOF
)
```

---

## Self-review against the spec

- §3.1 flags, rules, defaults → Task 1; `marks_deployed` stamping → Task 2. §3.2 columns, carve-out, usernames → Tasks 3, 6. §3.3 kind, one-per-release, instantiation → Task 4. §3.4 event types → Tasks 1, 3. §3.5 data step, downgrade → Task 3. §4.1–4.3 gate + guards → Task 5. §4.4 state → Task 5. §4.5 audit routes → Task 6. §4.6 incidents → Task 7. §5 routes and `/me/work` → Tasks 6, 7, 8. §6 frontend → Tasks 9–13. §7 tests → each task; browser pass → Task 15. §8–10 → Task 14 docs.
- Downgrade strips four flags, not five: `is_failed` predates C6 (noted in Task 3).
- Names used consistently: `release_closeout_service.{live_hypercare_phase, assert_hypercare_slot_free, hypercare_state, state_for_key, unmet_requirements, assert_may_close, usernames_for, declare_stable, withdraw_stable, confirm_handover, withdraw_handover, incidents_in_window, build_closeout, hypercare_queue, hypercare_overdue_total}`; constants `HYPERCARE`, `PHASE_KINDS`, `HYPERCARE_STATES`, `PIR_INCOMPLETE`, `HANDOVER_UNCONFIRMED`, `EVENT_*`, `INCIDENT_ITEM_CAP`, `HORIZON_DAYS`. Frontend: `closeoutService.{get, declareStable, withdrawStable, confirmHandover, withdrawHandover}`, thunks of the same names plus `fetchCloseout`, tab key `closeout`, queue key `hypercare`.
- Where a step says "check X and adjust", the assertion that follows is the contract and the check is a fact the implementer must read from the code — the plan names the file and line to read.
