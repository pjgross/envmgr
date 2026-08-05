# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-projects B1 and B3a shipped | Roadmap: [../plan.md](../plan.md)

Phase 7 is two independent programmes. Each sub-project gets its own spec, plan
and PR.

## A — Multi-Project Coordination

- [ ] **A1** `Project` entity + members; promote the free-text
      `BookingRequest.project_name` to an FK (the concept also leaks as
      `ReleaseChange.project_code`/`project_name`, `release_kind="project"` and
      `release_membership.project_release_id`)
- [ ] **A2** `EnvironmentGroup` + booking a group as one unit — gives
      `Booking.environment_group_id` the FK it has lacked since the March
      booking migration
- [ ] **A3** `UsageAgreement` (project A may use environment E in window W),
      checked by `BookingService`
- [ ] **A4** Project-aware contention: priority-ordered resolution and
      escalation with a named owner + response window

A1 gates A3 and A4.

## B — Environment Lifecycle & Governance ([requirements.md §2.12](../requirements.md))

- [x] **B1** Governance fields — tier, Reserved, named owner, expiry.
      [Spec](../superpowers/specs/2026-08-04-environment-governance-fields-design.md)
- [ ] **B2** Naming & tagging conventions + untagged quarantine after a grace period
- **B3** Environment Request Form + auto-generated Welcome Pack, split in two:
  - [x] **B3a** A generic `UserGroup` with membership, `environment.operations_group_id`,
        and the admin + environment UI for both. No request form, no routing, no Welcome
        Pack — it ships no user-visible workflow by itself, only the admin screens and the
        field the rest of B3 needs.
        [Spec](../superpowers/specs/2026-08-04-user-groups-design.md)
  - [ ] **B3b** The Environment Request Form, routed to the operating team via B3a's
        membership, its approval flow, and the Welcome Pack generated at handoff. This is
        where the requirement "an environment must have an operating team" actually gets
        enforced — B3a leaves `operations_group_id` nullable everywhere.
- [ ] **B4** Soft (preemptible) vs hard (protected) reservations + time-slot bookings
- [ ] **B5** Decommissioning workflow + idle auto-detection (ghost environments)
- [ ] **B6** Forward contention as a calendar leading indicator

B1 gates B2, B3 and B5. B3a gates B3b.

## What B1 established

- **Tier is a tenant-configurable table** (`environment_tier`), not an enum, and
  it *replaced* the free-text `environment_type` rather than sitting beside it.
  Each tenant's distinct values were folded onto the eight standard tiers
  case-insensitively; unrecognised values survive as tenant-specific tiers with
  a NULL `category`.
- **Reserved is derived, not stored.** An environment that is reserved is still
  active, so it is a second axis computed as a SQL `EXISTS` over live bookings —
  never an `EnvironmentStatus` value.
- **No `idle` field ships until B5.** A field reading "not idle" when it means
  "never checked" is the failure the drift work had to fix.
- **Owner is required by the API; expiry is required only on create.** During
  implementation the product owner decided that a null `expires_at` means "no
  expiry planned" — a legitimate state, not a missing value — so a null expiry
  never blocks a patch. `POST /environments` is unchanged and still requires
  both. Legacy rows keep a null owner rather than a fabricated one; the
  spreadsheet import is a different case — it sets the owner to the importing
  admin (present, acting, identifiable) and leaves the expiry null.
  (`PATCH`'s compliance rule and `governance_gap` keying on owner alone was
  true only until B3a — see below.)
- The migration's branch for a NULL `environment_type` is defensive, not a fix
  for an observed bug: the column has been `VARCHAR(100) NOT NULL` since its
  original migration and was never altered, so the state it guards against was
  never reachable.
- `{draft, rejected, closed}` — "not a live claim on an environment" — now lives
  once, in `app/core/booking_states.py`. `conflict_service.TERMINAL_STATES` is
  deliberately different and must not be merged into it.

## What B3a established

- **`PATCH`'s compliance rule and `governance_gap` now key on owner OR operations
  group** — either one missing is a gap, not owner alone as B1 shipped it. The
  `PATCH` compliance rule still requires only an **owner**, unchanged from B1: a
  null `operations_group_id` never blocks a patch, the same way a null
  `expires_at` doesn't. `POST /environments` does not require an operations
  group either — it stays optional everywhere in B3a; B3b is where a *request*
  for an environment with no operating team gets refused.
- **A soft-deleted group is accepted when it equals what the environment
  already stores, rejected as a new assignment.** This mirrors `owner_user_id`,
  which likewise never checks `is_active` — an environment can legitimately
  keep pointing at a retired owner, and the UI keeps a soft-deleted group (or a
  deactivated owner) selectable with a "(deleted)"/"(inactive)" label for the
  same reason. Re-submitting an edit form's unchanged value must not 404 a save
  of an unrelated field just because the group was retired since the form
  loaded.
- **Read is open to any tenant member, write is Admin-only** — the same split
  `/tenant/users/lite` uses. B3b needs every user to be able to see which team
  operates an environment; that is not admin-only information. Group CRUD and
  membership changes stay Admin-gated.
- **Soft delete on the group, hard delete on membership** — this repo's usual
  convention. A deleted group is still referenced by `environment.operations_group_id`
  and (later) by B3b's historical requests, so it must survive as a row; a
  membership row is a junction and accumulates no value once removed.
- **No role within a group, and group membership grants no permissions.** Every
  authorization rule stays role-based; B3b introduces the first behaviour that
  reads membership at all (which requests an ops-team member sees).
