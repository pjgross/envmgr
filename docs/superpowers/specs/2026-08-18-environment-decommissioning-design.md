# Phase 7 B5 — Decommissioning workflow + idle auto-detection

> Status: design approved 2026-08-18. Implements the decommissioning half of
> [requirements.md §2.12](../../requirements.md), the last governance
> sub-project in programme B apart from B6.
>
> Gated on B1 (governance fields), which deferred `idle` to this sub-project
> "with its detection rules" rather than shipping a field with no meaning, and
> on B3a (operations groups), which supplies the team that runs a decommission.

## 1. The problem

Decommissioning today is a dropdown. `EnvironmentStatus.DECOMMISSIONED` exists
and `EnvironmentDetail.tsx` offers it in a select. There is no warning, no
chance to object, no record of who decided or why, and no evidence that a
backup was ever taken. An environment can go from serving a team to
`decommissioned` in one click by anyone who can edit it.

The other half of the problem is the opposite failure: nothing tells you which
environments are *candidates*. Ghost environments — provisioned, monitored,
costing money, used by nobody — are invisible in the register, because the
register records what exists and not whether anyone wants it.

B5 is one sub-project covering both halves, so the join between them is
designed once: **idle detection produces candidates, the workflow acts on
them.**

## 2. What B5 does, and the limit of it

**B5 IS THE FIRST SUB-PROJECT IN THIS PROGRAMME THAT ACTS.** A3 warns, A4
advises, B2 advises, B4 advises — each with a named guard test asserting an
absence. A teardown that changes nothing is not a teardown, so B5 cannot make
that promise. It makes a narrower one instead, and the guard test pins it:

**B5 changes exactly two things outside its own records.** It writes its own
decommission, attestation, step and policy rows freely; the claim below is about
everything that existed before it.

1. At teardown, `environment.status` becomes `DECOMMISSIONED`.
2. A booking whose window runs past the scheduled teardown is refused.

**Nothing else.** No booking is cancelled, transitioned, shortened or deleted
at any step. A decommission never moves a booking. Bookings already running
still run to their end. **Idle detection changes nothing at all** — it is a
derived read, and no write anywhere consults it.

`tests/test_b5_acts_only_where_it_says.py` is the guard, and must be proved
non-vacuous the way B4's was: insert real preemption into the teardown path,
watch the first test fail, remove it, watch it pass.

## 3. Idle detection

### 3.1 What counts as activity

A deployment to the environment, or a booking overlapping the window.
**Overlap, not start** — a three-month booking taken four months ago means the
environment was claimed the whole time, and a start-date test would call it
idle.

**Health samples are deliberately NOT activity.** `environment_health_status`
rows are machine-pushed heartbeats: they say the infrastructure is alive, not
that anyone wants it. Counting them would mean any monitored environment never
reads idle — hiding precisely the ghosts that are up, costing money and used by
nobody. This is the single decision that determines whether the feature is
useful or noise.

**Deviation on record.** §2.12 says "no deployments/**logins/traffic** for N
days". This product has no per-environment logins and no traffic telemetry.
Deployments and bookings are the available evidence and are what B5 uses.
Bookings stand in for "logins" imperfectly: a booked-but-unused environment
still reads active, because a booking records intent rather than use.

### 3.2 How it is derived

**In SQL, on read, never stored** — the `_reserved_now_clause` and
`quarantine_clause` pattern. A stored verdict would need invalidating on every
deployment and every booking write, and a Python-side derivation could not be
filtered without windowing the page before the filter.

Three rules decide whether the flag is signal or noise:

- **Threshold is `COALESCE(tier.idle_threshold_days, policy.idle_threshold_days)`**,
  resolved per row. `environment_service._view_query` already joins
  `EnvironmentTier`, so the override costs no new join.
- **Only active environments are judged**, and every other environment answers
  **false**, never null. An inactive or decommissioned environment is idle by
  definition; flagging it buries the real ghosts. False rather than null because
  a nullable verdict forces every consumer to invent a third rendering for a
  question that is simply not being asked — B2's `name_compliant` allows null
  only because "no rule applies" is a state a *policy* can genuinely be in.
- **An environment younger than its own threshold is never idle**, the same
  guard B2 applies to policy age. Otherwise every new environment is born a
  ghost.

Day-granular through `expiry_boundary` (`app/core/day_boundaries.py`), so an
environment created at 15:00 does not lose most of its last day. **Do not add a
second copy of that rule** — that module's docstring exists because applying it
inconsistently in two places that looked equivalent is what produced the bug it
describes.

### 3.3 Surface

A column and a `?idle=` filter on `GET /environments`. **Not sortable**, and
recorded as such in docs/pagination.md: it is a correlated EXISTS, not a column
`apply_sort`'s whitelist can address. `?idle=`'s no-selection is an **omitted
key**; an empty `?idle=` is a 422 and the UI spells no-selection `any`, never
`all` — `buildParams`' own sentinel, which A3, A4, B2 and B4 each collided with
in turn.

**Deviation on record.** §2.12 lists **Idle** in an "extended status set".
It ships **derived, not as a status value** — the same call B1 made for
`reserved_now`, for the same reason: an environment that is idle is still
active.

## 4. The decommissioning workflow

### 4.1 Carrier: a fixed state machine, not a lifecycle template

`environment_request` and `change_request` are lifecycle-template driven, and
B5 deliberately is not.

B3b's retro is explicit: its service keys on four state names in five places,
and **renaming `approved` silently disabled the group gate** — a Test Manager
in no group approved another team's request, HTTP 200. B5 would inherit that
exposure and worsen it, because the refuse-new-bookings rule derives from
workflow state: a renamed state would silently stop refusing. Preventing it
means rebuilding B3b's save-time template validation for a second entity.

The payoff is not there. §2.12 describes one fixed audit sequence, not a
business-variable approval chain. **The variation tenants actually want is
which attestations must be signed** — one wants "final backup", another adds
"DNS removal" and "licence release" — and that ships as configuration (§5.3)
without putting the state names at risk.

### 4.2 States are computed, not stored

Following A4's escalation exactly: **the row stores facts; the state is
derived.** No status column, no scheduler, nothing to invalidate when a notice
period elapses. One SQL clause reproduces the branch order so a worklist filter
and a rendered chip cannot disagree — the "two mechanisms enforcing one
outcome" shape this codebase has paid for repeatedly.

First match wins:

| # | Condition | State |
|---|---|---|
| 1 | `cancelled_at` is set | **cancelled** (terminal) |
| 2 | `torn_down_at` is set | **torn_down** (terminal) |
| 3 | extension requested, not yet decided | **extension_requested** |
| 4 | `scheduled_teardown_at` is in the future | **warned** |
| 5 | otherwise | **due** |

Compared through `expiry_boundary`, because **a deadline is a day**: at instant
precision a decommission reads `due` from one minute past midnight on its own
teardown day, and `?state=warned` then hides exactly the rows closest to their
deadline. This is A4's bug, and B2's, and `formatExpiry`'s before them.

### 4.3 The extension

Granting an extension **moves `scheduled_teardown_at` to `extension_until` and
leaves the extension block in place as the record of the decision**. Branch 3
stops matching, the row falls through to `warned` on the new clock, and the
audit trail survives. Refusing sets `granted = false` and moves nothing.

**One extension per decommission.** A second request is refused with a message
pointing at cancel-and-re-raise. This keeps §2.12's "warning → extension
approval" shape without an unbounded reprieve loop, and avoids a child table
whose only purpose is holding repeat reprieves. If a tenant needs more, the
cancel path is not lossy — the cancelled record stays.

### 4.4 Teardown is gated on attestations

`torn_down_at` cannot be set until every active `is_required` step has a signed
attestation. The refusal is a 422 **naming the missing steps** — a bare "not
allowed" on a checklist is unactionable.

Teardown is the one acting step. It sets `environment.status =
DECOMMISSIONED`, records who and when, and **surfaces** any bookings still on
the calendar without touching them.

**Deviation on record.** §2.12 says teardown updates the "inventory/calendar
... to **Available**". There is no Available status in this model, and B5
destroys nothing: it sets `DECOMMISSIONED` and leaves the calendar to humans.

**Deviation on record.** §2.12 says "final backup → teardown". EnvManager is a
register: it holds no cloud credentials and no way to destroy a resource, so it
cannot take a backup or tear anything down. Attestations record that a human
did — who, when, and a reference (snapshot id, ticket, runbook link). This is
the same call B2 made on §2.12's "quarantine/**terminate**".

### 4.5 Permissions

| Action | Who |
|---|---|
| Initiate, decide extension, sign attestations, tear down, cancel | The environment's **operations group**, or Admin / master admin |
| Request an extension | The environment's **named owner**, or Admin |

The shape is B3b's: the party being acted upon (here the owner, there the
requester) is **not** gated on group membership, or the primary journey becomes
impossible — the person defending their environment is by definition not on the
team decommissioning it.

**B3b's degradation rule is carried over verbatim: where an environment has no
operations group, or the group is empty, every team action falls back to
Admin-only.** `operations_group_id` is nullable and most environments have no
group yet, so a permission that resolves to nobody is a stuck workflow.

**Cancel is always available to Admin.** A4 established that an approval
workflow with no escape hatch produces unrecoverable states, and B3b shipped
two of them. There is no edit path on a decommission; cancel-and-re-raise is
the correction.

Membership is read through the same helper `environment_request_service` and
`environment_service.assert_may_edit_handover` use. **Those two must stay in
step with this third caller**: same tenant scoping, same Admin-or-master
bypass, same degradation.

## 5. Data model

All additive. Migration `envdecommission`: four new tables, one nullable column
on `environment_tier`, no backfill.

### 5.1 `environment_decommission`

One row per decommission attempt. Stores facts only (§4.2).

- `tenant_id` (FK, indexed), `environment_id` (FK, indexed)
- `reason` (Text, required — a decommission with no stated reason is not an
  audit record)
- `warned_at`, `scheduled_teardown_at`, `initiated_by`

  `scheduled_teardown_at` defaults to `warned_at` plus the tenant's
  `decommission_notice_days` (§5.4). The initiator may set a **later** date and
  never an earlier one — an initiator who could shorten the notice period would
  make §2.12's five-day warning advisory, and the refusal in §6 derives from
  this date.
- extension block: `extension_requested_at`, `extension_requested_by`,
  `extension_reason`, `extension_until`, `extension_decided_at`,
  `extension_decided_by`, `extension_granted` (nullable Boolean — null means
  "not decided", which is branch 3)
- `torn_down_at`, `torn_down_by`
- `cancelled_at`, `cancelled_by`, `cancel_reason`
- `deleted_at`

**At most one live decommission per environment**, enforced in the service (a
partial unique index would be inert on SQLite — the same call B3a's group-name
uniqueness made). "Live" is not cancelled, not torn down, not soft-deleted.

### 5.2 `environment_decommission_attestation`

`decommission_id` (FK, indexed), `step_key`, `signed_by`, `signed_at`,
`reference` (String(500)), `notes` (Text). Unique on
`(decommission_id, step_key)`. No `deleted_at` — an attestation is an immutable
audit record, following `BookingStatusHistory`. A mistaken signature is
corrected by cancelling the decommission.

`step_key` is a plain string, **not** an FK to §5.3: an attestation must still
read correctly after its step definition is retired. Same rule as A2's
`environment_group_id` being provenance rather than a live link.

### 5.3 `environment_decommission_step`

The tenant's checklist vocabulary, shaped like `environment_tier` and
`booking_type`: `tenant_id`, `key`, `label`, `description`, `display_order`,
`is_required`, `is_active`, `deleted_at`.

Seeded with `final_backup` and `teardown` through a defaults module, following
`environment_tier_defaults` and `environment_request_defaults`. **The seed must
run for existing tenants in the migration**, or a tenant cannot complete a
teardown at all — B3b's `envrequests` deploy note records exactly this failure.

### 5.4 `environment_lifecycle_policy`

One row per tenant, shaped like `EnvironmentNamingPolicy`: unique `tenant_id`,
no `deleted_at`, no DELETE path.

- `idle_detection_enabled` (Boolean, default false)
- `idle_threshold_days` (Integer, default 30)
- `decommission_notice_days` (Integer, default 5 — §2.12's five-day warning)

Absent a row, the defaults apply and idle detection is off. **Idle detection
defaults to off** so no tenant's estate lights up with a flag they did not ask
for — B2's `?governance_gap=true` matched every environment on first deploy and
looked exactly like a bug.

### 5.5 `environment_tier.idle_threshold_days`

One nullable column. Null means "use the tenant default". A Dev sandbox quiet
for 30 days is a ghost; a DR or Training environment quiet for 90 is behaving
normally, and a single tenant-wide number necessarily mislabels one of them.

## 6. The booking refusal

### 6.1 The rule

**A booking whose window extends beyond `scheduled_teardown_at` is refused.**
Bookings that finish before teardown are accepted.

A blanket "no new bookings once warned" was considered and rejected: the
environment still exists until teardown, and a team may legitimately need it
next week. The date rule is derived, needs no carve-out, and **granting an
extension moves the line out so more bookings become legal with no second
write**.

Refusal applies only while a decommission is **live** (§5.1). A cancelled or
torn-down decommission refuses nothing.

### 6.2 Where it lands

On **every** create path, or it becomes the `exclusive_use_requested`
asymmetry CLAUDE.md still lists as open — a rule meaning different things
depending on which path made the booking:

- `booking_request_service.create_request` — the modern multi-environment path
- `booking_request_service.add_environment` — **a create in disguise**, and the
  exact shape a grep-by-endpoint sweep misses
- `booking_service.create_booking` — the legacy path.
  `release_booking_service` delegates to it, so covering it covers the release
  path too

Plus the date-extending edit paths: moving an end date past teardown is the
same act as booking past it.

A sweep must cover all of them by grep, in the manner docs/pagination.md's
five grep forms prescribe, and the guard test must assert each path
individually. A test covering one path proves nothing about the others.

### 6.3 A degenerate case B5 also closes

**Nothing today refuses a booking on a `decommissioned` environment.** No
create path looks at `environment.status` at all. This is the same question at
its limit, and B5 closes it with the same rule.

## 7. Pre-existing defect this work must not build on

`environment.status` stores the enum **member name** — the dev database holds
`ACTIVE` and `INACTIVE`, not `active`/`inactive`. `SAEnum` stores `.name`, and
`environment_tier.py` already documents this.

So `environment_health_service.py:103`'s

```python
Environment.status != "decommissioned",
```

compares against a value that never appears in the column. **The condition is
always true, and decommissioned environments are not excluded from the health
overview.** `releases.py:887` gets it right by comparing to the enum member.

B5 filters on status throughout, so this line is fixed as part of this work
rather than built on top of. Every new status comparison B5 adds goes through
the enum member, never a string literal.

## 8. API surface

- `POST /environments/{id}/decommission` — initiate
- `GET /environments/{id}/decommission` — the latest record for that environment
- `POST /decommissions/{id}/extension` — request
- `POST /decommissions/{id}/extension/decision` — grant or refuse
- `POST /decommissions/{id}/attestations` — sign a step
- `POST /decommissions/{id}/teardown` — mark torn down
- `POST /decommissions/{id}/cancel`
- `GET /decommissions` — worklist, on `pagination()` + `sorting()`, `?state=`
  filter, ordered by a **unique** key (append the primary key as a tiebreaker,
  or `LIMIT`/`OFFSET` duplicates and drops rows once ties exist)
- `GET /environments` gains `?idle=`; the view carries `idle` and
  `decommission_state`
- Admin: `GET`/`PUT /tenant/environment-lifecycle-policy`; CRUD on
  `/tenant/decommission-steps`; `idle_threshold_days` on the tier editor

Every request schema declares `extra="forbid"`. A1's `ProjectCreate` silently
discarded `priority_rank` for want of it, and `POST /tenant/lifecycle-templates`
still silently drops `required_fields` — the same class, still open.

`decommission_state` is **required, not defaulted**, on every response type
carrying it. A defaulted field renders a confident answer at a construction site
that never computed one; B4's `protection_level` and B2's `compliance_gaps`
both took the required-positional treatment for this reason.

## 9. UI surface

- **`EnvironmentList`** — an `Idle` chip and a decommission-state column, with
  matching server-side filters. Both are server-paged from the start; the
  pagination programme's rule is that a page is never fetched and then filtered
  in the browser.
- **`EnvironmentDetail`** — a decommission panel carrying the banner, the
  controls for whichever actions the viewer may take, and the attestation
  checklist. Repair and action controls sit **next to the state they act on**,
  which is A2's `GroupTransitionPanel` lesson: a banner that diagnoses a
  situation and offers no way to act on it is where three tasks quietly removed
  the affordance.
- **`/decommissions`** — the worklist, following `/contentions`.
- **Admin** — the lifecycle policy and the decommission-step vocabulary.

Errors surface through `rejectWithValue(formatApiError(err))`. Redux Toolkit's
default `miniSerializeError` drops `response.data.detail`, so the user would
otherwise see "Request failed with status code 422" instead of which
attestation is missing — and a test rejecting with a plain `Error` carrying the
final text **passes while the app is broken**. Mock an `AxiosError` shape.

## 10. Testing

- **`tests/test_b5_acts_only_where_it_says.py`** — the guard on §2, proved
  non-vacuous by inserting real preemption and watching it fail.
- **State-versus-clause agreement** — the computed state and its SQL predicate
  answer identically over a fixture spanning all five branches, including rows
  on their boundary day. A4's `state_predicate` test is the model.
- **One test per create path** for the refusal (§6.2). Three paths, three
  tests, plus the edit paths.
- **Dual engine.** The `COALESCE` threshold, the day-boundary comparisons and
  the naive-vs-aware `_utc` normalisation are exactly where SQLite and
  PostgreSQL diverge; B2 shipped a `TypeError` that 500'd every environment
  list and was invisible on the PostgreSQL leg.
- **Mutation pass.** Every rule this document explains at length needs a named
  test that fails when the rule is removed — six of seven mutation survivors on
  A4 were precisely the rules its comments explained best.
- **Browser pass.** Six defects on the pagination programme and three on B2
  were found only by opening the page, every one with a fully green suite.

## 11. Out of scope

- **Notifications.** Nobody is emailed when their environment is warned. The
  register surfaces it on the environment, the list and the worklist. Adding a
  channel is its own sub-project and B5 does not pretend to have one.
- **Scheduled or automatic teardown.** Nothing fires on the teardown date; a
  human signs the attestations and marks it torn down. There is no scheduler in
  this codebase, and A4 established that derived state is what removes the need
  for one.
- **Automatic decommission proposals from idle detection.** Idle flags
  candidates; a human decides. An automatic proposal would make B5 act on
  evidence §3.1 already concedes is partial.
- **Restoring a torn-down environment.** `DECOMMISSIONED` is reachable and
  editable back to `ACTIVE` through the existing status field; B5 adds no
  un-teardown path and no attempt to reverse what was attested.
