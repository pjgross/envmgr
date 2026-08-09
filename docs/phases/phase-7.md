# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-projects B1, B3a, B3b, A1, A2, A3 and A4 shipped (B3 complete, **programme A complete**) | Roadmap: [../plan.md](../plan.md)

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
      only the check and the rules, never the table's shape. A3's one change to
      it is an additive **index** on `(project_id, environment_id)` (revision
      `agreementidx`), supporting the coverage `NOT EXISTS`: no column, no
      constraint, no semantic change. (This line read "and did not touch it"
      until the whole-branch review — self-contradictory phrasing, since the
      index is disclosed in *What A3 established* below, not a hidden change.)
      `usage_agreement` was untouched by A2 as well as A1 — a group booking
      creates one `Booking` per member the same way a hand-picked
      multi-environment booking does, so A3's per-environment check needs no
      group-aware branch.
      [Spec](../superpowers/specs/2026-08-07-usage-agreement-enforcement-design.md)
- [x] **A4** Project-aware contention: `project.priority_rank` (nullable,
      **lower wins**), a verdict computed per conflicting pair, and a
      `contention_escalation` record naming an owner and a response deadline —
      this, not A3, is what [requirements.md §2.12](../requirements.md)'s
      contention bullet asks for. **A4 advises; it never acts** — no booking is
      transitioned, rejected or rescheduled, on detection, on a decision or on
      expiry.
      This line used to say A4 "must decide whether contention resolves **per
      environment or per group**", because A2's group bookings transition
      all-or-nothing and a resolution that reassigned or bumped one member out
      from under a group booking would leave it no longer a group booking in
      any sense the UI or the atomic transition endpoint still honours. **The
      question is dissolved rather than answered, and the history is kept here
      because the reasoning still holds**: an advisory verdict cannot tear a
      group apart, so there is no per-environment-versus-per-group resolution
      to choose between. Where a decision names a booking that belongs to a
      group, the owning team acts on it through the existing atomic transition
      endpoint and moves the whole group themselves; A4 never reaches inside
      one. The removal hole that same reasoning exposes —
      `DELETE /booking-requests/{id}/environments/{booking_id}` silently
      shrinking an atomic group booking — is a pre-existing **A2** defect and is
      now [issue #8](https://github.com/pjgross/envmgr/issues/8), deliberately
      not folded into the sub-project defined by not mutating bookings.
      [Spec](../superpowers/specs/2026-08-08-project-contention-design.md)

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
  **(Superseded by A3, below, on 2026-08-08: it now *warns* — `booking_service`
  applies the gap clause to its list query and both booking-shaped response
  types carry the warning. Nothing rejects, and that is still deliberate.)**
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
  owns the entire check and its cooperation rules, exactly as A1 left
  them for A3. **(Superseded by A3, below: the check shipped 2026-08-08, and a
  group booking needed no group-aware branch — it creates one `Booking` per
  member, each checked per environment like any other.)**

## What A3 established

- **A3 WARNS, IT NEVER BLOCKS — and that is a design decision, not an
  unfinished one.** No booking is refused, no transition is gated, no control
  is disabled. `booking_service`'s changes are confined to `list_bookings`: an
  `agreement_gap` parameter, the existing `BookingRequest` join widened to serve
  it as well as `project_id`, and a `WHERE` on the gap clause. **No create,
  update or transition path is touched** — which is the substantive claim, and
  the one this bullet used to over-compress into "only a `WHERE` clause". A1
  wrote `test_an_agreement_changes_no_booking_behaviour` precisely to
  detect this sub-project overstepping; it is still the single backend guard on
  the promise. **If it ever fails, A3 has started blocking.** The UI side of the
  same promise was untested until Task 6's review gated `TransitionButtons` on
  the gap and watched every test then in `src/pages/bookings` (50 at the time)
  pass anyway. **It is guarded on both sides now**: `describe('BookingDetail —
  A3 WARNS, IT NEVER BLOCKS')` in
  `frontend/src/pages/bookings/__tests__/bookingDetailAgreementGap.test.tsx`
  holds *"still renders the transition controls, enabled, with an
  UNACKNOWLEDGED gap on the page"* and *"…with an ACKNOWLEDGED gap on the
  page"*. Both supply a real allowed transition of their own, because the rest
  of that file stubs `getAllowedTransitions` to `[]` — and a page rendering no
  transition control at all cannot detect one being gated, which is exactly why
  the earlier mutation survived.
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
  **The count is status-blind and the page says so** — `gap_clause` never looks
  at `Booking.status`, so drafts and closed bookings count exactly as much as
  live ones, and "12 bookings in gap" would otherwise read as current exposure.

## What A4 established

- **A4 ADVISES; IT NEVER ACTS — and that, not a rule about groups, is what
  makes A2's group bookings a non-problem.** No booking is transitioned,
  rejected, rescheduled or bumped: not when a contention is detected, not when
  a decision is recorded, not when a deadline passes.
  `test_a_contention_changes_no_booking_behaviour`
  (`backend/tests/integration/test_contention_api.py`) is the guard, in the
  mould of A1's `test_an_agreement_changes_no_booking_behaviour`, with
  `test_recording_a_decision_changes_nothing_on_either_booking`
  (`backend/tests/test_contention_escalation.py`) pinning the decision path
  specifically. **If either fails, A4 has started acting.** The UI side is
  guarded by `describe('A4 advises; it never acts')` in
  `ContentionVerdict.test.tsx`, which asserts across four outcome/escalation
  shapes that the panel disables no button and contains no "cannot
  proceed"/"blocked"/"must be resolved" copy — A3's lesson, where the same
  promise went untested on the frontend until a mutation walked straight
  through it.
- **`project.priority_rank` is nullable, LOWER WINS, and unranked is a real
  state with no backfill.** Rank 1 outranks rank 2; `ge=1` refuses 0 and
  negatives, since a caller who guessed the direction should be refused rather
  than silently believed. **A ranked project deliberately does NOT beat an
  unranked one** — treating unranked as lowest would declare the entire
  existing estate the loser on the day this shipped, which is the shape B3a's
  governance-gap chip took when it flagged every environment. Project detail
  states the direction on both of its renderings — the field's helper text
  ("1 is highest. Leave empty for no rank.") and the read-only line for
  non-admins — because a bare integer whose direction a reader has to guess
  decides every contention backwards, confidently, with nothing to notice. The
  advisory alert above them says what a rank *does*, not which way it points.
- **The rank is set only by `PATCH /projects/{id}`.** `ProjectCreate` has no
  `priority_rank` field at all, so a project is always born unranked; the PATCH
  schema is `extra="forbid"` and keys on `model_fields_set`, so an omitted key
  means "leave alone" and only an **explicit null** unranks — the contract B1
  gave `expires_at` and A1 gave `team_group_id`.
- **The verdict is COMPUTED on every read, never stored.** It depends on two
  bookings *and* two project ranks, so four separate edits could falsify a
  cached one — a worse invalidation surface than A3's gap, which is computed
  for the same reason. Changing a rank, or linking a project-less request to a
  project, therefore takes effect on the next read with nothing to invalidate
  and no job to run.
- **Four outcomes, and THREE OF THEM HAVE NO WINNER.** `ranked` is the only one
  that names a booking; `no_project`, `unranked` and `equal_rank` each arrive
  with their own `reason` string, which the frontend renders verbatim rather
  than composing an explanation of its own. **Five reasons, not four**:
  `no_project` carries two, because "the request names no project" and "the
  request names a project this tenant cannot resolve" look identical to the
  verdict and completely different on screen — `get_project_names` deliberately
  does not filter `deleted_at` (A1's rule), so an archived project's **name**
  renders right beside a verdict saying its link cannot be resolved, and "not
  linked to a project" would read as a bug in the register.
- **`_ranks_for` takes the project id from the tenant-filtered LEFT JOIN, not
  from `BookingRequest.project_id`.** Reading it off the request reports a
  booking pointing at an archived or cross-tenant project as "has a project,
  and it is unranked" — so the verdict tells an admin to go and rank a project
  whose rank that same join then refuses to read, and they would set a rank and
  watch nothing change. Both sides of the pair must answer one question: is
  there a project *here*, live, in this tenant?
- **`contention_escalation` is the only thing A4 stores, and its STATE is
  computed too.** `open`, `answered` and `expired` follow from `respond_by` and
  `decided_at`, so there is no status column, **no background job and nothing
  to expire on a schedule**. `respond_by` is deliberately *not* required to be
  in the future — a deadline already passed reads as `expired` immediately,
  which is what an escalation raised about a clash already upon someone should
  say. Answering late is still `answered`: the branch order is the rule, and
  `state_predicate` reproduces it in SQL so the worklist filter and the rendered
  row cannot disagree.
- **One escalation per contention, keyed on the UNORDERED pair.** The pair is
  normalised (`min`, `max`) and backed by `uq_contention_pair`, so both owners
  escalating the same clash cannot create two records with two owners and two
  clocks. Re-asking returns the **existing record unchanged** — 200 rather than
  201 — and the caller-supplied `owner_user_id` and `respond_by` are ignored on
  that path, deliberately unlike the two acknowledgement upserts where the later
  answer wins: an escalation names *someone else* as the decider and starts a
  clock against them, so either party could otherwise restart the other's clock
  at will.
- **Escalating is the owner or a delegate of EITHER booking, or an Admin;
  answering is the NAMED OWNER, or an Admin.** Escalating is deliberately
  narrower than A3's ack (which any tenant member may record) because it starts
  a clock against a named person. **The Admin path on the answer is not a
  convenience** — A4 ships no edit and no withdraw path for an escalation
  (nothing anywhere sets `ContentionEscalation.deleted_at`; the column is
  filtered on read only), so a record naming the wrong owner, or one whose owner
  has since left, has exactly one way out: someone with authority answers it.
  B3b established that failure mode by shipping the opposite. Cross-tenant is
  **404, never 403**, on every route.
- **An escalation OUTLIVES its bookings**, and `bookings_live` is computed
  rather than stored. The worklist joins no bookings and filters on none —
  filtering by liveness would delete the audit trail from the only screen that
  shows it — and a dead pair is *annotated*, never dropped. "Live" is
  `conflict_service.TERMINAL_STATES` plus `deleted_at`, **not**
  `booking_states.INACTIVE_BOOKING_STATUSES`: that set counts a draft as
  inactive while `conflict_service` deliberately counts drafts *as* conflicts,
  so using it would mark dead a contention the conflicts page still shows.
- **`usernames_for` must NOT be tenant-qualified** — the same trap A3 recorded
  for `acknowledged_by_username`, now in batch form. Under master-admin
  impersonation `current_user.id` and `current_user.active_tenant_id` belong to
  different tenants, so `record_decision` legitimately writes a `decided_by`
  outside the escalation's own tenant; a `User.tenant_id == tenant_id` join
  renders that decider as **nobody**, and only under impersonation.
  `test_the_deciders_name_resolves_from_outside_the_escalations_tenant` fails
  with that join added.
- **Every name travels with the row** — the three usernames, both environments,
  both projects, both groups — resolved server-side in a fixed number of
  batched queries. The browser must not resolve them against the capped
  tenant-users or environments collections, where a name past the cap is
  information *lost*, not merely hidden. `booking_labels` resolves through the
  **read-rendering** lookups (`get_environment_names`, `get_project_names`,
  `get_group_names`), none of which filters `deleted_at`, while their
  write-validating siblings do — that asymmetry is A1's and A2's rule inherited
  deliberately, not an oversight to be tidied.
- **The group name is part of what identifies a booking, not decoration.** A2
  transitions a group booking atomically, so a decision naming one member is a
  decision about every member — a line reading "X on Staging gives way" about a
  five-environment group booking describes a consequence that will not happen.
  The note is rendered **per row**, only where that side actually has a group;
  a blanket page-level advisory fires on the majority of rows that have no
  group and tells the reader nothing about the one in front of them.
- **`GET /contention-escalations` filters `state` in SQL, and "everything" is
  spelled by OMITTING the parameter.** There is deliberately no `all` value on
  the wire and the URL spells it `any`: `buildParams` drops a filter valued
  `all` as its own no-selection sentinel, so both states would build
  byte-identical params and the grid would never refetch — the hazard
  `ScopeWindowsTable` and A1's project filter both had to dodge. One clock per
  request decides both the filter and every rendered state, so a page cannot
  select a row as open and render it expired.
- **The frontend's `canEscalate` is deliberately NARROWER than the server's
  rule.** `assert_may_escalate` also allows the owner or a delegate of the
  *other* booking, but nothing on `ConflictItem` says who that is and it is not
  worth a per-row lookup: that person sees the same contention, with the
  control, on their own booking's page. A button that 403s on click is worse
  than one that is absent.
- **A4 adds no `BookingList` column and no calendar surface.** Forward
  contention as a leading indicator is **B6**'s line; building one here would
  pre-empt it. The verdict renders in exactly two places — the Conflicts panel
  on a booking's page (`GET /bookings/{id}/conflicts`; the create dialog's
  `preview-conflicts` is untouched) and the Contention Escalations worklist.
- **The escalation owner is any user in the tenant, not a Release Manager.**
  §2.12's wording is "escalation to the Release Manager with a named owner +
  response window"; A4 implements the named owner and the window, and validates
  only that the owner exists in the caller's active tenant — there is no role
  check, and deliberately no `is_active` check either, matching
  `environment_service`'s FK validation (a contention already assigned to
  someone who has since left still names them). Recorded here as a knowing
  divergence, not an omission: the role that should arbitrate is a tenant
  policy question, and hard-coding one would make the feature unusable for
  tenants who arbitrate elsewhere.
- **Migration `contention` is additive** — one nullable column on `project`,
  one new table, no backfill, `down_revision = "relidx"`.

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
