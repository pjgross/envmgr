# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-projects B1, B3a, B3b, A1 and A2 shipped (B3 complete) | Roadmap: [../plan.md](../plan.md)

Phase 7 is two independent programmes. Each sub-project gets its own spec, plan
and PR.

## A — Multi-Project Coordination

- [x] **A1** `Project` entity + team, `booking_request.project_id` and
      `release.owning_project_id` beside the existing free-text fields (not
      replacing them — `booking_request.project_name` stays and is relabelled
      "Purpose"), and the `usage_agreement` table, recorded but not enforced.
      A1's real surface is **one** existing field, not the four this line used
      to claim: `ReleaseChange.project_code`/`project_name` are **external**
      identifiers owned by Phase 3 Sub-3 (Jira, deferred), `release_kind =
      "project"` is a type discriminator ("project" as opposed to
      "enterprise"), and `release_membership.project_release_id` uses
      "project" as an adjective for a non-enterprise child release — none of
      the three is a reference to a project at all. See the spec's table.
      [Spec](../superpowers/specs/2026-08-06-project-entity-design.md)
- [x] **A2** `EnvironmentGroup` + booking a group as one unit — gives
      `Booking.environment_group_id` the FK it has lacked since the March
      booking migration
      [Spec](../superpowers/specs/2026-08-07-environment-group-design.md)
- [ ] **A3** Enforcement of the `usage_agreement` table A1 ships (project A may
      use environment E in window W) — `BookingService` checking agreements,
      plus the cooperation rules of [requirements.md
      §2.12](../requirements.md). A1 deliberately ships the schema whole,
      including its window, so A3 owns only the check and the rules, never the
      table. `usage_agreement` was untouched by A2 as well as A1 — a group
      booking creates one `Booking` per member the same way a hand-picked
      multi-environment booking does, so A3's per-environment enforcement
      needs no group-aware branch.
- [ ] **A4** Project-aware contention: priority-ordered resolution and
      escalation with a named owner + response window. Must decide whether
      contention resolves **per environment or per group** — A2's group
      bookings transition all-or-nothing, so a resolution that reassigns or
      bumps one member out from under a group booking leaves it no longer a
      group booking in any sense the UI or the atomic transition endpoint
      still honours.

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

## What A1 established

- **`project_name` stays, relabelled "Purpose"; it is not migrated or replaced.**
  `BookingRequest.project_name` is required free text, referenced in 67 places
  across the backend and 60 across the frontend, and in practice holds a
  booking label, not a project name — the dev tenant's own values include
  `test`, `Reserved check` and `booking 1`. Promoting it to an FK would either
  manufacture junk projects every tenant inherits permanently, or silently
  rewrite user-entered data. `project_id` arrives beside it instead, nullable,
  and the relabel is copy only — the API field name is unchanged.
- **`release.owning_project_id`, not `project_id`.** `release_kind="project"`
  already means something else on that row ("not an enterprise release"); two
  things called *project* on one row is how a future reader gets it wrong.
- **One environment, many projects, deliberately not a single owning FK.**
  Shared estates are the normal case, and §2.12 frames usage agreements as how
  projects "cooperate in a shared environment" — a one-to-many FK would have
  had to be unpicked by A3.
- **A1 ships the usage-agreement table complete, with its window, rather than
  a plain junction A3 would migrate later.** Building it whole cost nothing
  and left A3 as what it actually is: the check and the cooperation rules, not
  the schema.
- **No enforcement.** `BookingService` is untouched — a project may still book
  an environment it has no agreement for, nothing warns and nothing rejects.
  That is A3, with its own rules, deliberately kept out of the sub-project
  that introduces the schema — the same call B3a made with group membership.
- **Members come from `team_group_id` → the existing `UserGroup`, not a new
  `project_member` table.** `UserGroup` was deliberately generic, not called
  `OperationsTeam`, precisely so A1 could reuse it rather than build a second
  membership model — and membership still grants no permissions; every
  authorization rule stays role-based.
- **Deleting a project is always allowed**, unlike `delete_group`, which 409s
  while any environment references it. A group operates a handful of
  environments; a project accumulates every booking and release it ever had,
  so a reference check would make every project permanently undeletable the
  moment someone booked against it. It soft-deletes; existing references keep
  rendering the name, marked archived; `is_active = false` is what removes it
  from pickers going forward.
- **The project filter's "no selection" state is spelled `any`, never `all`.**
  `buildParams` drops a filter valued `all` as "no selection", so a literal
  `all` project filter would build byte-identical params to no filter at all
  and the grid would never refetch — the same hazard `ScopeWindowsTable`
  already had to dodge.
- **The environment-direction read (`GET /environments/{id}/usage-agreements`)
  shipped alongside the project-direction one from the start**, not added
  later as a client-side filter over a capped list. `EnvironmentProjectsPanel`
  on the environment detail page and `ProjectDetail`'s own agreements table
  both read live rows with the project/environment name already on them —
  neither resolves an id against a separately-fetched, capped collection.

## What A2 established

- **The atomic unit is `(booking_request_id, environment_group_id)`, not the
  group alone.** The same group can be booked on two different requests, and
  each pairing transitions independently — `_group_bookings` scopes every
  read and write to that pair, never to `environment_group_id` by itself.
- **Membership is frozen at booking time.** Booking a group expands it to one
  `Booking` per current member, each carrying `environment_group_id` as
  **provenance, not a live link** — nothing re-reads `environment_group_member`
  to resolve a booking's environments, before or after the booking exists.
  Adding or removing a member afterwards changes nothing about bookings
  already created; the group only expands again the next time it is booked.
  This is also why `usage_agreement` needed no group-aware branch: a group
  booking is, from that table's point of view, exactly the multi-environment
  booking it already knew how to check, one row per environment.
- **The per-booking transition endpoint (`POST /bookings/{booking_id}/transition`)
  stays open on a group member**, deliberately not superseded by the group
  endpoint. It is the repair tool for the one journey the design accepts:
  transition one member individually (an operations reality — a single
  environment can go down, or approve early, out of step with its group),
  then the group transition **refuses and names the divergent environment**
  rather than silently moving the rest. Fixing that one member back into step
  is what makes the subsequent group transition succeed.
- **Every failure is collected, not just the first.** `transition_group`
  validates every member before mutating any of them (all-or-nothing) and
  reports every member that cannot make the move in one response — an
  approver needs the whole picture, because repair is manual and per-member.
- **The group's allowed-transitions endpoint offers only the INTERSECTION**
  of what every member allows, not the union — offering a transition that
  only some members could take would show a button that always fails.
- **Booking two groups that share an environment is refused, and the refusal
  names both groups** — not just the environment, and not only the first
  group found.
- **`usage_agreement` was deliberately untouched.** A2 does not check it, does
  not read it, and does not gate group creation or group booking on it — A3
  still owns the entire check and its cooperation rules, exactly as A1 left
  them for A3.

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
