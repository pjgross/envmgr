# Phase 9 C5a — Cutover runbook and execution

> Status: design approved in conversation 2026-09-28; this document awaits review.
>
> First of three sub-projects that together answer the *Deployment execution*
> line of [requirements.md §2.11](../../requirements.md): "deployment plan +
> window on the release record; pre-deployment checklist as a required gate;
> deploy patterns (rolling / blue-green / canary) per category; post-deployment
> verification (smoke / synthetic) that can trigger rollback; traffic-ramp
> schedule with auto-pause". See [Phase 9](../../phases/phase-9.md).

## 1. What C5 is, and how it was split

**C5 records and advises; the pipeline acts.** EnvManager holds no pipeline or
cloud credentials — the register-not-executor boundary every Phase 9
sub-project has kept. "Verification that can trigger rollback" and "ramp with
auto-pause" are therefore read as: *the pipeline* pauses or rolls back, and
EnvManager records that it did (C4 already records rollback authorisations).

Brainstorming with the owner turned the deployment plan into a **cutover
runbook**: a plan per **(release, environment)**, made of tasks carried out by
different **teams** against different **systems**, joined by dependencies with
**coordination points** — a task that cannot start until several earlier tasks
have all completed ("the automated tests cannot run until every system has been
deployed and brought up"). A runbook can span more than one sitting: pre-tasks
the previous evening, then the plan resumes the next evening with a check that
the pre-tasks completed.

That model absorbs most of §2.11's line: a **pre-deploy check** is a task before
the window, **smoke/synthetic verification** is a task that depends on every
deploy task, **ramp steps** ("10% → 50% → 100%") are a chain of tasks, and the
**deploy pattern** is an attribute of the plan.

C5 is three sub-projects, each with its own spec, plan and PR:

| | Sub-project | Contents | Depends on |
|---|---|---|---|
| **C5a** | **Runbook + execution** (this document) | plan, tasks, dependencies, the ordering refusal, skip/reopen, status history, computed schedule, UI, a `/me/work` queue | — |
| C5b | Pipeline integration + readiness | API-key task updates (new scope), `deploy` tasks following Phase 4 deployment webhooks, runbook findings folded into `release_readiness_service.evaluate()` and so into C3's snapshot | C5a |
| C5c | Templates + copy | tenant runbook templates (blank, or *save plan as template*), instantiate onto a release, copy from another plan, system/team re-matching with unmatched ones flagged, optional attachment to release templates | C5a |

C5b and C5c are independent of each other. §8 lists the seams C5a leaves for them.

## 2. Decisions taken with the owner

| Question | Decision |
|---|---|
| Purpose | Record + advise. EnvManager never calls out to a pipeline. |
| What a plan attaches to | (release, environment), at most one live plan per pair; many systems and teams per plan, with coordination points. |
| A task started before its predecessors complete | **Refused (409)** — within the runbook's own records only. |
| How statuses change | UI in C5a; API-key webhook and Phase 4 deployment link in C5b. |
| Authoring | Blank in C5a; copy, templates and save-as-template in C5c. |
| Planned times | Each task has a **duration**; its start is the latest finish of its predecessors, or the plan's anchor for a task with none; a task may also carry a **fixed "start no earlier than"** time, and then starts at the later of the two. |
| Teams per task | **One.** |
| Permissions | Task status: the task's team, or Admin / Release Manager (and a master admin). Skip and reopen: Admin/RM with a reason. Structure: Admin/RM. |
| Reopen | Kept — Admin/RM only, with a reason, and only while no successor has left `not_started`. |
| Critical path | Kept. |
| `/me/work` queue | Yes, in C5a. |

## 3. Data model — migration `runbooks`

Additive: four new tables, no change to any existing table, no backfill, no
seeding, so **no deploy step**.

### `runbook_plan`

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | FK `tenant`, indexed | |
| `release_id` | FK `release`, indexed | |
| `environment_id` | FK `environment`, indexed | |
| `name` | String(200) | |
| `anchor_start_at` | DateTime(tz) | where a task with no predecessors and no fixed start begins |
| `deploy_pattern` | String(20), nullable | `rolling` / `blue_green` / `canary` / `big_bang` / `other`; validated in the schema, not a native enum |
| `notes` | Text, nullable | |
| `deleted_at` | DateTime(tz), nullable | soft delete |

**At most one live plan per (release, environment)**, enforced in
`runbook_service` — not by a partial unique index, which is inert on SQLite and
so unguardable by half the suite (B3a's and C4's call). Creating a plan for a
pair whose previous plan was soft-deleted **revives** that row, clearing
`deleted_at` and overwriting its content, rather than inserting a second —
C4's rollback-plan lesson. A revived plan keeps no tasks: its old tasks stay
soft-deleted.

The `environment_id` must belong to the tenant and be live on create; an
archived environment already on a plan stays valid on update (A1's
archived-value carve-out). The environment need not be booked by the release —
C5a does not police that.

### `runbook_task`

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | FK `tenant`, indexed | |
| `plan_id` | FK `runbook_plan`, indexed | |
| `name` | String(200) | |
| `description` | Text, nullable | |
| `team_group_id` | FK `user_group`, nullable, indexed | the one team that carries it out |
| `system_id` | FK `system`, nullable, indexed | |
| `kind` | String(20) | `task` / `check` / `deploy` / `verification` / `ramp`; a label in C5a, keyed on by C5b's deployment link |
| `duration_minutes` | Integer, ≥ 0 | 0 is a milestone |
| `fixed_start_at` | DateTime(tz), nullable | "start no earlier than" |
| `status` | String(20) | `not_started` / `in_progress` / `done` / `failed` / `skipped`; server default `not_started` |
| `actual_started_at` | DateTime(tz), nullable | |
| `actual_finished_at` | DateTime(tz), nullable | set on `done`, `failed` and `skipped` |
| `sort_order` | Integer | tie-break for display only |
| `deleted_at` | DateTime(tz), nullable | |

**Status is stored**, unlike the computed states elsewhere in this codebase
(A4's escalations, B5's decommissions, C6's hyper-care). A task's status is a
fact a person reports — "I started it" — not a function of other rows, so
there is nothing it could be computed from. What *is* computed is everything
derived from it: the schedule, lateness, criticality and the plan's state (§5).

**`system_id` is stored, not a `release_system` id**, and validated on write
against the release's current systems. `release_system` rows are hard-deleted
(`DELETE /release-systems/{id}`), which is how C4 came to have orphaned
rollback plans; a task whose system later leaves the release keeps its
`system_id` and renders as "no longer on this release" rather than losing the
link. An unchanged `system_id` re-sent on a full-form save is accepted even
when it is no longer on the release — the permission guards a change, not a
mention (B2's rule).

**`team_group_id`** must be a live group of the tenant when newly assigned; a
group archived after assignment stays valid on the task (A1's carve-out), and
its name still renders through `user_group_service.get_group_names`, the
read-rendering lookup that deliberately does not filter `deleted_at`.

### `runbook_task_dependency`

`tenant_id`, `task_id` (FK `runbook_task`), `predecessor_task_id` (FK
`runbook_task`), unique on `(task_id, predecessor_task_id)`. **Hard-deleted**,
as junction rows are throughout this codebase. Both tasks must be live and in
the **same plan**.

### `runbook_task_event`

Append-only history of every status change: `tenant_id`, `task_id`,
`from_status`, `to_status`, `at` (the time the change is *said* to have
happened), `recorded_at` (server time), `by_user_id` (nullable), `by_api_key_id`
(nullable — unused until C5b, present now so C5b adds no migration), `note`
(the skip or reopen reason, or a free comment). A retried failure keeps its
first failure here; that is what a cutover review asks for.

## 4. Execution rules — the refusal, and its limits

**The invariant: no task is `in_progress` or `done` while any predecessor is
anything other than `done` or `skipped`.** Every refusal in C5a protects that
one sentence. It is ONE invariant with THREE guards, one per way it could be
broken: a task moving forward (`NEEDS_PREDECESSORS` on start/mark-done), a
predecessor moving back (`NEEDS_QUIET_SUCCESSORS` on reopen), and the edges
themselves changing (`PUT .../predecessors` on a started task — below).

| Transition | Allowed when | Who |
|---|---|---|
| `not_started` → `in_progress` | every predecessor `done` or `skipped`; otherwise **409 naming each blocking predecessor and its status** | team or Admin/RM |
| `not_started` → `done` | same predecessor rule (a quick check is ticked in one step; `actual_started_at` = `actual_finished_at`) | team or Admin/RM |
| `in_progress` → `done` / `failed` | always | team or Admin/RM |
| `failed` → `in_progress` | always (retry; `actual_started_at` restamped and `actual_finished_at` cleared, the failure stays in the history) | team or Admin/RM |
| `not_started` / `failed` → `skipped` | **reason required**; successors then treat it as satisfied — the escape hatch | Admin/RM |
| `done` / `skipped` → `not_started` (reopen) | **no successor has left `not_started`**, otherwise 409 naming them; **reason required**; actuals cleared | Admin/RM |

Anything not in the table is a 409 naming the current and requested status.

- **Actual times.** The server stamps them, but a transition may carry `at`
  (must not be in the future), because a task is often ticked after it
  finished. `at` is what the task records; the event records both `at` and
  `recorded_at`. `at` is not checked against predecessors' finish times —
  C5a does not police honest back-dating. The one check on `at` is against
  the task's OWN start: finishing (`in_progress` → `done`/`failed`) at an
  `at` earlier than its `actual_started_at` is a 422 ("cannot finish before
  it started") — a typo, not a history (added in the final-review fix wave).
- **"Team" means** an active member of `team_group_id` in the caller's active
  tenant. A task with **no team, or a team with no members, degrades to
  Admin/RM only** — B3b's degradation rule. Admin and Release Manager are
  `Role.ADMIN` and `Role.RELEASE_MANAGER`; a master admin impersonating the
  tenant counts as Admin. Membership is read in exactly one function,
  `runbook_service.assert_may_update_status`.
- **Structure edits preserve the invariant.** `PUT .../predecessors` refuses
  (409, naming the tasks) a set that would create a cycle, that names a task in
  another plan or a deleted task, or that adds an unsatisfied predecessor to a
  task that has already left `not_started`. A task that has left `not_started`
  cannot be deleted (409 — its history is the record); deleting a not-started
  task hard-deletes its dependency rows in both directions. A plan with any
  task that has left `not_started` cannot be deleted (409). Duration, fixed
  start, anchor, name, team and system stay editable at any time — they move
  the forecast, never the invariant.
- **The limit of the refusal.** C5a refuses only writes to its own runbook
  records. No deployment webhook, release transition, booking, `can-deploy`
  answer or readiness verdict changes because a runbook exists or is
  incomplete. Guard: **`tests/test_c5a_refuses_only_within_runbook.py`**,
  proved non-vacuous by adding a readiness blocker for an unfinished runbook
  and watching it fail. C5b deliberately amends exactly one test in it when it
  adds the readiness finding, as C6 did to `test_pir_records_never_refuses.py`.

## 5. The schedule — computed once, on the server, never stored

`runbook_schedule_service.compute(plan, tasks, edges, now)` is a pure function
— no database access — returning one entry per task and a plan summary. It is
the only place these rules live; the table, the timeline, the `/me/work` queue
and C5b's readiness finding all read its output (or, for the queue, a SQL
predicate held equal to it, §6). All times are UTC instants at **minute
precision** (seconds truncated before comparison). `expiry_boundary`'s
day-granular rule deliberately does **not** apply: a cutover is measured in
minutes.

**Planned pass** — the baseline; ignores status. In topological order:

```
planned_start  = max( anchor_start_at            if no predecessors
                      else max(pred.planned_finish),
                      fixed_start_at             if set )
planned_finish = planned_start + duration_minutes
```

**Forecast pass** — the plan as it now stands:

| Status | forecast_start | forecast_finish |
|---|---|---|
| `done` | `actual_started_at` | `actual_finished_at` |
| `in_progress` | `actual_started_at` | `max(actual_started_at + duration, now)` |
| `failed` | `actual_started_at` | `max(actual_started_at + duration, now)` |
| `skipped` | latest predecessor forecast finish (or anchor) | = forecast_start (adds no time) |
| `not_started` | `max(pred forecast finishes or anchor, fixed_start_at, now)` | forecast_start + duration |

The `now` floor means a task overdue to start is forecast to start now, never
in the past. Before the anchor, `now` is earlier than every computed start and
the forecast equals the plan.

**Per-task flags**

- `late_start` — `forecast_start > planned_start`.
- `overrunning` — `in_progress` and `now > actual_started_at + duration`.
- `slipped_past_fixed_start` — `fixed_start_at` set and the predecessor-driven
  forecast start is later than it: the "second evening starts late because the
  pre-tasks overran" case.
- `blocked` — some transitive predecessor is `failed`.
- `critical` — zero total float in the **forecast** schedule, from a backward
  pass from `forecast_end`: a delay to this task moves the plan's end.
  `done` and `skipped` tasks are never critical.

**Plan summary**: `planned_end` (max planned finish), `forecast_end`,
`slip_minutes` (`forecast_end − planned_end`, never negative in display), and
`state`, first match wins: `complete` (every task `done` or `skipped`; a plan
with no tasks is `not_started`), `failed` (any task `failed`), `in_progress`
(any task has left `not_started`), `not_started`.

Writes refuse cycles, so a cycle cannot reach `compute`; if one does, it raises
rather than looping.

## 6. API

New router `app/api/v1/runbooks.py`, thin over `runbook_service` and
`runbook_schedule_service`. Every request schema declares
`extra="forbid"` — an undeclared field has been silent data loss here twice
(C6's `is_failed`, A4's `priority_rank`). Literal-segment routes are registered
before any `/{id}` catch-all (B6's lesson).

| Route | Who | Purpose |
|---|---|---|
| `GET /releases/{id}/runbooks` | any member | the release's plans with environment name and computed state; `pagination()` + `X-Total-Count`, ordered by environment name then id |
| `POST /releases/{id}/runbooks` | Admin/RM | create (revives a soft-deleted slot) |
| `GET /runbooks/{id}` | any member | **composite**: plan, tasks, edges, §5's schedule and summary, team/system/environment names, and per-task **`allowed_transitions` for the caller** — the UI renders only these, and never re-derives a rule |
| `PATCH /runbooks/{id}` | Admin/RM | name, anchor, pattern, notes |
| `DELETE /runbooks/{id}` | Admin/RM | soft delete; 409 once any task has started |
| `POST /runbooks/{id}/tasks` | Admin/RM | create a task (optionally with `predecessor_ids`, validated as below) |
| `PATCH /runbook-tasks/{id}` | Admin/RM | name, description, team, system, kind, duration, fixed start, sort order |
| `DELETE /runbook-tasks/{id}` | Admin/RM | soft delete; 409 once started |
| `PUT /runbook-tasks/{id}/predecessors` | Admin/RM | replace the set, validated whole (§4) |
| `POST /runbook-tasks/{id}/transition` | per §4 | `{to_status, at?, reason?}` |
| `GET /runbook-tasks/{id}/events` | any member | history, newest first, paginated |

`by_username` on events is resolved **without** a tenant qualifier: under
master-admin impersonation the actor can sit outside the plan's tenant — the
rule A3, A4, C2 and C6 each recorded.

Every query filters `tenant_id` on the entity it selects, and each such filter
has a named test that fails without it.

### `/me/work` — a seventh queue, "Runbook tasks ready to start"

Tasks where the caller is an active member of `team_group_id`, the task is
`not_started`, **every live predecessor is `done` or `skipped`**, and the plan,
release and task are live. Expressed once, in SQL, as
`runbook_service.ready_predicate` (a `NOT EXISTS` over the dependency table),
composed by `my_work_service` under its single clock like the other six.
Ordered by plan anchor, then task id. Admin/RM see only their own teams' tasks
here — the queue is "waiting on me", not a tenant-wide list. Links to the
Runbook tab with the plan selected.

`ready_predicate` and the composite's `allowed_transitions` must agree on
whether a task can start. A test asserts that agreement over a shared fixture —
and, because agreement is not correctness, separate tests pin the predicate's
own answer for each case (a failed predecessor, a skipped one, a deleted one,
another team's task).

## 7. UI

A fourteenth **Runbook** tab on release detail (the strip already scrolls,
`variant="scrollable"`), URL-addressable like the others (`?tab=runbook&plan=`).

- **Plan switcher** — one entry per environment with a plan; *New runbook*
  (Admin/RM) picks an environment, name, anchor and pattern.
- **Header** — environment, anchor (local time), pattern, state chip, planned
  end, forecast end and slip.
- **Task table** on `DataTable`, ordered by planned start then `sort_order`:
  name, kind, team, system (with "no longer on this release" where it applies),
  duration, predecessors by name, planned start, forecast start, status chip,
  flags as icons **with visible text in the tooltip and an accessible name**,
  and action buttons drawn only from `allowed_transitions`. *Skip* and
  *Reopen* open a dialog that requires a reason; any transition may set an
  "actually happened at" time (*Record time*, shown only where a transition
  needing no reason exists). A row's buttons are disabled while its own
  transition is in flight. A refused write re-reads the composite, so the
  screen never keeps offering the action the server just refused.
- **History** (added by Ruling R16; §3/§6 built the data, this section had
  omitted the view) — a per-row, read-only *History* dialog open to every
  viewer: the task's description (its instructions) and its events newest
  first — from → to, `at`, `recorded_at`, who, note. The header shows the
  plan's `notes` when present.
- **Timeline** — a read-only bar view beside the table: planned bars against
  forecast bars, critical tasks emphasised, a "now" line. A small new
  component modelled on `EnvironmentResourceGantt`; `PhaseGanttEditor` is an
  editor for a different entity and is not extended.
- **Task dialog** (Admin/RM) — fields of §3 plus a predecessor multi-select
  offering this plan's tasks only. Server 409s (cycle, invariant) are shown
  through `rejectWithValue(formatApiError(err))`, never `result.error.message`.
- **Live refresh** — until the plan is `complete`, the tab re-reads the
  composite every 30 seconds, paused while the document is hidden and re-read
  at once when it becomes visible again. Several teams tick tasks at once
  during a cutover — and a `failed` or not-yet-started cutover's screen must
  keep updating too (Ruling R15; this said "while `in_progress`" until the
  final review). "Updated HH:MM" beside the state chip gives the time of the
  last successful read, and a failed load or refresh is shown as an error,
  never as an endless "Loading…" or a frozen page that looks live.
- Every raw `<Table>`, if any, sits directly inside a `<TableContainer>` (the
  IA PR 5 sweep enforces it); the timeline scrolls inside itself, never the page.

## 8. Seams left for C5b and C5c

- **C5b** adds a transition path authenticated by API key (scope added to
  `KNOWN_SCOPES`) that calls the same `runbook_service.transition` and fills
  `runbook_task_event.by_api_key_id`. `deploy` tasks with a `system_id` follow
  Phase 4 deployment webhooks for (release, environment, system). **A Phase 4
  webhook is never refused**: a deployment arriving for a task whose
  predecessors are unsatisfied is recorded as ever, the task is left alone and
  flagged "deployment arrived out of order". Runbook findings then fold into
  `release_readiness_service.evaluate()`, amending exactly one test in
  `test_c5a_refuses_only_within_runbook.py`.
- **C5c** clones a plan's tasks and edges with remapping. It converts
  `fixed_start_at` to an offset from `anchor_start_at` when saving a template,
  and back when instantiating; durations and dependencies copy unchanged.

## 9. Testing

**Backend, SQLite and PostgreSQL legs** (run the PostgreSQL leg alone):

- `compute` unit tests against hand-worked plans: a chain; a join (tests wait
  on every deploy); fixed start winning; fixed start slipped (the two-evening
  case); skip passing time through; retry after failure; the `now` floor on an
  overdue task; critical path across two branches of unequal length; a
  zero-duration milestone; a plan with no tasks; a cycle raising.
- One test per row of §4's table, including the 409 text naming each blocking
  predecessor; reopen refused under a started successor; the team,
  Admin/RM, master-admin-impersonation and empty/absent-team paths.
- Structure: cycle refused, cross-plan link refused, unsatisfied predecessor
  added under a started task refused, started task and started plan
  undeletable, deleted plan's slot revived with the same id and no tasks,
  archived team/environment carve-outs, the unchanged-`system_id` carve-out.
- A named, failing-without-it test for every tenant filter.
- `/me/work`: the predicate's own cases, and its agreement with
  `allowed_transitions`.
- `test_c5a_refuses_only_within_runbook.py`, proved non-vacuous by mutation.
- The migration drift test, and `alembic upgrade head` on a scratch database.

**Frontend:** component tests for the tab, plan switcher, task table actions,
the task, skip and reopen dialogs, the timeline's structure and the queue;
error mocks shaped as `AxiosError`; each stateful component re-rendered with
changed props, not only mounted. Full suite, lint and build — the frontend is
the third full suite.

**Browser pass**, the gate that has found what green suites miss on every
Phase 9 sub-project: build the two-evening plan in the dev tenant with **more
tasks and teams than the dev data carries** (at least three teams, a dozen
tasks, two coordination points), then tick a task out of order and read the
409; overrun a pre-task until the next evening's fixed-start task slips; skip,
fail, retry and reopen; sign in as a team member and see the queue; confirm the
30-second re-read; check width at iPad size.

## 10. Out of scope for C5a

Anything that reaches outside the runbook (C5b); templates and copying (C5c);
any notification; a maintenance-window concept distinct from the anchor
(Stable Windows are C9's); per-task multiple teams; enforcing that the plan's
environment is booked by the release.
