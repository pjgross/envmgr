# Phase 7 A4 — Project-aware contention: priority-ordered resolution and escalation

> Status: designed 2026-08-08. Implements [requirements.md §2.12](../../requirements.md)'s
> contention bullet: *"Priority-ordered contention resolution (configured priority order, not
> first-come-first-served); escalation to the Release Manager with a named owner + response
> window"*. Gated on A1 (`Project`), which is shipped.

## The one-sentence version

When two projects' bookings collide on an environment, A4 says **which project outranks the
other and why** — and lets a human be formally asked to decide, with a named owner and a
deadline. **It never moves a booking.**

## What A4 does not do, and why that is the design

**A4 ADVISES; IT NEVER ACTS.** No booking is transitioned, rejected, rescheduled or bumped —
not on detection, not on a decision, not on expiry. This is the same promise A3 makes about
usage-agreement warnings, and it is load-bearing here for a reason beyond consistency:

**it is what makes group bookings a non-problem.** A2's group bookings transition
all-or-nothing, and the phase doc flagged that a resolution which reassigns or bumps one member
"leaves it no longer a group booking in any sense the UI or the atomic transition endpoint still
honours". An advisory verdict cannot do that. Where a decision names a booking that belongs to a
group, yielding means the owning team moves **their whole group** through the existing atomic
endpoint themselves. A4 never reaches inside a group.

The guard is a named test, in the mould of A1's `test_an_agreement_changes_no_booking_behaviour`
— written specifically to catch a later sub-project overstepping. **If it ever fails, A4 has
started acting.**

Also explicitly out of scope:

- **Forward contention on the calendar** — that is **B6**'s line ("contention as a leading
  indicator, surface weeks out"). A4 adds no `BookingList` column and no calendar surface;
  building one would duplicate or pre-empt B6.
- **A second definition of "overlap"** — A4 rides on `conflict_service`'s existing conflict
  pairs. Issue #3 was created by exactly this kind of duplication, where a second copy of the
  conflict rule was invisible to the first copy's tests.
- **The group-member removal hole.** `DELETE /booking-requests/{id}/environments/{booking_id}`
  silently shrinks an atomic group booking. The phase doc assigned that decision to A4; the
  "never act" choice removes A4's need for it, and it is **raised as its own issue** rather than
  folded in. It is a pre-existing A2 atomicity defect, not a contention question, and putting a
  booking-mutating change inside the sub-project defined by not mutating bookings would weaken
  the guard above. *`docs/phases/phase-7.md`'s A4 line must be corrected to say so.*
- **Notifications.** The worklist is the surface. No email, no digest.
- **Any background job.** See "computed, not stored" below.

## Data model

### Stored: two things

**`project.priority_rank`** — nullable integer on A1's existing `Project`.

- **Lower wins.** Rank 1 outranks rank 2. The UI must label this explicitly; an integer whose
  direction a reader has to guess is a defect generator.
- **Null means UNRANKED, which is a real state, not a missing value.** Every project has it on
  first deploy — there is no backfill, deliberately.

**`contention_escalation`** — one new table.

| column | notes |
| --- | --- |
| `tenant_id` | FK, indexed |
| `booking_id`, `other_booking_id` | the pair, **normalised** so `booking_id < other_booking_id` |
| `escalated_by` | who asked. **When** is `Base`'s `created_at` — a separate `escalated_at` would be a second source for one fact |
| `owner_user_id` | the named owner who must decide |
| `respond_by` | the response window's deadline |
| `decision_yields_booking_id` | which booking should give way; null until answered |
| `decision_notes` | the reasoning |
| `decided_by`, `decided_at` | null until answered |
| `deleted_at` | soft delete, per house rule |

`UniqueConstraint(booking_id, other_booking_id)` — see "one escalation per contention".

### NOT stored: the verdict

Derived on read from the two requests' projects and their ranks. Nothing caches it, so changing
a rank, moving a booking, or setting a project on a previously project-less request all take
effect immediately **with nothing to invalidate**.

This is Approach A of three considered. Materialising contention rows would buy a cheap
estate-wide worklist and metrics, but a stored verdict depends on **two bookings and two project
ranks**, so four separate edits can falsify it — a worse invalidation surface than A3's gap,
which is already computed for the same reason. The metrics are recoverable from escalation
records, which *are* stored, and escalations are the interesting events rather than every
overlapping pair.

## The verdict

For a conflict pair, exactly one of four outcomes. **Three of them are "no winner".**

| outcome | when | winner |
| --- | --- | --- |
| `ranked` | both projects ranked, ranks differ | the lower rank |
| `no_project` | either booking's request names no project | none |
| `unranked` | both have projects, at least one has no rank | none |
| `equal_rank` | both ranked, ranks equal | none |

**A no-winner outcome is reported with its reason, never as a fabricated ordering.** On today's
data almost every pair is `no_project` — A1 shipped `project_id` nullable with no backfill — so
the honest answer is precisely what makes the unranked estate visible instead of hiding it
behind a spurious winner. This follows the drift-detection precedent, where absence categories
return **null with a reason, never `[]`**.

Two consequences, both deliberate:

- **A ranked project does NOT beat an unranked one.** Tempting, but it declares the entire
  existing estate the loser on first deploy — the shape B1's governance-gap chip took when it
  flagged every environment and looked exactly like a bug.
- **Two bookings from the same project never separate** (`equal_rank` by construction). Correct:
  A4 is *project*-aware contention, and intra-project scheduling is not a priority question.

## Escalation lifecycle

### One escalation per contention

A conflict is symmetric — (A,B) and (B,A) are one contention — so the pair is **normalised to
`(min, max)`** under a unique constraint. Without it, both owners escalating the same clash
produce two escalations with two owners and two clocks.

Creation goes through **`app/core/upsert.py::insert_or_reread`** (added by issue #6), so two
people escalating at once record one escalation instead of a 500.

### State is computed, not stored

- **answered** — a decision is recorded
- **expired** — `respond_by` has passed and no decision was recorded
- **open** — otherwise

No stored flag to drift, and **no background job**: "expired" is a fact about `respond_by` and
`decided_at`, not a state something must write. This mirrors
`agreement_gap_service.has_unacknowledged_agreement_gap`.

`respond_by` is set when escalating; the UI defaults it to **three working days ahead** and the
escalator may change it. It is required — an escalation with no deadline cannot expire, which
would quietly remove the half of §2.12 that makes escalation time-bound. **No new
tenant-configuration table** for the default: `POST /tenant/lifecycle-templates` already silently
drops unknown keys (a recorded, unfixed defect), so a setting reaching through it would be
unconfigurable in the product.

### Permissions

- **Escalating** — the owner or a delegate of either contending booking, or an Admin. Escalation
  creates an obligation for a named person, so it is not open to any passer-by. This matches
  `conflict_service._authorize_ack`, deliberately *unlike* A3's ack, which any tenant member may
  record because a gap is a finding rather than a request.
- **Answering** — the named owner, **or an Admin**. The Admin path is not a convenience: B3b
  established that gating solely on a person or a group leaves a workflow permanently stuck when
  that person leaves or the group is empty.

### Bookings that move on

An escalation whose bookings have since closed, been rejected or been deleted **keeps its
record** and is shown as no longer live. It is the trail of a decision that was asked for, which
is the reason to store it at all.

## API surface

**Extended:** `GET /bookings/{id}/conflicts` — each `ConflictItem` gains a `contention` object:
outcome, `winner_booking_id` (null on the three no-winner outcomes), reason, and the live
escalation or null.

Project ranks for the page come from **one batch lookup**, alongside the existing project-name,
gap and conflict batches. Three sub-projects have now added a field to this endpoint and every
one had to be batched; the per-row form is the thing that keeps being undone (issue #3).

**Corrected in task 6 — the pair's names travel on the response.** As first written, this
design asked the UI for a line reading "Mortgage Replatform outranks Payments Rebuild" from a
payload that carried no project name at all: `winner_booking_id` is an integer, and
`EnvBookingSummary.project_name` on the same item is `BookingRequest.project_name`, the free
text the UI labels "Purpose". The counterparty's project could only have been resolved per
row — the N+1 the paragraph above exists to forbid. So `ContentionRead` also carries
`booking_project_name` and `other_project_name` (keyed **as given**, subject then row), and
`EscalationRead` carries `booking_environment_name` / `booking_project_name` /
`other_booking_environment_name` / `other_booking_project_name` (keyed by the **stored,
normalised** pair, since a worklist reader is party to neither side). All resolved by one
batched `contention_service.booking_labels`, through `project_service.get_project_names` and
`environment_service.get_environment_names`.

Two properties of those two resolvers are load-bearing rather than inherited: **neither filters
`deleted_at`**, which is what puts an archived project's NAME beside a verdict saying its link
cannot be resolved — the only way `REASON_PROJECT_UNRESOLVABLE` is readable — and both are
tenant-qualified, so a request pointing at another tenant's project renders no name. Likewise
`booking_labels` does **not** filter `Booking.deleted_at`, deliberately unlike `bookings_live`
beside it: liveness says the contention has gone away, a label says which contention it *was*,
and an escalation outlives its bookings.

**New:**

| endpoint | purpose |
| --- | --- |
| `POST /bookings/{id}/contentions/{other_id}/escalate` | create; returns the existing escalation if one is live |
| `PUT /contention-escalations/{id}/decision` | record which booking yields, plus notes |
| `GET /contention-escalations` | the worklist — `pagination()` + `sorting()`, filtered by state and owner |

`priority_rank` is added to the project update path.

**Errors:** escalating a pair not actually in conflict is a **400** naming why; escalating one
that already has a live escalation returns the existing record rather than erroring; answering
as anyone but the owner or an Admin is **403**; cross-tenant is **404** throughout, never 403.

## UI surface

- **Project admin** — the rank field, labelled so the direction is unambiguous ("1 is highest").
- **Booking detail, conflicts panel** — a verdict line per conflict ("Mortgage Replatform
  outranks Payments Rebuild"; "Priority does not separate these — neither project is ranked"),
  and an Escalate control **next to the condition it acts on**, per A2's repair-panel lesson.
  Where the named booking belongs to a group, say so, so nobody reads it as "move this one
  booking".
- **Escalations worklist** — what a named owner opens to see what they must decide, with the
  response window and its state.

Entities render **by name**, never `#N`.

## Testing

Every rule verified by **removing it and watching a NAMED test fail**. Specifically:

- the four verdict outcomes asserted **against each other** over one mixed population, not
  separately — A1 shipped a count and a list, written three tasks apart, that disagreed two ways
- each no-winner outcome names its reason
- **tenant isolation assumed unguarded until a named test fails without it** — thirteen instances
  across six sub-projects, none caught by a pre-existing test
- the unordered pair: escalating from both directions yields **one** record
- the create race, via `insert_or_reread`
- expiry proved **with no job running**
- both permission gates, including the Admin fallback on answering
- **the never-acts guard**: a contention, an escalation and a decision change no booking's state,
  dates or lifecycle
- both engines; frontend tests **re-render** rather than only mounting, and failure paths reject
  with a real `AxiosError` shape, since a plain `Error` carrying the final text passes while the
  app is broken

## Open items this design creates

- `docs/phases/phase-7.md`'s A4 line claims A4 must decide per-environment-vs-per-group
  resolution. **"Never act" dissolves that**; the line needs correcting when A4 ships.
- The group-member removal hole gets its own issue (see *What A4 does not do*).
