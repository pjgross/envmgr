# Phase 9 C6 — Hyper-care and closeout

> Status: design approved 2026-09-09.
>
> Sixth cluster of [Phase 9](../../phases/phase-9.md) to be built (after C2,
> C4, C3 and the PIR findings/actions work that is its retro half). Answers
> the last line of [requirements.md §2.11](../../requirements.md) — "explicit
> hyper-care window; 'declared stable' decision to move Operate → Improve;
> closeout confirms ops-ownership transfer and records outcome" — and §2.5's
> "PIR completion can be configured as a gate before a release is formally
> closed", which the PIR work and C3 each deferred here by name.

## 1. What §2.11 asks for, and what the code has

Four things: a hyper-care window sized to the release, a decision that the
release is stable, a closeout that confirms ops ownership has moved and
records the outcome, and a retrospective producing owned, dated actions. The
last already exists (PIR findings and actions, 2026-09-02). The other three
have no representation anywhere in the schema.

Two facts about the code shaped every decision below.

**There is no "closed" state.** A project release's lifecycle is a
tenant-configurable template (`LifecycleTemplate`, state machine in a JSON
`definition`, four seeded per tenant by `release_defaults.py`). Its terminal
states are `completed`, `completed_with_issues`, `backed_out`, `rejected` and
`cancelled`. Entering `completed` or `completed_with_issues` stamps
`actual_date` — a hardcoded name set, `_DEPLOYED_TERMINAL_STATES` in
`release_service.py`. So today the moment a release is deployed **is** the
moment it terminates. Hyper-care happens after deployment, so a close gate on
the existing terminal transition would refuse go-live on a review that is
written after go-live.

**The lifecycle editor silently drops `is_failed`.** `LifecycleState` in
`schemas/booking_lifecycle.py` declares `is_initial`, `is_terminal` and
`is_admission_lockdown`; `is_failed` is read by the DORA change-failure rate
but is not on the schema, and both create and update store
`definition.model_dump()`. Every save through the admin editor strips the flag
from every state. Same class as the `required_fields` drop already recorded
in CLAUDE.md. C6 adds flags to that same schema, so it fixes this one too.

## 2. Decisions taken in design

Each was put as a question and answered; the answer is the rule.

1. **"Formally closed" is a per-state flag on the tenant's own lifecycle
   template**, not a fixed state name and not a separate record. A tenant
   marks whichever of its states mean closed — e.g. *Closed*, *Closed with
   Issues* and *Rolled back* can all be closed states.
2. **The hyper-care window is a phase**, flagged as such: `TestPhase.kind`.
   Phases already carry dates, sit on the release Gantt and are seeded from
   the release template, so "sized to the release" is a template default
   plus an editable pair of dates.
3. **"Declared stable" is a flag with an audit trail** — date/time and who —
   not a lifecycle state.
4. **Ops ownership is a group on the release plus a confirmation flag** with
   the same audit shape. The group is a `UserGroup`, the primitive
   environments already use (`environment.operations_group_id`).
5. **"PIR complete" means the PIR's own status is `complete`.** Open actions
   never hold a release: they live on a tenant-wide worklist and outlive
   releases by design.
6. **The close gates are configured per closed state on the template**, not
   on a tenant-wide policy row. An Emergency template or a *Rolled back*
   state can differ from *Closed*. Default off; nothing to seed.
7. **Project releases only.** Enterprise releases have no PIR tab, no
   readiness banner and no Go/No-Go; the new flags are refused on enterprise
   templates the way `is_admission_lockdown` is refused on project ones.
8. **Approach A for the deploy/close split** (see §3.1): a `marks_deployed`
   flag replaces the by-name set, new tenants' defaults gain a non-terminal
   `deployed` state, existing tenants' templates receive flags only.

## 3. Data model

Migration `closeout`, chained off `gonogo`. Additive on the schema: five
nullable columns on `release` and one NOT NULL column with a server default
on `test_phase`. One data
step, on template JSON, described in §3.5.

### 3.1 Lifecycle state flags

All live in the template's `definition.states[]` entries and are declared on
`LifecycleState` so they survive `model_dump()`.

| flag | meaning | rule |
|---|---|---|
| `is_failed` | counts as a failed delivery (DORA) | already read; now declared |
| `marks_deployed` | entering this state stamps `actual_date`, once | replaces `_DEPLOYED_TERMINAL_STATES` |
| `is_closed` | the release is formally closed in this state | requires `is_terminal` |
| `requires_pir_complete` | gate: the release's PIR status must be `complete` | requires `is_closed` |
| `requires_handover_confirmed` | gate: `handover_confirmed_at` must be set | requires `is_closed` |

Validation, in `validate_definition_for_entity`, each a 422 naming the state:

- `is_closed` without `is_terminal` is refused.
- `requires_pir_complete` or `requires_handover_confirmed` without `is_closed`
  is refused.
- On an enterprise release template (`applies_to_kind == "enterprise"`) all
  four new flags are refused. Enterprise releases' `deployed` state is
  terminal and never stamps `actual_date` today; that stays as it is.
- `is_failed` keeps its current meaning and no new rule.

`transition_release` stamps `actual_date` when the target state has
`marks_deployed` and `actual_date` is null. The by-name set is deleted. A
tenant that renames or inserts states keeps a correct deploy date.

**Defaults for new tenants** (`release_defaults.py`, Major, Minor and
Emergency; Enterprise untouched):

- A new non-terminal state `deployed`, label "Deployed (hyper-care)", with
  `marks_deployed`, placed after `ready_for_release`.
- Transitions `ready_for_release → deployed` ("Deploy") and `deployed →
  completed | completed_with_issues | backed_out`, Admin and ReleaseManager.
  The existing direct transitions from `ready_for_release` to those three
  **stay**, so a release with no hyper-care closes in one step and nothing
  that exercises today's paths breaks.
- `completed`: `marks_deployed`, `is_closed`.
  `completed_with_issues`: `marks_deployed`, `is_closed`, `is_failed`.
  `backed_out`: `is_closed`, `is_failed` (it does not stamp `actual_date`
  today and still does not). `rejected`, `cancelled`: terminal, not closed.
- `field_permissions["deployed"]` is an empty entry like the other terminals.

### 3.2 `release` — five nullable columns

| column | type | notes |
|---|---|---|
| `operations_group_id` | FK `user_group.id`, nullable, indexed | the team that owns the release in operation |
| `declared_stable_at` | timestamptz nullable | |
| `declared_stable_by` | FK `user.id`, nullable | |
| `handover_confirmed_at` | timestamptz nullable | |
| `handover_confirmed_by` | FK `user.id`, nullable | |

`operations_group_id` follows the archived-value carve-out `owning_project_id`
already carries: a new assignment is validated through
`user_group_service.get_group` (live, this tenant); re-sending the stored
value is accepted even if the group has since been soft-deleted, because
`ReleaseForm.tsx` sends a fixed whitelist payload on every save.

The two `_by` columns are rendered as usernames through a lookup that is
**not tenant-qualified** — under master-admin impersonation the actor can
legitimately sit outside the release's tenant. Same rule as A3's
`acknowledged_by_username`, A4's `usernames_for`, B5's and C2's equivalents.

### 3.3 `test_phase.kind`

`String(20)`, NOT NULL, server default `'test'`. Values `test` and
`hypercare`, validated on the schema. `ReleaseTemplatePhase` (the JSON
skeleton on `release_template.phases`) gains the same `kind`, default `test`.

**At most one live hyper-care phase per release**, enforced in
`test_phase` create and update (a 422 naming the existing phase), never by a
partial unique index, which is inert on SQLite. A soft-deleted hyper-care
phase does not count. Changing a test phase's kind to `hypercare` obeys the
same rule.

**Instantiation** (`release_template_service.instantiate`): test phases are
laid backwards so the last ends on `target_date`, exactly as today; hyper-care
phases are laid **forwards** from `target_date`, in template order, each
starting where the previous ended. A hyper-care phase therefore begins on the
planned deploy day.

### 3.4 Release event types

Four system event types seeded per tenant beside the existing release event
types, idempotently, in `release_defaults` and in the migration's data step
(its own literal copy, the `gate_type_defaults` rule): *Declared stable*,
*Stability declaration withdrawn*, *Ops handover confirmed*, *Ops handover
withdrawn*. `record_auto_event` returns None when a type is missing, so a
tenant restored from a pre-C6 backup silently loses the audit line until the
seeder is run; the admin guide says so.

### 3.5 The migration's data step

Walks every `lifecycle_template` with `entity_type = 'release'` and
`applies_to_kind != 'enterprise'` and, matching **by state key**:

- `completed`, `completed_with_issues` → `marks_deployed: true`,
  `is_closed: true`
- `backed_out` → `is_closed: true`

This reproduces, as flags, exactly the behaviour those tenants have today:
the two states that stamped `actual_date` still do, and the three deployed
terminals read as closed. **No state and no transition is inserted** into an
existing template — a tenant may have renamed or rewired it, and a migration
cannot know which transition should lead into a new state. A tenant that has
already renamed those keys gets no flags; its closeout tab reports that the
template has no closed state and links an Admin to the lifecycle editor.

Downgrade drops the six columns and strips the five flags from every
template definition.

### 3.6 Computed, never stored

The one C3 exception aside, this codebase computes state on read, and C6
does too:

- **Hyper-care state** — `none` | `planned` | `active` | `overdue` | `stable`.
- **Incidents in the window.**
- **Whether each closed state is currently enterable** and why not.

## 4. The gate, and the rules that will look wrong to a later reader

### 4.1 One function refuses, in one place, default off

`release_closeout_service.assert_may_close(db, release, target_state)` is
called from `transition_release` after `validate_transition` passes and
before `release.status` is written. It returns at once unless the target
state has `is_closed`. If it does, it evaluates each `requires_*` flag and
raises **one** 422 naming everything unmet, the B5 teardown shape:

> Cannot close this release: the post-implementation review is not complete;
> ops handover is not confirmed.

"PIR complete" is `pir.status == "complete"` on the release's PIR; **no PIR at
all is incomplete** when the flag is on.

**This is the first deliberate refusal in Phase 9**, the ninth sub-project
running whose central promise is a named test — but this time the promise is
"refuses exactly here and nowhere else":
`backend/tests/test_c6_refuses_only_at_close.py`. Readiness, `can-deploy`,
bookings, incidents, deployments and every non-closed transition are
unchanged with the flag on.

### 4.2 Why the gate is not folded into readiness

`release_readiness_service.evaluate()` is read before go-live; closing happens
after. Keeping them apart preserves
`test_pir_records_never_refuses.py::test_the_readiness_verdict_says_nothing_about_pirs`
as written, and means the release page's readiness banner and the pipeline's
`release-ready` endpoint never learn about closeout. The closeout tab has its
own read (§5.2) for what blocks a close.

### 4.3 What happens to the never-refuses guard

`test_pir_records_never_refuses.py` keeps every assertion but one.
`test_a_release_with_an_overdue_action_still_transitions` becomes "still
transitions when the closed state does not require it" — the default, on
every existing template — with a docstring naming the gate and the file that
now guards it. The bookings, incident, readiness and "completing a PIR moves
nothing on the release" assertions all stay true and stay in the file.

### 4.4 Hyper-care state

Computed per read from the release's live hyper-care phase and its
`declared_stable_at`:

| state | when |
|---|---|
| `stable` | `declared_stable_at` is set, whatever the dates say |
| `none` | no live hyper-care phase |
| `planned` | phase `start_date` is after today |
| `active` | started (or undated), and the end day has not passed |
| `overdue` | the end day has passed and nothing was declared |

First match wins in the order `stable`, `none`, `planned`, `overdue`,
`active`. **The end is a day**, compared through `expiry_boundary`: the last
day of the window still reads `active`, the same rule A4, B2, B5 and C2
follow. A phase with no dates is `active` from creation.

### 4.5 Declared stable and handover confirmed

Both are set and cleared by Admin or ReleaseManager (master admin included,
as everywhere). Setting an already-set flag is a **409**, so a recorded actor
and time are never quietly replaced; clear first. Each set and each clear
records a release event (§3.4), so a withdrawal does not erase history.

Declaring stable needs no hyper-care phase and no particular lifecycle state
— a release that skipped hyper-care can still be declared stable. Confirming
handover **requires `operations_group_id` to be set**; a 422 says so.

### 4.6 Incidents in the window

Incidents whose **causal** `release_id` is this release and whose
`detected_at` lies in `[window_start, window_end]`, where `window_start` is
the phase's `start_date` and `window_end` is the first of
`declared_stable_at`, the phase's `end_date`, or now. Read through the
existing `incident_service.list_incidents` filters (`release_id`,
`date_from`, `date_to`), never a second predicate. Rendered as counts by
severity and a list capped at 50 with a total.

## 5. API

All new routes sit on the releases router, JWT, project releases only — an
enterprise release answers 422 the way `scope_deadline` does.

### 5.1 New routes

| route | who | does |
|---|---|---|
| `GET /releases/{id}/closeout` | any tenant member | the composite read, §5.2 |
| `POST /releases/{id}/declare-stable` `{note?}` | Admin, RM | sets the pair, records the event |
| `DELETE /releases/{id}/declare-stable` | Admin, RM | clears the pair, records the withdrawal |
| `POST /releases/{id}/confirm-handover` `{note?}` | Admin, RM | 422 without a group; sets the pair, records |
| `DELETE /releases/{id}/confirm-handover` | Admin, RM | clears, records |

Literal segments are registered ahead of any `/{id}` catch-all in the same
router, the B6 lesson.

### 5.2 `GET /releases/{id}/closeout`

```
{
  "hypercare": {
    "state": "active",
    "phase": {"id", "name", "start_date", "end_date"} | null,
    "declared_stable_at": ..., "declared_stable_by_username": ...
  },
  "handover": {
    "operations_group_id", "operations_group_name",
    "confirmed_at", "confirmed_by_username"
  },
  "pir": {"exists": bool, "status": "draft"|"complete"|null, "completed_at"},
  "incidents": {
    "window_start", "window_end",
    "by_severity": {"P1": n, "P2": n, "P3": n, "P4": n},
    "total": n, "items": [{"id","title","severity","status","detected_at"}]
  },
  "close_targets": [
    {"state_key", "label", "requires_pir_complete",
     "requires_handover_confirmed", "unmet": ["..."], "can_close": bool}
  ]
}
```

`close_targets` has one entry per `is_closed` state on the release's own
template. An empty list means the template has no closed state; the UI says
so rather than rendering an empty card. `unmet` is the same wording the 422
uses, produced by the same function, so the tab and the refusal cannot
disagree.

### 5.3 Existing routes that change

- `ReleaseCreate` and `ReleaseUpdate` gain `operations_group_id`.
  `ReleaseRead` gains it plus `operations_group_name` and the four audit
  columns (usernames resolved as in §3.2).
- `TestPhaseCreate`, `TestPhaseUpdate`, `TestPhaseRead` and
  `ReleaseTemplatePhase` gain `kind`. A second live hyper-care phase is a
  422 naming the first.
- `POST /releases/{id}/transition` returns the §4.1 422 on a refused close.
- Lifecycle template create, update and copy accept and validate the five
  flags.
- `GET /me/work` gains a sixth queue, `hypercare`: releases in `overdue`
  first, then `active` with an end date within seven days; tenant-wide, like
  incidents, because a release has no per-user owner; `due` is the phase
  end; `overdue` is counted from the same `now` with its own `limit=1` query,
  the `_pir_actions_queue` shape.

### 5.4 Events

Release events (§3.4) through `record_auto_event`. One outbox event,
`ReleaseDeclaredStable`, published on declare for the pipeline side; nothing
consumes it yet.

## 6. Frontend

### 6.1 A thirteenth tab, *Closeout*

Added to `RELEASE_TABS` in `ReleaseDetail.tsx` **and** to the file's header
comment, which mirrors it. The tab strip is already `variant="scrollable"`.
Four stacked cards in lifecycle order:

1. **Hyper-care.** State chip and the phase's dates. No hyper-care phase: a
   one-line hint pointing at *Gates & Test Phases*. *Declare stable*
   (Admin/RM) with a confirm dialog and optional note; once declared, who
   and when, and *Withdraw*.
2. **Incidents in the window.** Severity chips and a short list linking to
   each incident. Hidden while the state is `none` — there is no window.
3. **Ops handover.** Operations group picker (the same `useAllUserGroups`
   picker the environment form uses, saving through the release PUT), then
   *Confirm handover*, disabled with a tooltip until a group is set; once
   confirmed, who and when, and *Withdraw*.
4. **Closing.** One row per `close_targets` entry: label, then each
   requirement as a tick or a cross with its reason. If the list is empty,
   the card says the lifecycle has no state flagged as closed and links an
   Admin to the lifecycle editor.

The transition buttons on the Main tab **stay exactly as they are and stay
enabled**. `ReadinessBanner`'s header comment forbids wiring it into
transition controls, and the same holds here: the server decides, the UI
reports. A refused close surfaces the server's 422 text in the existing
snackbar. Today that snackbar shows Axios's generic "Request failed with
status code 422", so `transitionRelease` moves to
`rejectWithValue(formatApiError(err))` and the caller reads
`result.payload` — the conversion three admin panels already had.

### 6.2 Phases

`PhasesTable` gains a *Kind* column and a *Kind* select in its create and
edit dialog. `PhaseGanttEditor` draws hyper-care phases in a distinct colour
with a legend entry. `ReleaseTemplateForm`'s phase editor gains the same
select, and a hyper-care phase shows "after target date" beside its duration.

### 6.3 Lifecycle editor

Beside *Terminal* and *Counts as failure*: *Marks deployed* (always shown),
*Closed* (shown when terminal), and when *Closed* is ticked, *Require PIR
complete* and *Require ops handover confirmed*. Enterprise templates hide all
four. The save payload now includes `is_failed` unconditionally.

### 6.4 My work

A sixth card, *Hyper-care decisions*, through the existing `QueueResult`
component, overdue count in red as the PIR actions card does.

### 6.5 Not built

No release-list column or filter (the state is computed per response and
would join the permanently-unsortable set for no consumer yet), no calendar
marker, no enterprise page changes.

## 7. Testing

### 7.1 Backend

- `test_c6_refuses_only_at_close.py`: with the flag on, the close 422s; PIR
  completed, it succeeds; handover flag on, 422 until confirmed; the same
  flags on a non-closed state are refused at template save; with both flags
  on, a booking, an incident transition, a deployment webhook, `can-deploy`
  and readiness are byte-for-byte what they were. Proved non-vacuous by
  removing the `assert_may_close` call and watching it fail.
- `test_pir_records_never_refuses.py` amended as §4.3.
- Lifecycle schema: five flags round-trip through create, update and copy;
  every §3.1 rule 422s naming the state; enterprise refuses all four;
  **`is_failed` survives a save** (the regression test for the pre-existing
  drop).
- `transition_release`: `actual_date` stamps on the first `marks_deployed`
  state and never again; a renamed flagged state stamps; an unflagged one
  does not.
- Migration: the data step flags the three named states, leaves renamed keys
  alone, seeds the four event types, and the downgrade strips the flags —
  on both engines, plus `test_migration_schema_drift` for the new columns.
- Hyper-care state: one test per state, `stable` beating every date, the
  day-boundary pair (23:59 UTC on the end day is `active`; 00:00 the next
  day is `overdue`), undated phase `active`.
- Incidents in the window: inside counts; one second outside either bound
  does not; `declared_stable_at` closes the window; another release's and
  another tenant's are excluded — each filter proved by mutation.
- One hyper-care phase per release: second create 422s naming the first; a
  soft-deleted one does not count; kind change obeys the rule.
- Instantiation: hyper-care starts on `target_date` and runs forward; test
  phases still end on it; order preserved.
- `declared_stable_by_username` resolves for a user outside the release's
  tenant.
- Audit routes: 409 on re-set; event on set and clear; handover 422 without
  a group; roles enforced; enterprise 422.
- `/me/work`: overdue first, active-within-seven-days next, `stable`
  absent, per-queue isolation on PostgreSQL.

### 7.2 Frontend

- Closeout tab: each card in each state; buttons gated by role; the
  no-closed-state message; ticks and crosses read from `close_targets`.
- The 422 text reaching the snackbar, mocked as an **`AxiosError` shape**,
  never a plain `Error` carrying the final text.
- Lifecycle editor: checkbox visibility rules; payload carries `is_failed`
  on every save.
- Phase kind in table, dialogs and template form; Gantt legend.
- The `RELEASE_TABS` / header-comment agreement test.

### 7.3 Browser pass — load-bearing, not a formality

On the dev tenant, whose templates go through the **migration**, not the
seeder: create a release from a default template and confirm the hyper-care
phase lands after the target date on the Gantt; declare stable and withdraw;
set a group and confirm; turn a close gate on in the lifecycle editor, try to
close, read the refusal, complete the PIR, close; open My work with an
overdue window. Vary the data: a template with two closed states, a
hyper-care phase with no dates.

### 7.4 All three suites

SQLite, PostgreSQL run **alone**, and the **full** frontend suite — not
targeted files — before the PR.

## 8. Deviations on record

- §2.11's "declared stable" moves Operate → Improve. Here it is a flag with
  an audit trail, not a lifecycle state, by decision. A tenant that wants a
  state adds one; the flag works either way.
- §2.11's closeout "records outcome". The outcome is the closed state chosen
  plus the transition note; there is no separate vocabulary, because the
  decision's own example ("Closed", "Closed with Issues", "Rolled back") is
  a list of states.
- §2.5's "PIR completion" is the PIR's status, not its actions.
- The confirmer of an ops handover is Admin or ReleaseManager, not a member
  of the receiving group. A third membership-reading site would have to stay
  in step with the two B3b left, and nothing here needs it yet.

## 9. Existing behaviour changed on purpose

- **The first refusal in Phase 9**, in one function, default off, guarded by
  a named test.
- **`actual_date` keys on a flag, not two state names.** Existing templates
  are migrated so nothing observable changes for them.
- **`is_failed` stops being dropped on save.** A tenant that edited a
  template through the UI since July has lost the flag on its failed states,
  and its DORA change-failure rate has undercounted since. The migration
  cannot know which states those were; the admin guide gets a note and the
  checkbox reappears.

## 10. Not built

- The §2.15 evidence pack. Everything it needs from C6 is now recorded or
  computable; assembling it is Phase 12.
- Enterprise releases, calendar markers, a release-list column,
  notifications on an overdue window. None has a consumer today.
- Automatic hyper-care on deployment. The phase is planned from the
  template or by hand; a deployment webhook neither creates nor starts one.
- Rewriting existing tenants' templates to insert a `deployed` state.
