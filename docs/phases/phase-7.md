# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-project B1 shipped | Roadmap: [../plan.md](../plan.md)

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
- [ ] **B3** Environment Request Form + auto-generated Welcome Pack
- [ ] **B4** Soft (preemptible) vs hard (protected) reservations + time-slot bookings
- [ ] **B5** Decommissioning workflow + idle auto-detection (ghost environments)
- [ ] **B6** Forward contention as a calendar leading indicator

B1 gates B2, B3 and B5.

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
  expiry planned" — a legitimate state, not a missing value — so `PATCH`'s
  compliance rule and `governance_gap` both key on owner alone; a null expiry
  never blocks a patch. `POST /environments` is unchanged and still requires
  both. Legacy rows keep a null owner rather than a fabricated one; the
  spreadsheet import is a different case — it sets the owner to the importing
  admin (present, acting, identifiable) and leaves the expiry null.
- The migration's branch for a NULL `environment_type` is defensive, not a fix
  for an observed bug: the column has been `VARCHAR(100) NOT NULL` since its
  original migration and was never altered, so the state it guards against was
  never reachable.
- `{draft, rejected, closed}` — "not a live claim on an environment" — now lives
  once, in `app/core/booking_states.py`. `conflict_service.TERMINAL_STATES` is
  deliberately different and must not be merged into it.
