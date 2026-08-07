# Environment Groups and Atomic Group Bookings — Design

**Phase 7, sub-project A2.** Roadmap line: *"`EnvironmentGroup` + booking a group as one unit — gives `Booking.environment_group_id` the FK it has lacked since the March booking migration."*

## Problem

[requirements.md §2.1](../../requirements.md) says environments can be grouped ("Mortgage SIT + Customer SIT") and that an environment may belong to **multiple** groups. §2.2 says bookings are made "at the environment level or at the **environment group level** (books all member environments as one unit)".

Neither exists. What does exist:

- **`booking.environment_group_id`** — a nullable `Integer` added by the March booking migration (`20260323_1413_0d99256c6a56_add_booking.py`) with **no foreign key and no table to point at**. The model carries the comment `# no FK yet (Phase 7)`. It is the column's only reference in the entire backend: nothing reads it, nothing writes it, and every row in it is null.
- **Multi-environment bookings** — a `BookingRequest` already fans out to one `Booking` per environment via `environment_ids`, and `BulkBookEnvironmentsDialog` plus the guided multi-env flow already drive it.

So the fan-out is solved. What is missing is the **group** as a named thing, and **atomicity** — today every member `Booking` carries its own `status` and its own `POST /bookings/{id}/transition`, so members approve and reject independently. `rollup_status` merely *describes* the result (`all_approved`, `all_rejected`, `mixed`, `empty`).

A2 supplies both.

## What A2 is not

- **It does not touch `usage_agreement`.** A1 shipped that table whole — including its window — specifically so that A3 would own "only the check and the rules, never the table". A group agreement is expressed as agreements for the group's member environments; A3 checks each member environment as it already would. Reopening the table here would waste A1's central structural decision.
- **It adds no enforcement.** Nothing in A2 refuses a booking because of a usage agreement. That remains A3.
- **It stores no group status.** A group's state is derived from its members, the way `rollup_status` already derives a request's. A stored status would be a second source of truth free to disagree with the bookings it summarises.

## Data model

```
environment_group                     environment_group_member
  id, tenant_id                         id, tenant_id
  name         VARCHAR(200) NOT NULL    group_id        FK → environment_group.id
  description  TEXT NULL                environment_id  FK → environment.id
  is_active    BOOLEAN NOT NULL         deleted_at      TIMESTAMP NULL
  deleted_at   TIMESTAMP NULL
```

A **junction table**, because an environment can belong to multiple groups. Same shape as `usage_agreement`, which A1 shipped, and the same tenant-scoped-vocabulary shape as `Project` and `UserGroup`: soft delete, `is_active` to drop a group from pickers while existing references keep rendering its name, and **name uniqueness enforced in the service, not by a partial unique index** — a partial index is inert on SQLite, so half the suite would never exercise it. `environment_tier_service`, `user_group_service` and `project_service` all make the same call.

`booking.environment_group_id` finally gets its foreign key. **The migration adds the constraint and an index only** — no column, no backfill. Every existing value is null and no code path can produce a non-null one, so the constraint cannot fail on existing data.

### Two properties of `booking.environment_group_id` that will be misread

**It is provenance, not a live link.** Membership is frozen at booking time (see below), so the column records *which group this booking came from*. A booking's environments may legitimately differ from the group's current members. **Nothing may resolve a booking's environments by re-reading the group** — that would silently rewrite history the moment somebody edits a membership list.

**It is also the atomic-unit key, scoped to a request.** Bookings move together when they share `(booking_request_id, environment_group_id)`.

The request scope is not strictly load-bearing today: because an environment may appear only once on a request (below), a group cannot appear twice on one either, so its members are already unique within a request. The pair is used anyway because transitions are addressed per-request regardless, and because deriving a key's uniqueness from a *different* rule is fragile — relax the duplicate rule later and an unscoped group id silently starts conflating bookings.

## Decisions

### Atomicity: the group approves or rejects together

A transition applies to every member at once. You cannot approve three of five.

**The atomic unit is the group's members within one request.** Environments picked by hand on the same request keep transitioning independently, exactly as today. A request may hold both kinds side by side — which means two bookings on one request can behave differently, and the UI must make that visible rather than leaving it to be inferred.

### All-or-nothing, validated before anything mutates

An atomic transition cannot always apply to every member: members may sit in different states, and the lifecycle template's role and required-field checks may pass for some and not others.

**If any member would be refused, none move.** Validate every member first, then apply. Report **every** failure, not just the first — each naming the environment and the reason — because that is what makes the situation repairable. `403` if any refusal is role-based, `400` otherwise, matching `POST /bookings/{id}/transition`'s existing convention.

This is deliberate defence against the failure this codebase has produced twice: B3b shipped two separate states that no transition could leave, one of them asserted as correct by its own test. A half-transitioned group is exactly that shape.

### The per-booking transition endpoint stays open

`POST /bookings/{id}/transition` keeps its exact current meaning and is **not** forbidden for a booking carrying an `environment_group_id`.

The consequence is intended and must be designed around: **members can diverge**, after which a group transition refuses until someone repairs the odd one out, and whether repair is possible depends on the tenant's template offering a path back. Forbidding the individual endpoint would prevent divergence but would also remove the only repair tool, converting a recoverable mess into a stuck one.

Two mitigations, both required:

- The group transition's error names **which** environments are out of step and what state each is in.
- The UI shows members' states together, so divergence is visible rather than inferred.

### Membership is frozen at booking time

Adding or removing a group member never touches an existing booking. Bookings are real reservations against real environments; retroactively creating one because a list changed would reserve an environment nobody asked for, and retroactively cancelling one would release an environment somebody is using.

### An environment may appear only once on a request

Because an environment can belong to multiple groups, booking two overlapping groups would produce two bookings for the same environment — and that environment would belong to two atomic units at once, which `(request, group)` cannot express.

**Refuse the create**, naming the overlap: *"Mortgage SIT and Customer SIT both contain Perf; an environment can appear only once on a request."*

This extends a rule that already exists rather than inventing one: `create_request` already refuses with *"environment_ids must be unique"*, and `add_environment` with *"Environment already in request"*. The new check covers the two cases those miss — the same environment reached via two groups, and via a group and by hand. Silently deduping and picking a winner would make one group's approval quietly govern an environment the user believes belongs to the other.

### Two smaller rules the create path needs

**"At least one environment" now spans both fields.** `create_request` today refuses an empty `environment_ids`. With groups it must count the environments contributed by `environment_group_ids` too, or booking a group alone is rejected as empty.

**A group with no live members is refused by name.** Expanding it contributes nothing, so without an explicit check the caller gets either a silent partial request or *"At least one environment_id is required"* — neither of which says *"Mortgage SIT has no environments"*.

## API

```
GET    /environment-groups                          read: any tenant member
POST   /environment-groups                          write: Admin
GET    /environment-groups/{id}
PATCH  /environment-groups/{id}
DELETE /environment-groups/{id}                     soft delete
GET    /environment-groups/{id}/members
POST   /environment-groups/{id}/members             {environment_id}
DELETE /environment-groups/{id}/members/{member_id}
GET    /environments/{id}/groups                    which groups an environment is in

POST /booking-requests/{request_id}/groups/{group_id}/transition          {to_state, notes}
GET  /booking-requests/{request_id}/groups/{group_id}/allowed-transitions
```

`POST /booking-requests` gains `environment_group_ids: list[int] | None` beside `environment_ids`. The service expands each group to its **current live members**, creating one booking per member with `environment_group_id` set; hand-picked environments create bookings with it null.

**"Live member" means the membership row is not soft-deleted and the environment is not soft-deleted. It does *not* mean the environment is `active`.** An environment in `maintenance` or `inactive` still expands into a booking, because booking a future window on an environment that is currently down is legitimate and the existing per-environment path already allows it — `POST /booking-requests` performs no status check on `environment_ids` today. Silently dropping a member would be worse than either alternative: the user asked for a group and would get a partial one with no indication which environment was skipped or why.

**Reads are open to any tenant member; only writes are Admin.** Every booking form needs the group picker, so gating reads would break the primary journey — the mistake B3a shipped and a review had to catch.

**`allowed-transitions` for a group is the *intersection* across its members.** A transition not valid for every member must not be offered, or the UI shows a button that always 403s — precisely what all-or-nothing exists to prevent. It is the endpoint the UI's buttons come from, and B3b's review found the equivalent endpoint had shipped with zero tests, where dropping either gate survived a green suite.

All list endpoints take `pagination()`, order by a **unique** key, and emit `X-Total-Count`. Every filter runs in SQL. Cross-tenant ids are **404, never 403**, on create and on update.

### Events

Per-booking `BookingStateTransitioned` events, one per member, exactly as the per-booking path already publishes. No new group-level event: existing outbox consumers keep working unchanged, and nothing needs one yet.

## Frontend

- **`/tenant/environment-groups`** and **`/tenant/environment-groups/:id`**, following `Projects.tsx` and `UserGroups.tsx`: list with name, description, member count and status; detail with an environment picker to add and remove members.
- **Booking form** gains a Group picker beside the environment picker, sourced through a **`useAllEnvironmentGroups`** hook — `useSharedList`-backed, `is_active: true` — mirroring `useAllProjects`. A picker that reads a paged slice silently loses options past the cap; `useAllSystems` and `useAllProjects` both exist for this reason.
- **Booking request detail** groups member bookings visually under their group name, showing one set of transition controls for the group and each member's state beside it. This is where divergence becomes visible.
- **Environment detail** gains a "Member of" line listing the environment's groups. Without it there is no way to discover why an environment got booked.

Grid columns backed by a join or a computed value are **`sortable: false`** — `member_count` is a correlated subquery and can never be whitelisted for a server-side sort. Any new list filter spells its "no selection" state `any`, never `all`: `buildParams` drops a filter valued `all`, so both states build byte-identical params and the grid never refetches.

Components read a rejected thunk's reason from `result.payload`, never `result.error.message` — RTK's `miniSerializeError` drops `response.data.detail`. Tests reject with an **AxiosError shape**; a plain `Error` carrying the final text passes while the app is broken.

## Testing

Both engines, SQLite and PostgreSQL. The properties worth pinning, beyond ordinary CRUD:

- **A refused member blocks the whole group, and nothing moves.** Assert the other members' states are unchanged *and* that no `BookingStatusHistory` rows were written — a test asserting only the HTTP status would pass against a half-applied transition that then rolled back for an unrelated reason.
- **Every failure is reported, not just the first.**
- **`allowed-transitions` is the intersection.** A transition valid for three of four members must not appear.
- **Membership drift does not touch existing bookings** — add and remove a member, assert the booking's environments are unchanged.
- **Overlapping groups are refused at create**, with both group names in the message — and separately, the same environment reached via a group *and* by hand.
- **A group alone satisfies "at least one environment"**, and an empty group is refused by name.
- **An `inactive` or `maintenance` environment still expands into a booking** — it must not be silently dropped from the group.
- **Divergence is recoverable** — transition one member individually, assert the group transition refuses and names it, repair it, assert the group transition then succeeds.
- **A hand-picked environment on the same request is unaffected by a group transition.**
- Tenant isolation on every new FK write path, on **create and on update**. The same missing filter appeared eight times across A1 and the two sub-projects before it, and was never once caught by a pre-existing test.

Each rule gets a test proved by **mutation** — break the rule, watch a *named* test fail. On this branch's predecessors, every substantive defect was found that way and none by reading for plausibility.

## Deployment

The migration is additive: two tables, one foreign key and one index on an existing all-null column. No backfill, no data migration, no seed. Safe to apply before the code that uses it.

## Open questions for later sub-projects

- **A3** will check usage agreements per environment. A group booking is N bookings, so N checks — no group-aware branch is needed. But note the two states A1 left A3 to decide: `get_project` does not check `is_active`, and overlapping agreement windows are legal, so "which agreement applies" is ambiguous by construction.
- **A4** (priority contention) will need to decide whether contention is resolved per environment or per group. A group booking that loses only one member is no longer a group booking, which is the same atomicity question this spec answers for transitions.
