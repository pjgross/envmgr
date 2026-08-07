# Usage Agreement Enforcement — Design

**Phase 7, sub-project A3.** Roadmap line: *"Enforcement of the `usage_agreement` table A1 ships (project A may use environment E in window W) — `BookingService` checking agreements, plus the cooperation rules of [requirements.md §2.12](../../requirements.md). A1 deliberately ships the schema whole, including its window, so A3 owns only the check and the rules, never the table."*

## Problem

A1 shipped `usage_agreement` — "project P may use environment E, optionally between two dates" — and deliberately made it inert. Its spec says so plainly: *"A1 records it and nothing reads it: no booking is rejected, nothing warns."* A2 left the table untouched as well.

So today a project can book an environment it has no agreement for, and nobody finds out. A3 makes the table mean something.

## The decision that shapes everything else: A3 warns, it does not block

**No booking is ever refused.** A gap produces a warning the booker sees at creation and can acknowledge; it never prevents the booking.

This is a deliberate narrowing of the roadmap line's word "enforcement", taken because the people blocked would usually be unable to fix the cause. Agreements are admin-maintained; a tester booking an environment at 9am cannot conjure one. A rule that stops work its subject cannot unblock gets routed around, and the routing-around is invisible.

Two consequences worth stating:

- **A1's guard test survives unchanged.** `test_an_agreement_changes_no_booking_behaviour` asserts that a booking against an unagreed environment still succeeds. A1 wrote it to detect exactly this sub-project overstepping. Under a warn-only A3 it stays green and stays useful, rather than being renegotiated by the change it was written to catch. **If it ever fails, someone has made A3 block.**
- **`BookingService`'s create path keeps its outcomes.** A3 adds information to the response, not a new refusal.

## What is checked

For each booking whose **request** names a project, is there a live `usage_agreement` for `(project, environment)` whose window covers the booking's dates?

| Situation | Result |
|---|---|
| Request has no `project_id` | **No check at all** |
| An agreement covers the dates | Nothing |
| Agreements exist, none covers the dates | Warn — *"outside the agreed window (1 Jan – 30 Jun)"* |
| No agreement for this environment | Warn — *"no usage agreement for Mortgage SIT"* |

### No project means no check

Most existing bookings have no project — in the dev database, 2 of 11 — and **every** booking made before A1 shipped has none. Refusing or warning on those would make A3's first day a wall of noise about historical data nobody can retrospectively fix.

Adoption is therefore opt-in per booking: link a project and the check applies. This mirrors A1's own treatment of a missing owner — reportable as a gap, never blocking.

### "Live agreement" does NOT mean `deleted_at IS NULL`

**This is the trap A2 explicitly left for A3, and the check will be wrong if it is missed.**

The rule "this agreement is meaningless" is encoded in `project_service._agreement_query`'s **join filters** — which require the project *and* the environment to be live — not in the agreement row's own `deleted_at`.

`delete_project` cascades a soft delete to its agreements. **`delete_environment` does not.** So a soft-deleted environment leaves `usage_agreement` rows with `deleted_at IS NULL` pointing at it: invisible to both A1 list endpoints, and fully visible to a naive enforcement query.

A3's predicate must therefore filter **all three** — the agreement, its project, and its environment — exactly as `_agreement_query` does. A check written as `SELECT ... FROM usage_agreement WHERE deleted_at IS NULL` would honour agreements for dead environments and for projects archived before A2's cascade shipped.

The reverse rule also holds and is easy to conflate: `get_project` and `get_group` filter `deleted_at` because they validate a **write**, while `get_project_names` and `get_environment_names` deliberately do **not**, because they render a name on a row that legitimately references an archived thing. A3 does neither — it evaluates a **rule**, and a rule must not fire on a dead counterparty.

### Windows: warn only if *no* agreement covers the booking

A1 made overlapping windows legal and refuses only an exact duplicate, so "which agreement applies" is ambiguous by construction. A3 resolves that ambiguity in the only direction that does not manufacture false warnings: **a booking is covered if any single live agreement covers it.**

A null `starts_at` or `ends_at` means "no bound", not "unknown" — an agreement with both null covers everything.

Out-of-window and no-agreement produce the **same severity** with different wording. Splitting them into two severities would double the states the UI and the report must express, for a distinction nobody has yet asked to act on differently.

## How the warning works: computed, with only the acknowledgement stored

This mirrors the conflicts mechanism already in the codebase, which is the closest existing analogue and the right shape:

- **Conflicts** are computed live by an overlap query; only `BookingConflictAck` rows are stored; `has_unacknowledged_conflicts` is derived by comparing the two.
- **Agreement gaps** are computed live; only `usage_agreement_ack` rows are stored; `has_unacknowledged_agreement_gap` is derived the same way.

**Why the split matters more than it looks.** Because the warning is derived rather than persisted, adding the missing agreement makes it disappear on its own — nothing to backfill, nothing to invalidate, and no stored flag that can drift from the `usage_agreement` table. A stored warning would be a second source of truth about a question that table already answers, and this codebase has been bitten by exactly that: A1 shipped a count and a list, written three tasks apart, that disagreed two ways with zero coverage.

```
usage_agreement_ack
  id, tenant_id
  booking_id       FK → booking.id
  notes            TEXT NULL
  acknowledged_by  FK → user.id
  acknowledged_at  TIMESTAMP
```

Keyed on `booking_id` alone — unlike a conflict, which is pairwise, a gap is a property of one booking.

### An accepted wrinkle

An acknowledgement is keyed by booking, but a booking's dates are editable through `PATCH /bookings/{id}/standard-fields`. Acknowledge "outside the agreed window", move the dates, and the stale ack suppresses a warning it was never given for.

**This is accepted, not overlooked.** Conflicts have the same property — their ack is keyed by the other booking, and dates move there too. Building ack-invalidation would add a state machine nobody has asked for. Recorded here so a future reader knows it was a decision.

## API

```
POST /booking-requests          → { request, detected_conflicts, agreement_gaps }
PUT  /bookings/{id}/agreement-gap/ack     { notes }
GET  /bookings?agreement_gap=true
```

`agreement_gaps` sits beside `detected_conflicts` in the existing create envelope — same shape, same moment, so the booker learns where they can act. The ack endpoint mirrors `PUT /{booking_id}/conflicts/{other_id}/ack`.

### The filter is the constraint that shapes the implementation

`GET /bookings` is bounded and paged, and this codebase's rule is that **every filter runs in SQL**: a Python-side filter windows the page *before* filtering and quietly returns wrong rows.

So the gap check must be expressible as a **SQL predicate** — a correlated `NOT EXISTS` over `usage_agreement` with window overlap — not merely as a Python function.

**Write the SQL form first and derive the per-booking answer from it.** Writing the Python version first and discovering later that it cannot be pushed down is how `dependency-alerts` ended up permanently unbounded: a second filter with no portable SQL form, so a page would window the pre-filter set.

## Frontend

- **Booking form** surfaces gaps on create alongside conflicts.
- **Booking detail** shows the gap, an acknowledge control, and — once acknowledged — who and when.
- **`BookingList`** gets a gap chip and the `agreement_gap` filter. Its "no selection" state spells `any`, never `all`: `buildParams` drops a filter valued `all`, so both states build byte-identical params and the grid never refetches.
- **Project detail** already lists agreements; a count of that project's bookings currently in gap belongs beside them.

Components read a rejected thunk's reason from `result.payload`, never `result.error.message`. A component calling a service **directly** must call `formatApiError` itself in its own catch — there is no `miniSerializeError` boundary on that path, and no type or lint rule enforces it.

## Testing

Both engines. The properties worth pinning beyond ordinary CRUD:

- **A booking with no project is never warned**, whatever the agreements say.
- **A booking covered by an agreement is not warned**; one outside every window is, with the window in the message.
- **Overlapping agreements**: covered by one and not another → **not** warned.
- **Null bounds** mean unbounded, in both directions and both together.
- **Adding the missing agreement clears the warning with no other action** — the property the computed-not-stored design exists to give.
- **An agreement whose environment was soft-deleted does NOT count as coverage**, and neither does one whose project was. Seed the environment case by soft-deleting the environment directly, **not** via a project delete — `delete_project` cascades and would hide the row a second way, masking exactly the predicate under test. That masking shape appeared three times on A2.
- **The SQL filter and the per-booking answer agree**, over a set including covered, uncovered, out-of-window and no-project bookings. This is the count-vs-list divergence A1 shipped; assert them against each other rather than separately.
- **`X-Total-Count` moves with the filter** — proving it filtered in SQL rather than in Python after the page.
- **A1's `test_an_agreement_changes_no_booking_behaviour` still passes.**
- Tenant isolation on every new path, on create and on ack. The same missing filter has appeared twelve times across the last five sub-projects.

Each rule gets a test proved by **mutation** — break it, watch a *named* test fail. Frontend tests must **re-render**, not only mount: two defects on A2 needed a second render to surface, and one needed unmocked child components.

## Scope

Roughly seven tasks: the prerequisite, the service and its SQL predicate, the ack table and endpoints, the list filter, then three frontend tasks and docs.

**Task 1 is a prerequisite, not a nicety.** `ENTITY_FIELD_SPECS["booking"]["valid"]` omits `project_id`, and so does `EditStandardFieldsDialog`'s fieldMap, so a booking's project is **create-only** — a mislinked booking can be fixed only by deleting and recreating it. Warning on a field nobody can correct is the failure mode this project has fixed repeatedly. Nothing else in A3 is safe to build until it lands.

### Not in A3

- **Priority-ordered contention, escalation, response windows** — A4.
- **Any change to `usage_agreement`** — A1 shipped it whole so A3 would own only the check.
- **The "cooperation rules" of §2.12.** The roadmap line assigns them to A3, but §2.12's cooperation content *is* priority-ordered contention and escalation, which is A4's line almost word for word. A3's scope is read as the check and its surfaces; **that roadmap line should be corrected when A3 ships.**

## Open questions for A4

- **`get_project` does not check `is_active`.** A project can be assigned via the API after being archived, so a gap warning can name an archived project. A1 flagged this; A2 hit the same asymmetry with `get_group`. A4 must decide whether an archived project contends at all.
- **Overlapping windows remain ambiguous** for any rule that needs to pick *one* agreement. A3 avoids the question by asking only "is it covered by any"; A4's priority ordering may not be able to.
