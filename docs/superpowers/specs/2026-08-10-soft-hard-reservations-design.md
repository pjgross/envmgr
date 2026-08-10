# Phase 7 B4 — Soft (preemptible) vs hard (protected) reservations, and time-slot presets

- **Status**: design agreed, not implemented
- **Requirement**: [requirements.md §2.12](../../requirements.md) — "Soft (preemptible) vs hard
  (protected) reservations; time-slot bookings (half-day / sprint / release cycle)"
- **Depends on**: A4 (project-aware contention) for the verdict this extends; A1 for
  `project.priority_rank`; the existing `booking_type` tenant vocabulary

## The one-sentence version

A booking request declares whether its claim on an environment is **soft** or **hard**, defaulted
from its booking type; the level breaks the tie in A4's contention verdict **only where project
priority cannot separate the two bookings**; and the same booking type carries a default duration
so "half-day", "sprint" and "release cycle" become one click rather than arithmetic.

## What B4 does not do, and why that is the design

**B4 ADVISES; IT NEVER BLOCKS AND IT NEVER PREEMPTS.** Nothing is refused, nothing is cancelled,
no booking is transitioned, and no overlap that is permitted today becomes impermissible. A "hard"
reservation is not mechanically protected — it is *declared* protected, and that declaration wins
an argument that today has no winner at all.

This was chosen over three alternatives, all of which were on the table:

- **Refusing the overlap.** Would make "protected" mean something enforceable, and would finally
  close the standing asymmetry where legacy `POST /bookings/` 409s on an exclusive overlap while
  the modern `create_request` does not. Declined: it is the first refusal in Programme B outside
  B2's name pattern, and it converts a scheduling hint into a hard gate on the primary journey.
- **Refusal plus an explicit preemption record** (shaped like A4's escalation). Declined as
  scope — A4 already provides the ask-and-answer machinery, and a second one for the same
  disagreement would be two mechanisms enforcing one outcome.
- **Auto-preemption** — a hard booking transitions a soft one out. Declined for the reason every
  prior sub-project declined it: the register acts on a booking without a human.

The guard on all of that is `test_b4_advises_never_blocks.py`. This is the **fourth** sub-project
running whose central promise is a named test rather than an absence in the diff (A1's
`test_an_agreement_changes_no_booking_behaviour`, A4's
`test_a_contention_changes_no_booking_behaviour`, B2's `test_b2_advises_never_blocks.py`).

**No new escalation, no new worklist, no new stored verdict.** B4 stores two vocabulary defaults
and one column on the request. Everything else is computed, exactly as A4's verdict is.

## Decisions taken during brainstorming

1. **Advisory, feeding A4's verdict** — not refusal, not preemption. (Above.)
2. **Rank first, protection breaks ties.** A4's rank rule is untouched and stays primary.
3. **Default from the booking type, overridable by Admin / Release Manager.** The owner's reason:
   "this must be configurable by tenant — some customers may have different costing and process
   options for a hard booking." That makes the level a first-class, queryable, sortable column
   rather than a UI hint, so Phase 11 (Cost & FinOps, §2.14) can read it without a migration.
4. **Duration presets live on the booking type too**, not in a second vocabulary and not
   hardcoded in the form.
5. **`exclusive_use_requested` is kept, untouched, and relabelled alongside** — the two axes are
   orthogonal and both are needed. (See "Two adjacent controls".)

## Two adjacent controls that sound alike

The booking form will carry both. They answer different questions and neither implies the other:

| | Question | Behaviour today / after B4 |
|---|---|---|
| `exclusive_use_requested` | *Can anyone else be in here with me?* | Blocks on legacy `POST /bookings/` (409); **not** enforced by `create_request` |
| `protection_level` | *Can I be pushed out?* | Never blocks anywhere |

A booking can legitimately want exclusive use of the environment while being entirely
preemptible — a load test that must run alone but can move — which is exactly why folding them
into one three-value scale was declined.

**B4 changes nothing about `exclusive_use_requested`.** The form groups the two under one
*Sharing & protection* heading with helper text, and the user guide states the distinction. The
standing inconsistency — that the modern multi-environment path does not enforce exclusivity at
all while the legacy single-environment path 409s — is **recorded here and deliberately not
fixed**: fixing it means shipping a refusal, which is the thing B4 has just declined to do. It
belongs in its own ticket.

## Data model

One migration, `bookingprotection`, fully additive: two columns on `booking_type`, one on
`booking_request`, no backfill beyond the server defaults.

### `booking_request.protection_level`

```python
protection_level: Mapped[str] = mapped_column(
    String(20), nullable=False, server_default="soft", default="soft"
)
```

`soft` | `hard`, as a `String` with a module-level constant pair, following the house rule that
enum columns are never native (`native_enum=False`) — here taken one step further to a plain
`String`, matching `booking.status`, which is the column this one sits beside conceptually.

**It lives on the REQUEST, not the booking.** A2's group bookings share one `BookingRequest`, and
A4's argument that "group reachability is exactly equal to individual reachability" depends on
`_record_values` being byte-identical across members. A per-booking level would let one member of
an atomic group be protected and another not, which is not a state the group transition can
express. **Nothing may add a per-booking override without revisiting A2's atomicity argument.**

### `booking_type.default_protection_level`

Same domain, `nullable=False`, server default `'soft'`. A tenant declares once, in a vocabulary it
already configures, that (say) Release-cycle bookings are protected and ad-hoc ones are not.

### `booking_type.default_duration_minutes`

`Integer`, **nullable** — null means "this type has no preset", which is a legitimate state and
not a missing value, the same call B1 made for `environment.expires_at`.

Minutes, not hours, because "half-day" is 240 and a sprint is 20,160 and one unit must hold both.
See "Duration is applied by rule, not by arithmetic" for why the unit alone is not enough.

### Every existing row lands on `soft`

Which means **no verdict A4 renders today changes on deploy**. That is what makes this additive
rather than a silent, retrospective reversal of live advice, and it gets its own test (see
"Testing").

## The verdict extension

`_ranks_for` already performs the tenant-filtered `Booking → BookingRequest → Project` LEFT JOIN.
It gains `BookingRequest.protection_level` from **that same select** — one query, no extra round
trip, no new lookup to keep in step — widening its tuple from three values to four:

```
booking id -> (requested_project_id, resolved_project_id, priority_rank, protection_level)
```

`_decide` keeps its branch order exactly as it is — `no_project` first, then `unranked`, then
`equal_rank`, then `ranked` — for the reason its docstring already gives. The change is that the
three no-winner branches consult protection **before** giving up:

| Rank branch | Levels | Outcome |
|---|---|---|
| `ranked` | not consulted | unchanged — rank decides, as today |
| `no_project` / `unranked` / `equal_rank` | both known, and they differ | **`OUTCOME_PROTECTED`**, winner = the `hard` side |
| `no_project` / `unranked` / `equal_rank` | equal, or either unknown | unchanged — today's outcome and today's reason |

**Rank stays strictly primary.** A hard booking on an unranked project still loses to nothing it
does not already beat, and a soft booking on a top-ranked project still wins. This is what makes
B4 purely additive to A4 rather than a reweighting of it.

### One outcome constant, four reasons

`OUTCOME_PROTECTED` carries a **composed** reason naming why rank could not separate the pair:

- "both projects have the same priority rank; the protected booking holds"
- "at least one project has no priority rank; the protected booking holds"
- "at least one booking is not linked to a project; the protected booking holds"
- "at least one booking's project is archived or belongs to another tenant; the protected booking
  holds"

Four, not three, because A4's `no_project` already carries two — and the second of them exists
precisely so a user looking at an archived project's name beside the verdict is told the real
problem. Composing rather than replacing keeps that.

Same shape as A4's `no_project` carrying two reasons, and for the same reason: the rank fact is
still the thing the reader needs, and collapsing it to a bare "the protected booking holds" throws
away the only information that tells an admin whether to go and set a rank.

### An unknown level must never lose

`verdicts_for_pairs` reads a booking id absent from `_ranks_for` as project-less — another
tenant's, or stale. Its widened `missing` sentinel is `(None, None, None, **None**)`, and the
protection branch fires **only when both levels are known and differ**. A booking we cannot see
must not be declared the loser of an argument on the strength of a level we never read. This is a
one-line rule with a named test, because the obvious implementation — defaulting the sentinel to
`"soft"` — silently makes every unresolvable booking lose to any hard one.

## Setting the level

### On create

The request **inherits** its booking type's `default_protection_level`. Both create paths set it:
`booking_request_service.create_request` (modern, multi-environment) and
`booking_service.create_booking` (legacy single-environment, which already constructs a
`BookingRequest` and already carries `exclusive_use_requested=data.exclusive_use` — the same line
gains the level).

A caller who is neither `Role.ADMIN` nor `Role.RELEASE_MANAGER` may not **choose** a level: sending
one that differs from the booking type's default is a **403**. Sending one that *equals* it is
accepted — the same unchanged-value carve-out as the update path below, and load-bearing rather
than tidy, because `BookingForm` shows non-admins their inherited level read-only and submits the
whole form including it.

The schema also declares `extra="forbid"`, which is the house rule after A4's `ProjectCreate`
silently discarded `priority_rank` and only a browser pass caught it. That is a **different**
guard from the role check: `extra="forbid"` 422s an *unknown* key, the role check 403s a *known*
key the caller may not set.

### On update

`protection_level` joins `STANDARD_REQUEST_FIELDS`, so it is editable through
`PATCH /booking-requests/{id}/standard-fields`, which keys on `model_fields_set` — an omitted key
means "leave alone". Only Admin / Release Manager may **change** it.

### The unchanged-value carve-out

**A non-admin full-form save that re-sends the request's EXISTING level is accepted.** Taken
directly from B2's name rule, and for the identical reason: without it, the moment an Admin marks
a booking hard, every subsequent full-form save by the original booker 422s on a field they did
not touch and cannot change. The permission guards a *change*, not a *mention*.

Note the shape this shares with A1's repeated defect — "an FK validated on an update path 404s a
full-form save once the referenced row is archived". Different mechanism, same failure: a
validation written for the create path applied unaltered to a full-form update breaks saves that
change nothing.

## Duration is applied by rule, not by arithmetic

Picking a booking type in `BookingForm` fills the end field from the start plus
`default_duration_minutes` — and **only when the user has not already edited the end**, so a
deliberate choice is never overwritten.

The application rule, in one helper with its own test:

> A duration that is a whole multiple of 1440 minutes is added as **calendar days**. Anything else
> is added as **minutes**.

So "sprint = 14 days" from 09:00 on 20 March lands on 09:00, not 08:00, across a spring-forward;
"half-day = 240 minutes" from 09:00 lands on 13:00. This codebase has already paid twice for
instant-vs-calendar arithmetic — `formatExpiry` reporting an environment "overdue by 1 day"
throughout the day it expired, and SP5a's DST-correct utilization needing per-date localization —
so the rule is stated and tested rather than left as `+ n * 60000`.

### The preset is a convenience, never a constraint

Nothing server-side validates that a booking's length matches its type's preset. Consistent with
advises-never-blocks, and it means a tenant editing a preset does not retroactively make live
bookings wrong. There is no stored "slot" and no slot vocabulary.

Environment-defined slots (AM/PM, aligned-or-refused) were considered and declined: they refuse,
and they collide with Phase 5 SP5a's operating hours, which already model when an environment is
available.

## A defect B4 must fix to be usable at all

`BookingForm.tsx` collects `start_date`/`end_date` as `datetime-local`. `EditStandardFieldsDialog`
and `BookingDetail`'s inline fields bind **the same fields** as `type="date"`.

Saving a half-day booking through either therefore truncates 09:00–13:00 to 00:00–00:00 — a
**zero-length booking**, which then conflicts with nothing at all, because overlap is
`start < end AND end > start` and a zero-length interval satisfies neither. Today that is rare
because bookings are day-scale by habit; the moment B4 ships half-day presets it becomes routine.

Both move to `datetime-local`. This is in scope because B4's own feature is otherwise destroyed by
the app's own edit path.

## API

### `GET /bookings`

- New filter `?protection=soft|hard`. Applied **in SQL**, on the existing `BookingRequest` join —
  the one A3 established both list filters must share, because the pre-branch shape was a join per
  filter and restoring it breaks exactly the pair the project rollup sends while every
  single-filter test stays green.
- **"No selection" is an OMITTED KEY.** The UI spells it **`any`**, never `all`: `buildParams`'
  own sentinel is `'all'`, so a vocabulary containing that value builds byte-identical params for
  two different states and the grid never refetches. Third sub-project to hit this (A3, A4, B2).
- `protection_level` joins `BOOKING_SORTS`. **Unlike `agreement_gap`, this column IS sortable** —
  it is a stored column on a joined table, not a value resolved after the page is fetched. It is
  therefore *not* a member of docs/pagination.md's permanently-unsortable set.

### Response fields

`protection_level` on `BookingResponse` and on `EnvBookingSummary`, both booking-shaped response
types, exactly as A3 added its gap pair to both. It comes off the already-loaded
`BookingRequest` — no new query, no batch resolver, nothing to keep in step.

### `GET /booking-types` / `POST` / `PATCH`

`default_protection_level` and `default_duration_minutes` on the read and write schemas. Both
write schemas declare `extra="forbid"`.

## UI

1. **`BookingForm`** — a *Sharing & protection* group holding the existing exclusive-use control
   and the new level, with helper text distinguishing them. The level is **read-only** for
   non-Admin/RM, rendered as the inherited value with the booking type named, not hidden: a user
   should be able to see that their release-cycle booking is protected.
2. **`/bookings` grid** — a `Protection` column and a filter whose no-selection is `any`.
3. **`BookingDetail`** — the level in the header beside the status.
4. **`ContentionVerdict`** — renders `OUTCOME_PROTECTED` with its composed reason. The same
   component already serves the Conflicts panel and the `/contentions` worklist, so both get it
   from one change.
5. **Calendar / Gantt** — protected bookings take a **border or hatch, never a colour**. Both
   `BookingCalendar` and `BookingScheduleGantt` already spend colour on `STATUS_COLORS` (and
   `booking_type.color` is the calendar's other colour vocabulary), so overloading it makes two
   vocabularies fight for one visual dimension. A border alone is also not accessible, so the
   marker is paired with text — "Protected (hard) reservation" in the tooltip — which is what the
   jsdom tests can assert on, since neither component's geometry renders there.
6. **`BookingTypesPanel`** — the two new defaults beside the existing lifecycle template. The
   panel already reads `result.payload` via `formatApiError`, so its error path needs no change.

## Testing

### The promise

`backend/tests/test_b4_advises_never_blocks.py` — a hard reservation is still bookable over, still
transitionable, still editable; `check_overlap` returns **identically** for both levels; no new
409 or 422 exists on any booking path. UI half: `describe('B4 advises; it never blocks')`.

### The migration is inert

A test asserting that an all-`soft` estate produces **byte-identical verdicts** to the pre-B4
rule, for every one of A4's four outcomes. This is the only thing that proves the server default
really is inert, and it is the test that fails if someone later "simplifies" the protection branch
to fire on equality.

### The rules that need a named test each

A rule the code explains at length reads as a rule that is guarded, and usually is not — six of
seven mutation survivors on A4 were exactly such sentences. Each of these gets a test that fails
when the rule is deleted:

- Rank stays primary: a `soft` booking on rank 1 beats a `hard` booking on rank 5.
- Protection speaks in all three no-winner branches, and in none of them when levels are equal.
- An **unknown** level never loses (the `missing` sentinel).
- The unchanged-value carve-out — and note B2's lesson here: **run the mutation against the whole
  B4 file set, not the one file you expect**, because two mechanisms (the role check and the
  equality carve-out) enforce one outcome and either can hide the other.
- The DST rule, with a test crossing a spring-forward boundary in both branches.
- `?protection=` filters in SQL before the window, so `X-Total-Count` describes the filtered set.

### Dual engine

Both legs, per the standing rule. Nothing here is dialect-gated, but `?protection=` is a new
`WHERE` on a joined table and the sort is a new `ORDER BY` on a `String` column — which
`apply_sort` will case-fold, harmlessly here since both values are lowercase, but the assertion
must be on **rendered row order**, never on the emitted SQL token.

## Migration

`bookingprotection`, additive, hand-written DDL per the house rule (no `--autogenerate`):

- `ALTER TABLE booking_type ADD COLUMN default_protection_level VARCHAR(20) NOT NULL DEFAULT 'soft'`
- `ALTER TABLE booking_type ADD COLUMN default_duration_minutes INTEGER NULL`
- `ALTER TABLE booking_request ADD COLUMN protection_level VARCHAR(20) NOT NULL DEFAULT 'soft'`

No backfill, no data migration, no index — `?protection=` is a low-cardinality filter always
applied alongside the tenant filter, so an index on it would not be used.

**Note for the drift test**: `tests/test_migration_schema_drift.py` compares only column NAME
SETS, not types or defaults. It passing is **not** evidence that these three columns match their
models — B3a shipped four real drifts past it, including naive-vs-timezone-aware timestamps.
Check the types by hand.

## Risks carried into implementation

- **Everyone picks hard.** The role gate plus the booking-type default is the whole mitigation.
  There is no quota and no expiry on a hard reservation. If an estate ends up all-hard the axis
  stops discriminating and the verdict silently reverts to A4's three no-winner outcomes — which
  is a degradation to today's behaviour, not a break, but it will look like the feature stopped
  working. Worth a note in the admin guide.
- **`OUTCOME_PROTECTED` is a fifth outcome**, and A4's spec explicitly declined a fifth one for
  "project not resolvable" on the grounds that a malformed link "is not a different KIND of
  answer". This one is: it is the first outcome with a winner that rank did not choose. The
  distinction is deliberate and stated here so it does not read as A4's rule being forgotten.
- **The frontend must not evaluate the tie-break.** The verdict, its winner and its reason all
  come from the server, as A4's already do. A second evaluator in TypeScript is the B2 regex
  mistake in a different costume.
- **Phase 11 will want to price this.** The level is a stored, filterable, sortable column
  precisely so a cost model can group by it later — that is why it is a column rather than a UI
  hint. It carries **no index**, for the reason given under Migration; a Phase 11 aggregation over
  the whole estate may need one, and that is Phase 11's call to make with a query in front of it.
  Nothing in B4 computes cost, and nothing should.

## Deviation on record

§2.12 says "soft (**preemptible**) vs hard (protected)". B4 preempts nothing — no booking is
transitioned, rescheduled or cancelled by anything in this sub-project, automatically or on
request. "Preemptible" here means *loses the argument*, and a human then acts through A4's
existing escalation and decision path. Recorded the same way B2 recorded that it terminates
nothing.
