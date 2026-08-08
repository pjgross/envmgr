# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-projects B1, B3a, B3b, A1, A2 and A3 shipped (B3 complete) | Roadmap: [../plan.md](../plan.md)

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
- [x] **A3** The `usage_agreement` table A1 ships, now **checked** (project A
      may use environment E in window W) — [requirements.md
      §2.3](../requirements.md), *"project-aware conflict detection checks
      whether projects have valid agreements before flagging"*. It **warns and
      never blocks**: no booking is refused, no transition is gated. This line
      used to cite "the cooperation rules of §2.12"; §2.12 has no cooperation
      rules — its nearest bullet is *priority-ordered contention resolution and
      escalation to the Release Manager with a named owner + response window*,
      which is **A4's** line almost word for word. Usage agreements are §2.3's
      subject, and A1's own "what it established" section quoted "cooperate in
      a shared environment" from there while crediting §2.12 too. A1
      deliberately ships the schema whole, including its window, so A3 owns
      only the check and the rules, never the table — and did not touch it.
      `usage_agreement` was untouched by A2 as well as A1 — a group booking
      creates one `Booking` per member the same way a hand-picked
      multi-environment booking does, so A3's per-environment check needs no
      group-aware branch.
      [Spec](../superpowers/specs/2026-08-07-usage-agreement-enforcement-design.md)
- [ ] **A4** Project-aware contention: priority-ordered resolution and
      escalation with a named owner + response window — this, not A3, is what
      [requirements.md §2.12](../requirements.md)'s contention bullet asks for.
      Must decide whether
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
  Shared estates are the normal case, and **§2.3** — not §2.12, which this
  bullet used to credit — frames usage agreements as how projects "cooperate in
  a shared environment"; a one-to-many FK would have had to be unpicked by A3.
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

## What A3 established

- **A3 WARNS, IT NEVER BLOCKS — and that is a design decision, not an
  unfinished one.** No booking is refused, no transition is gated, no control
  is disabled. `booking_service`'s only change is a `WHERE` clause on the list
  query. A1 wrote `test_an_agreement_changes_no_booking_behaviour` precisely to
  detect this sub-project overstepping; it is still the single backend guard on
  the promise. **If it ever fails, A3 has started blocking.** The UI side of the
  same promise was untested until Task 6's review gated `TransitionButtons` on
  the gap and watched all 50 booking-page tests pass anyway — a constraint the
  whole sub-project is named for, guarded on one side and nothing on the other.
- **The gap is COMPUTED on every read; only the acknowledgement is stored.**
  There is no `booking.in_gap` column and no cached verdict, so recording the
  missing agreement clears the warning with no other action, on the next read.
  `usage_agreement` itself was not modified — A1 pulled that table forward
  whole for exactly this reason. A3 adds one table (`usage_agreement_ack`,
  revision `agreementack`) and one index (`agreementidx`, on
  `usage_agreement (project_id, environment_id)`, supporting the filter's
  `NOT EXISTS`).
- **"Live agreement" is not `deleted_at IS NULL` on the agreement alone.** The
  project *and* the environment must be live too, exactly as A1's
  `_agreement_query` requires: `delete_project` cascades a soft delete to its
  agreements, **`delete_environment` does not**, so a soft-deleted environment
  leaves agreement rows with a null `deleted_at` pointing at it. Filtering only
  the agreement would honour agreements for dead environments.
- **Window bounds are INSTANTS, not calendar days, while the message renders
  days.** An agreement ending `2026-06-30T00:00:00Z` does not cover a booking
  ending at 17:00 that same day, and the warning says "until 30 Jun 2026". This
  is A1's stored shape carried through deliberately; a future task wanting
  day-granular inclusivity must change the comparison **and** the wording in one
  commit.
- **A booking whose request names no project is never in gap**, and
  `?agreement_gap=false` returns it. The two filter values partition the
  estate rather than leaving project-less bookings invisible to both — which is
  why the list column labels them "No gap" rather than "Covered": nothing
  assessed them, and "Covered" would be a claim about a check that never ran.
- **ACKNOWLEDGING IS NOT RESOLVING.** An acknowledged gap is still a gap:
  `?agreement_gap=true` still returns it, the indicator still shows (greyed,
  with a different accessible name), and only recording the agreement clears
  it. An indicator that vanished on acknowledgement would leave that filter
  rendering a page of blank cells.
- **A booking that is no longer in gap can still carry an
  `agreement_gap_ack`** — the field reports the ack ROW, and gating its presence
  on the computed gap would make one field's presence depend on two mechanisms.
  Consumers key on `agreement_gap`. Deliberate; **not a regression**.
- **`acknowledged_by_username` must NOT be resolved with a `User.tenant_id ==
  tenant_id` join.** Under master-admin impersonation `current_user.id` and
  `current_user.active_tenant_id` belong to different tenants, so
  `acknowledged_by` legitimately sits outside the ack's own tenant; qualifying
  the join renders that acknowledger as **nobody**, losing exactly the name the
  governance trail exists to hold, and only under impersonation. This is the
  shape a tidying pass "fixes" into a bug. It is pinned by
  `test_the_acknowledgers_name_resolves_from_outside_the_bookings_tenant` and
  spelled out in `agreement_gap_service.ack_author_username`'s docstring — the
  batch sibling `acknowledged_booking_ids` returns *ids*, not rows, for the same
  reason.
- **Anyone in the tenant may acknowledge; cross-tenant is 404.** Deliberately
  unlike `conflict_service`'s owner-or-delegate gate: a conflict ack is a
  message from one booker to another, a gap is a governance finding an admin or
  a project lead may reasonably accept. Acknowledging a *covered* booking is
  also accepted and simply changes no answer — refusing it would make the button
  a race against a gap that can close between render and click.
- **The warning is reported on other people's bookings within the tenant**
  (`preview-conflicts`, the conflicts list, received feedback). It leaks nothing
  new: `GET /projects` and `GET /projects/{id}/usage-agreements` are
  `get_current_user`-only by an explicit A1 decision, and `GET /bookings`
  already returns `project_id`/`project_name_link` for every booking in the
  tenant, so any member could compute the gap with two ordinary GETs.
- **`agreement_gap` is a FILTER, never a sort key.** `BOOKING_SORTS` whitelists
  `start_date`, `end_date` and `status` only, and an unknown `sort_by` is a 422
  rather than a silent fallback. The URL spells "no gap filter" **`any`, never
  `all`** — `buildParams` drops `all` as its own no-selection sentinel, and an
  empty `?agreement_gap=` is a 422 from FastAPI's `Optional[bool]`.
- **Never call `describe_gap` in a loop over a page** — it is
  `gaps_for_bookings` of one, so a 50-row page would issue ~150 queries. Every
  list builder uses the batch form; `has_unacknowledged_agreement_gap` (the
  plan-mandated single-booking interface) consequently has no production caller
  and says so in its docstring.
- **The booking→project link is editable.** A1's note ("create-only — fix it
  before A3") was half wrong and is now spent: `PATCH
  /booking-requests/{id}/standard-fields` already accepted `project_id`,
  gating on `STANDARD_REQUEST_FIELDS` rather than `ENTITY_FIELD_SPECS`; only the
  UI lacked the field. `EditStandardFieldsDialog` now exposes it, so a
  mislinked booking is corrected rather than recreated — which matters now that
  a mislink produces a visible warning. The field's edit gate is a **fallback**,
  not an override, so it disarms itself the day the backend starts emitting a
  permission for it.
- **Project detail carries a rollup**: how many of that project's bookings are
  currently in gap, linking to `/bookings/list?project_id=…&agreement_gap=true`.
  It is counted through `GET /bookings`' `X-Total-Count` with `limit=1` — **A3
  added no count endpoint** — so the number and the list the link lands on are
  one query and cannot disagree. A failed count renders "unavailable", never 0.

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
