# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-projects B1, B3a and B3b shipped (B3 complete) | Roadmap: [../plan.md](../plan.md)

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
  - [x] **B3b** The Environment Request Form, routed to the operating team via B3a's
        membership, its approval flow, and the Welcome Pack generated at handoff. It does
        **not** make an operating team mandatory — `operations_group_id` stays nullable and
        unenforced, same as B3a shipped it. What it enforces is narrower: an access request
        against a teamless environment cannot be *submitted*.
        [Spec](../superpowers/specs/2026-08-05-environment-request-form-design.md)
- [ ] **B4** Soft (preemptible) vs hard (protected) reservations + time-slot bookings
- [ ] **B5** Decommissioning workflow + idle auto-detection (ghost environments)
- [ ] **B6** Forward contention as a calendar leading indicator

B1 gates B2, B3 and B5. B3a gates B3b. B3b completes B3.

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

## What B3b established

- **The group gate applies to the transition's *target* state, not to every transition.**
  The spec's original design gated every transition on membership, which meant a Viewer
  raising an access request got 403 submitting their own draft — the requester is by
  definition not in the operating team, so the gate made the primary user journey
  impossible, and since the queue also excludes your own requests, a non-Admin's request
  could never even reach an approver. `APPROVAL_TARGET_STATES = {approved, rejected,
  fulfilled}` fixes this: submitting and cancelling need only the role gate the lifecycle
  template already controls, and only a move *into* one of those three states asks whether
  the actor is in the target environment's operating team (or is an Admin, who bypasses the
  group check but never the role check). The bug shipped past 29 green tests before review
  caught it, because every submission test in the suite happened to use an Admin — the one
  actor the gate doesn't apply to.
- **`validate_definition_for_entity` refuses an `environment_request` template that
  doesn't define `submitted`, `approved`, `rejected` and `fulfilled`, plus exactly one
  initial state.** The service keys on those four names in five places — routing,
  fulfilment, the welcome-pack gate, and `APPROVAL_TARGET_STATES` itself — so a tenant
  renaming one of them wouldn't get a smaller version of the feature, it would silently
  lose the group-gate check on a state the service no longer recognises as an approval
  target, or wedge every request in a status with no transition out. A tenant may still add
  states, add a second review step, and rewire transitions freely; only those four names are
  pinned. The *initial* state's name is deliberately not pinned — `create_request` reads it
  from the template's own `is_initial` flag rather than assuming `draft`.
- **Six handover fields on `Environment`, written through exactly one narrow endpoint.**
  `PATCH /environments/{id}/handover` accepts only `access_url`, `connection_notes`,
  `support_contact`, `sla_notes`, `known_limitations` and `decommission_notes` — never a
  widening of the Admin-gated `PATCH /environments/{id}`, which still controls tier, owner,
  status and the operations group itself. The fields are never added to `EnvironmentUpdate`,
  so there is exactly one write path and no second one to keep in step. Authorization on that
  one path is the operating team *or* an Admin — the second and last place in the application
  that reads group membership, alongside the transition gate above. Without it, only Admins
  could author the access URL, VPN route and support contact for every environment in the
  estate, and the predictable result is packs that stay empty.
- **Fulfilling a new-environment request creates the `Environment` with `status = INACTIVE`,
  never `ACTIVE`.** The register must not claim an environment is available before anyone
  has actually built it — that drift between the register and reality is what this product
  exists to prevent. An admin flips it active once the infrastructure exists. The six
  handover fields stay null on creation: there is nothing to hand over until it is built.
- **The Welcome Pack is a read model, rendered live on every request — never a stored
  snapshot.** A copy frozen at fulfilment would go stale the moment the operating team
  updates a VPN endpoint or support contact, and a confidently-stated stale connection
  detail is worse than no document at all. Every free-text field that hasn't been filled in
  renders as "Not provided", not a blank section — an empty "How to connect" heading reads
  as "there is nothing to do", the same absent-versus-checked-and-empty confusion the drift
  work already had to fix once.
