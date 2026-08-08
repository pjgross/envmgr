# EnvManager - Claude Code Guide

> **Repo / remote (2026-08-04) — READ THIS FIRST, IT CHANGED**: `github.com/pjgross/envmgr` is now a **PUBLIC repository with rewritten history**, and it is **not the same repository** the older notes below refer to. The original private repo was renamed **`pjgross/envmgr_old`** (remote `old`) and still holds all 59 PRs and the unpurged history. The public repo was created fresh from a purged mirror, so **every commit hash before 2026-08-04 differs from the old repo's**, and the two share no common ancestor.
>
> Consequences that matter:
>
> - **Never force-push a branch derived from old history to `github`.** It would reintroduce material that was deliberately purged (see below). Normal `main` pushes are safe; the histories are unrelated so git rejects accidental mixing.
> - The local `origin` (GitLab, `localhost:8929`) **still holds the old history** and is the one place old objects remain reachable locally. Legacy/dev-only; leave it alone.
> - Licence is **Apache-2.0** (`LICENSE` + `NOTICE`). The README carries a work-in-progress status notice. Both `frontend/package.json` and `backend/pyproject.toml` declare `license = "Apache-2.0"`. Do not reintroduce the old "Proprietary — All rights reserved" wording.
>
>
>
> - Backups of the pre-purge history: `../envmgr-backup-20260804-180454.bundle` and `../envmgr-backup-docx-191629.bundle` (33 MB each).
> - **A history purge does not defeat GitHub PR refs.** `refs/pull/N/head` is permanent and public on a public repo, so purging `main` in a repo with PRs leaves the content fetchable. That is *why* publication used a fresh repo rather than a rewrite of the original. Remember this before ever purging again.
>
> Push and open PRs against **GitHub** (`gh` CLI, account `pjgross`). For where `main` actually is, run `git log -1 github/main` — **this file deliberately records no current tip SHA**, because a line naming HEAD is written by the very commit that changes HEAD and is therefore stale before it lands. (SHAs recorded *historically* below — "this programme ended at X" — are a different thing and stay accurate.)
> **Hardening programme (2026-07-30) — ✅ COMPLETE**, 11 PRs (#23–#33) merged to `main`, CI green on both engines; docs then realigned (#34) and superseded docs archived (#35) — tip `dbfa73a`. In order: migration-built databases were broken (6 tables missing `Base` timestamps) + a drift guard; unauthenticated `/auth/register` could mint an Admin in any tenant; **GitHub Actions CI** (there was none); **Dockerfiles + wired compose** (there was no deployable artifact); all dependency advisories cleared + audit gates; Neo4j and pika removed (never used); **dual-engine test suite + foreign key enforcement** (SQLite was ignoring FKs, 41 tests were inserting broken rows); structured logging, request ids, `/metrics`, supervised outbox publisher; frontend code splitting (3,445 kB → 180 kB entry); refresh-token sessions with revocation + login rate limiting; bounded list results.
>
> **Pagination programme (2026-07-30 → 2026-08-01) — ✅ COMPLETE.** Backend halves A/B/C1 (#36 `305c222`, #37 `cbd2974`, #38 `22b6a9b`) bounded 22 list endpoints, restructured 5 that filtered after execution, and added the whitelist-based `sorting()` primitive. The frontend half, **sub-project C3, converted all eleven list pages**: pilot `ReleaseList` (`0f89056`), prerequisites (**#41** `aaab293`), **#43** PR A deployments+builds (`b546ebe`), **#44** PR B bookings+change-requests+incidents (`5644dde`), **#45** PR C1 environments (`52b878c`), **#46** PR C2 infrastructure-components (`6466db4`), and PR C3 systems. **No list page fetches a capped page and filters it in the browser any more.** Two backend fixes came out of it: **#39** case-insensitive text sorting (`cb65fd5`) and **#42** a `DeploymentRead.event_id` schema mismatch that 500'd the whole deployments list (`448ac0f`). The seven rules the programme produced — the five grep forms a slice-consumer sweep must cover, pickers must not read a paged slice, bind text filters to the draft-aware value, check the sort whitelist per column, raw `DataGrid` needs `disableColumnFilter`, optimistic list surgery is wrong once a slice holds a page, and **open the page** — are in [docs/pagination.md](docs/pagination.md). **Six defects were found only by opening the page, every one with a fully green suite** (the last, a component-dependency tab that didn't refresh after a create, by the user). **`ScopeWindowsTable` — recorded twice as the twelfth grid this pattern could not convert — was converted after all**: nobody had read `scope_window.py`. "Actionable" is three comparisons (`actual_date IS NULL AND scope_deadline IS NOT NULL AND scope_deadline > :now`), not a `CASE` and a date diff, and sorting by `scope_deadline` *is* sorting by `days_to_cutoff` since one is monotonic in the other — which also dodges Python's `timedelta.days` flooring where both engines' date functions truncate. It shipped two shared additions: `useServerGrid.defaultSort` (first page whose default order differs from its endpoint's) and the finding that **a filter whose value vocabulary includes `all` collides with `buildParams`' "no selection" sentinel** — both toggle states built byte-identical params, so the grid never refetched. **`/releases/calendar`'s date range was never applied at all** — the endpoint declares `date_from`/`date_to`, the frontend sent `from`/`to`, and FastAPI drops unknown query params, so every month navigated to re-fetched the same unranged set (capped at 500, `created_at desc`); it looked right only because FullCalendar hides what falls outside the visible range. Fixed with the truncation: undated releases now filtered in SQL not Python, both endpoints on `pagination()` + `X-Total-Count`, and — a regression the fix itself introduced, caught by opening the page — calendar range matching is now interval **overlap** (`[target_date, COALESCE(actual_date, target_date)]`), since filtering on `target_date` alone blanks a month that a release merely spans. The `useAllX` hooks then got **in-flight request coalescing** (`useSharedList`): `/change-requests` renders its list, create form and edit dialog together, so it was issuing **eight** identical picker GETs per page load (four environments, four hosts — the note here said two); it now issues two. Deliberately **not** a cache — the map entry clears the moment the request settles, so a picker never serves a list from before the user created a row. A follow-on **client-side-filtering sweep** then covered the non-list pages the C3 rollout never looked at, and found the pattern is broader than filtering: `.find()` by id into a capped collection renders the entity as `—` (**information lost, not merely hidden** — a truncation banner cannot fix it), and `.length` yields a wrong count. Worst case was the tenant-wide `/tenant/users` collection (capped 500) feeding three consumers, one of which filtered it to active users so the option count bore no relation to the cap; RAID owner names now travel **with the row** (`owner_username`, as `ReleaseSystemRead` already does with `system_name`) rather than being resolved against it. Four lower-severity per-entity cases are recorded but not fixed in docs/pagination.md. Still open there too: the endpoints not yet bounded.
>
> **Phase 6 (Infrastructure Topology) — ✅ COMPLETE 2026-08-03.** The last sub-project, **drift detection**, shipped: `GET /systems/{id}/github/drift` plus a "Check drift" dialog on System detail, read-only — scan remains the only apply path. It compares repository IaC against the **subsystem catalogue**, not `.tfstate` against recorded state, because the phase doc's framing did not match the code: the IaC parsers write `SubSystem` rows, not `InfrastructureComponent` rows, and nothing anywhere sets `InfrastructureComponentSource.TERRAFORM` (still an unused enum value). So the available comparison needed no `.tfstate` and no new data source; `.tf`-vs-`.tfstate` stays out of scope for the reasons already recorded. It required splitting parsing from persistence — see the two new pitfalls below, and note the scanner now accumulates a detector's declarations across all its files and applies **once**, so two compose files no longer wipe each other's edges. Spec: [docs/superpowers/specs/2026-08-03-drift-detection-design.md](docs/superpowers/specs/2026-08-03-drift-detection-design.md). Historical note on how the phase doc read before this:
>
> **Phase 6 (Infrastructure Topology) — was 🟡 substantially shipped, and `docs/phases/phase-6.md` was two-thirds wrong.** Six of its thirteen unchecked tasks were already done (both IaC parsers with their System-detail UI, both topology endpoints, the React Flow canvas, the environment topology page, the GitHub repo field) and one — the Neo4j sync consumer — has been obsolete since Neo4j was removed in July. Corrected in place. **Sub-project 1, environment comparison, shipped 2026-08-03**: `GET /environments/compare?left=&right=` plus a page at `/environments/compare`, diffing presence (systems + subsystems), mocked-vs-real, deployed version and host shape. Two decisions carry into the rest of the phase — **host *shape* (`{component_type, role, count}`), never host identity**, because hostnames differ between environments by design and comparing them marks every subsystem different; and **the API is symmetric, with the reference environment applied only in the UI**, so one response serves both the triage and fidelity framings. **Two** sub-projects remain: drift detection and GitHub App/OAuth + repository scanning. (**env-topology SP4 was recorded here as outstanding and is in fact already shipped** — the System/Host toggle exists, is wired, and regroups the diagram; the claim that `setGroupBy` was dead code came from a case-sensitive grep that never matched it. Corrected 2026-08-03.) Spec: [docs/superpowers/specs/2026-08-03-environment-comparison-design.md](docs/superpowers/specs/2026-08-03-environment-comparison-design.md).
>
> **Sorting collates by byte value on every engine this app runs on**, which #39 fixed in the shared `apply_sort` by folding case explicitly. SQLite's default collation is `BINARY`, and the app's `postgres:15-alpine` uses **musl libc, which implements no locales** — the database reports `datcollate = en_US.utf8` while `SELECT 'a' < 'B'` is false. `docker-compose.prod.yml` only remaps ports, so **prod collated identically; this was never dev-only.** Do not "fix" ordering by changing the base image or the declared collation — keep it explicit in the query, as the NULL pinning already is. When testing a sort, assert **rendered row order over mixed-case data**: the pilot's assertions pinned the emitted SQL token and stayed green while the order users saw was wrong. Note the e2e suite runs in **no CI pipeline** and is only ever run by hand.
> **Phase 7 sub-project B1 (Environment governance fields) — ✅ COMPLETE 2026-08-04**, merged as `d4e6813` in the old repo (the public repo's history was rewritten afterwards, so that SHA exists only in `envmgr_old`). Phase 7 is **two programmes** and `docs/phases/phase-7.md` now describes both: **A** multi-project coordination (A1 `Project` + members, A2 `EnvironmentGroup`, A3 `UsageAgreement`, A4 priority contention) and **B** environment lifecycle & governance (B1 done; B2 naming/tagging + quarantine, B3 request form + welcome pack, B4 soft/hard reservations, B5 decommission + idle detection, B6 forward contention). A1 gates A3/A4; B1 gates B2/B3/B5.
>
> **Phase 7 sub-project B3a (User groups + environment operations group) — ✅ COMPLETE 2026-08-05**, merged as `b72684d7`. **B3 is now two sub-projects.** Brainstorming surfaced a requirement the roadmap line does not carry: the environment request is consumed by **operations teams, one per platform**, who need to see the requests they must action — so environments have to know which team operates them, and teams had to become a thing the system can hold. **B3a** shipped a generic `UserGroup` + `user_group_member`, `environment.operations_group_id`, and the admin and environment UI. **B3b** — the request form, routing to the operating team, approval and the Welcome Pack — is not started. Spec: [docs/superpowers/specs/2026-08-04-user-groups-design.md](docs/superpowers/specs/2026-08-04-user-groups-design.md).
>
> What B3a established, and what will bite if forgotten:
>
> - **`UserGroup` is deliberately generic, not an "OperationsTeam".** A1 is `Project` + members — also a container of users — and **must point at this primitive** rather than building a second membership model, or users are left asking which one to add someone to.
> - **Membership grants NO permissions.** Every authorization rule stays role-based; B3b introduces the first behaviour that reads membership. **Reads are open to any tenant member; only writes are Admin** — deliberately unlike `/tenant/users`, which really is admin-gated. An implementer over-gated the UI on exactly that false analogy and it took a review to catch.
> - **`?governance_gap=true` changed meaning**: missing owner **OR** missing operations group. On first deploy it therefore matches **every** existing environment (nullable, no backfill by design), so the relabelled "Governance gap" chip flags the whole estate until groups are assigned. Correct, documented in the admin guide, and looks exactly like a bug.
> - **An environment may keep a soft-deleted group**: validation accepts it when it equals the stored value and rejects it as a *new* assignment, mirroring the owner field, whose validation deliberately does not check `is_active`.
> - Group name uniqueness is enforced **in the service**, not by a partial unique index — inert on SQLite, same call as `environment_tier`.
> - **`tests/test_migration_schema_drift.py` compares only column NAME SETS** — not types, defaults or indexes. Four real drifts passed it on this branch, including naive-vs-timezone-aware timestamps that would have reached production. Its "N passed" is **not** evidence that a hand-written migration matches its model. Extending it is open work in its own right (it will surface pre-existing, deliberate divergence such as `uq_environment_tenant_name`, so it needs an allow-list).
>
> **Phase 7 sub-project A2 (Environment Groups + atomic group bookings) — ✅ COMPLETE 2026-08-07.** An `EnvironmentGroup` entity with a membership junction (an environment may belong to **multiple** groups); `POST /booking-requests` accepts `environment_group_ids` and the **server** expands each to its live members; and bookings sharing `(booking_request_id, environment_group_id)` transition **atomically**. Migration `envgroups` is additive — two tables, plus the foreign key `booking.environment_group_id` has lacked since the March booking migration. Spec: [docs/superpowers/specs/2026-08-07-environment-group-design.md](docs/superpowers/specs/2026-08-07-environment-group-design.md).
>
> What A2 established, and what will bite if forgotten:
>
> - **All-or-nothing.** If any member would be refused, **none move** — validated before anything mutates, with **every** failure reported, each naming the environment and its state. A half-transitioned group is the shape that produced two unrecoverable states on B3b.
> - **`POST /bookings/{id}/transition` stays open for group members — it is the only repair tool.** Members can diverge; a group transition then refuses until someone repairs the odd one out. **Forbidding it would convert a recoverable mess into a stuck one.** The final review found the UI had quietly removed that affordance across three tasks — the banner diagnosed divergence and offered no way to act on it. Repair controls now live in `GroupTransitionPanel`, next to the divergence they repair.
> - **Every member of a group booking shares ONE `BookingRequest`**, so `_record_values` is byte-identical across members and the only per-member input to `validate_transition` is `from_state`. Group reachability is therefore **exactly equal** to individual reachability, not merely a subset — which is *why* a diverged group ending in mixed terminal states is a legitimate end state and not a stuck one. **A4 must not split a group's members across requests, or that argument dies with it.**
> - **`allowed-transitions` for a group is the INTERSECTION** across members. Offer a union and the UI shows buttons that always 403.
> - **`environment_group_id` is PROVENANCE, NOT A LIVE LINK.** Membership is frozen at create, so a booking's environments may legitimately differ from the group's current members. **Nothing may resolve a booking's environments by re-reading the group.**
> - **`usage_agreement` was deliberately untouched**, so A3 still owns only the check and the rules — A1's reason for shipping that table whole.
> - **An environment may appear only once on a request** — refused for both "via two groups" and "via a group and by hand", naming the overlap. An empty group is refused **by name**.
> - **`get_group` (write validation) filters `deleted_at`; `get_group_names` and `get_environment_names` (read rendering) must NOT** — an archived group still renders its name on the bookings made against it. Three lookups, two opposed rules; a tidying pass will want to unify them.
> - **Removing one member of a group booking via `DELETE /booking-requests/{id}/environments/{booking_id}` silently shrinks the atomic unit.** Nothing refuses it and nothing documents it. A4 needs a rule — "bump one member out" is exactly that call.
> - **`POST /tenant/lifecycle-templates` silently drops `required_fields`** (Pydantic `extra='ignore'`), so the required-field half of `validate_transition` — which A2's group path depends on in three places — is unconfigurable through the product. Pre-existing, not A2's, deserves its own ticket.
>
> Two failure shapes this branch produced repeatedly, both invisible to reading the diff:
>
> - **Two mechanisms enforcing one outcome means one test cannot guard both.** Three instances, one *created* by fixing another: a cascade's test hid a join filter, fixing that let the join hide the cascade, and `delete_group`'s cascade 404ing first hid the membership `deleted_at` filter entirely — where the real exposure was that removing an environment from a group and re-booking it **booked the removed environment again**.
> - **A test that mocks the thing on the other side of a boundary stops testing the boundary.** Deleting the wiring between `BookingDetail` and its repair control left all 43 frontend tests green while the repair path regressed in full — both *ends* were tested, the *join* was not. Frontend tests that only ever mount also miss stale-effect and referential-identity bugs; two shipped on this branch and needed a second render to surface.
>
> **Phase 7 sub-project A1 (Project entity, members and usage agreements) — ✅ COMPLETE 2026-08-07**, merged as `32207b4b`. **Programme A is started.** A tenant-scoped `Project` whose team is an existing `UserGroup`, `UsageAgreement` rows recording which environments a project may use, and links from bookings (`booking_request.project_id`, surfaced on `BookingResponse` too) and releases (`release.owning_project_id`). Migration `projects` is additive — two tables, two nullable columns, no backfill. Spec: [docs/superpowers/specs/2026-08-06-project-entity-design.md](docs/superpowers/specs/2026-08-06-project-entity-design.md).
>
> What A1 established, and what will bite if forgotten:
>
> - **A1 RECORDS usage agreements and ENFORCES nothing.** No booking is refused, nothing warns, `booking_service` is untouched. Enforcement is A3. `test_an_agreement_changes_no_booking_behaviour` is the single guard on that promise, and was proved non-vacuous by inserting real enforcement into `create_request` and watching it fail. **If it ever starts failing, someone has added enforcement without the rules.**
> - **A project's members are `UserGroup`, not a new table.** B3a made that primitive deliberately generic for exactly this. There is one membership model and one admin screen.
> - **Two rules a tidying pass will want to "unify" and must not.** `get_project` (write validation) filters `deleted_at`; **`get_project_names` (read rendering) deliberately does not** — an archived project still renders its name on the rows that reference it, while a *new* assignment to it is refused. Likewise `_agreement_query`'s joins filter `deleted_at` while `_view_query`'s `UserGroup` join does not: there we ask whether a row whose counterparty is gone should appear at all, here we render the name of an archived thing on a live row.
> - **`owning_project_id`, not `project_id`, on `release`** — `release_kind='project'` already lives on that table meaning "not an enterprise release". And **`project_name_link`, not `project_name`, on the booking response** — that key is taken by the free text the UI now labels **"Purpose"**. `booking_request.project_name` is deliberately KEPT and never migrated: in real data it holds booking labels ("Health Demo Booking", "Reserved check"), so promoting it would manufacture junk projects.
> - **`delete_project` cascades a soft delete to its agreements; `delete_environment` does NOT.** So a soft-deleted environment leaves agreement rows with `deleted_at IS NULL` pointing at it — invisible to both list endpoints because the *join filters* hide them, but fully visible to a naive query. **A3 must not `SELECT ... FROM usage_agreement WHERE deleted_at IS NULL`.**
> - **Overlapping windows are legal; only an exact duplicate is refused.** So "which agreement applies" is ambiguous by construction, and a null bound means "no bound", not "unknown". A3 owns that decision.
> - **`get_project` does not check `is_active`.** A project can be assigned via the API after being archived; only the UI pickers filter it. `is_active` and `deleted_at` are two different retirement states.
> - **The booking→project link is correctable — and the "create-only" finding was half wrong.** ~~`EditStandardFieldsDialog`'s fieldMap and `ENTITY_FIELD_SPECS["booking"]` both omit `project_id`, so a mislinked booking can only be fixed by recreating it. Fix it before A3.~~ Checked against the code and the running app on the A3 branch: **`PATCH /booking-requests/{id}/standard-fields` already accepted `project_id`** — it gates on `STANDARD_REQUEST_FIELDS`, not `ENTITY_FIELD_SPECS` (which governs *lifecycle field permissions*, a system that endpoint does not consult yet: there is a `TODO permission gating` in `update_standard_fields`) — and already carried A1's archived-value carve-out. Only the **UI** lacked the field. `EditStandardFieldsDialog` now exposes it (`db862e5c`, `5a2b749f`), so a mislinked booking is corrected rather than recreated, which matters now that A3 makes a mislink visible. Do **not** "finish the job" by adding `project_id` to `ENTITY_FIELD_SPECS`: that would opt it into a permission system this endpoint ignores, changing nothing today and misleading the next reader. And note the dialog's edit gate for this field is a **fallback**, not an unconditional override — written that way so it disarms itself the day the backend starts emitting a real permission for it, rather than silently outranking one forever.
> - **A2 note:** `usage_agreement.environment_id` is a *single*-environment FK. Booking an `EnvironmentGroup` as one unit needs an agreement per member or a second nullable column — decide before A2 ships schema, since A1 pulled this table forward precisely to stop A3 migrating it.
>
> Four defect classes this branch re-proved, each found by mutation and never by reading:
>
> - **The missing `tenant_id` filter appeared EIGHT more times**, never once caught by a pre-existing test. Assume every tenant filter is unguarded until a named test fails without it.
> - **An FK validated on an update path 404s a full-form save once the referenced row is archived.** `environment_service` carries this rule in a comment naming the failure mode verbatim; A1 still shipped it on three separate paths. **Assume every FK validation on an update path has this bug.**
> - **Pydantic silently defaults a missing non-column attribute rather than raising**, so a response field renders `null` at four of five construction sites with the suite green. Both helpers now take the value **required-positional**, turning an omission into a `TypeError`.
> - **FastAPI drops unknown query params silently.** The Projects grid's Environments count linked to `/environments?project_id=` — a filter that does not exist — so it showed the entire estate as one project's environments, with a test *and* the admin guide asserting it as correct. Same failure as `/releases/calendar`'s long-broken date range.
>
> **Phase 7 sub-project B3b (Environment Request Form + Welcome Pack) — ✅ COMPLETE 2026-08-06**, merged as `61bc235e`. **B3 is done.** Two request modes on one entity — access to an existing environment, or a new one — routed to the operating team B3a introduced, on the existing lifecycle-template machinery. Plus six handover fields on `Environment` behind a narrow team-writable endpoint, and a Welcome Pack rendered live from them. Spec: [docs/superpowers/specs/2026-08-05-environment-request-form-design.md](docs/superpowers/specs/2026-08-05-environment-request-form-design.md).
>
> What B3b established, and what will bite if forgotten:
> - **The group gate applies to transitions whose TARGET is an approval state** (`APPROVAL_TARGET_STATES = {approved, rejected, fulfilled}`), not to every transition. Gating a requester's own submission on membership made the primary journey impossible — the person requesting access is by definition not in the operating team. This shipped broken and was caught only by tracing the workflow, not the diff.
> - **A `environment_request` lifecycle template that does not define `submitted`/`approved`/`rejected`/`fulfilled` plus exactly one initial state is REFUSED at save time.** The service keys on those four names in five places, and renaming `approved` made the group gate **silently stop applying** — a Test Manager in no group approved another team's request, HTTP 200. Tenants may still add states and rewire transitions; they may not rename these four. If you add a state literal to that service, add it to the validation rule too.
> - **Handover fields have their own endpoint** (`PATCH /environments/{id}/handover`) accepting exactly six keys, and are deliberately absent from `EnvironmentUpdate`. Its safety is the narrow schema, not the permission: `PATCH /environments/{id}` also edits tier, owner and the operating group, so widening *that* would let a team member change which team operates the environment.
> - **Group membership is read in exactly two places** — `environment_request_service.assert_may_transition` and `environment_service.assert_may_edit_handover`. They must stay in step: same tenant scoping, same Admin-or-master bypass, same degradation to Admin-only when a group is empty or absent.
> - **Fulfilment creates the environment `INACTIVE`**, governance fields populated by construction, handover fields null. The register must not claim an environment is available before it is built.
> - **The Welcome Pack is rendered live, stored nowhere**, and substitutes `"Not provided"` rather than hiding a section — an empty "How to connect" heading reads as "there is nothing to do".
> - An **access request still grants nothing technically**. Nothing scopes a user to an environment; it is a paperwork and audit trail, not a security control.
> - **Deploy note:** revision `envrequests` seeds the default request lifecycle for existing tenants. Applied anywhere in an earlier form, run `seed_environment_request_defaults_for_tenant` by hand or those tenants cannot raise requests at all (400).
> - **Two standing test-suite gaps found on the way, neither B3b's to fix:** `uq_environment_tenant_name` and its two siblings have **zero coverage on either engine** — both legs build schema with `create_all`, never `alembic upgrade head` — and `conftest.py`'s docstring implied otherwise (now corrected). And `realistic_client` shares the global `app.dependency_overrides[get_db]` with `client`, on which `auth_headers` depends, so a test requesting both silently gets the wrong override.
>
> What B1 established, and the decisions that will bite if forgotten:
>
> - **Tier is a tenant-configurable table** (`environment_tier`), not an enum, and it *replaced* `environment.environment_type`. Each tenant's distinct values were folded onto the eight standard tiers case-insensitively; unrecognised values survive as tenant-specific tiers with a NULL `category`.
> - **A null `expires_at` means "no expiry planned"** — a legitimate state, not a missing value. So `governance_gap` = **missing owner only**; the PATCH compliance rule requires an **owner only** (a null expiry must never block a save, or spreadsheet-imported rows freeze); `POST /environments` **still requires** an expiry; the import sets `owner_user_id` to the importing admin. `EnvironmentUpdate.expires_at` is typed `string | null`, not optional, because the backend keys on `model_fields_set` — an omitted key means "leave alone", so only an explicit null can clear an expiry.
> - **`reserved_now` is derived in SQL** (correlated EXISTS over live bookings, half-open `[start, end)`), never a stored status — an environment that is reserved is still active. **No `idle` field ships**; it arrives in B5 with its detection rules.
> - `{draft, rejected, closed}` now lives once, in `app/core/booking_states.py`. `conflict_service.TERMINAL_STATES` is deliberately different (it counts drafts *as* conflicts) — do not merge them.
>
> **Next**: **Phases 6 and the pagination programme are both complete** — this paragraph's former advice (choose between the C3 rollout and Phase 6) is spent, and the C3 rollout converted all eleven list pages long ago. The open work is now **Phase 7** (Multi-Project Coordination + Environment Lifecycle & Governance) per [docs/plan.md](docs/plan.md), or the smaller backlog below. Known open items: of **51** `GET .../response_model=list[...]` endpoints (reproducible count in [docs/pagination.md](docs/pagination.md)), **28** are bounded and **23** are not, after a follow-on pass restructured four of the six that used to be blocked on Python-side filtering/merging (`GET /{release_id}/raid` — `rag`/`overdue` into SQL; `GET /systems/{id}/dependencies` and `GET /subsystems/{id}/dependencies` — two concatenated queries into one `OR` query; `GET /environments/{id}/versions` — `current_only` dedup into a `ROW_NUMBER()` window; `GET /releases/{id}/dependency-alerts` — its N+1 became a join with `IS DISTINCT FROM`, but it stays **unbounded**: a second filter, `diff_days == 0`, drops rows after the query and has no portable SQL form, so a page would window the pre-filter set) plus `GET /releases/{id}/membership` (not in the 51 — it returns a dict; its `history` list is now bounded, `X-Total-Count` describes `history` only, not `current`+`history` combined). **"Blocked on a query restructure" now holds one endpoint** — `dependency-alerts`, for the reason above; the five cleared cases stay on record in docs/pagination.md rather than being deleted. Sub-project **C1** then added a whitelist-based `sorting()` primitive (sibling to `pagination()`, same 422-not-silent-fallback contract) to nine of the bounded endpoints, plus the filter parameters their grids needed (`search` on environments/systems, widened `search` on infrastructure-components, `environment_search`/`release_search` on deployments, `subsystem_search` on builds) — and bounded `GET /builds` itself in the process, its one deliberate behaviour change (a new `id` tiebreaker on an endpoint that had none). See docs/pagination.md's "What sub-project C3 must honour" for the sortable-column contract the frontend half (C3) depends on: which columns are permanently unsortable (computed post-query), the endpoint-wide `default_dir` hazard, and the enum name-vs-value storage gotcha. Of the remaining 24: **2** (`rollup/systems`, `rollup/members`, alongside 3 non-list aggregation endpoints) are permanently unbounded by design; **17** are bounded in practice by tenant configuration or by a single entity's own structure/history — neither needs action; the **5** genuinely growth-bearing ones — 3 inside the count plus 2 outside it that don't declare `response_model=list[...]` — **were all bounded on 2026-08-04**: `GET /releases/{id}/bookings`, `GET /releases/{id}/change-requests`, `GET /environments/{id}/deployments`, `GET /tenant/users/lite`, `GET /bookings/{id}/received-feedback`. Four needed a unique tiebreaker added. **`users/lite` took its own larger contract (default 1000, max 5000)**, not the shared 500/1000, because every consumer is a *picker* and a truncated picker loses users rather than shortening a page. Bounding it also exposed that **an `ORDER BY` which was merely cosmetic while unbounded becomes a data-selection rule the moment a `LIMIT` is attached** — byte-value collation meant every lowercase username would truncate before any capitalised one, so the query now folds case explicitly the way `apply_sort` does. The reproducible grep now returns **52**, not 51 (`/environment-tiers/` postdates the audit), and the remaining not-bounded set has **not** been re-enumerated against it — see docs/pagination.md, which now says so rather than implying the old numbers are current. `GET /releases/calendar` and `/releases/timeline` are now bounded via `pagination()` and emit `X-Total-Count` (and the calendar's long-broken date range works — see above). `GET /environments/{id}/health/history` is now wired to `pagination(default_limit=50, max_limit=500)` — its own contract, not the shared 500/1000 — which turned up an `ORDER BY recorded_at` with **no unique tiebreaker** (samples are machine-pushed with a caller-supplied timestamp, so ties are ordinary) and a `HealthDashboard` that derived its alert banner by filtering a capped, total-discarding fetch client-side. Note the tiebreaker has **no behavioural test**: removing it leaves paging green on both engines, so the guard is a structural assertion on the exposed `history_query()` — a deliberate, documented exception to the don't-assert-emitted-SQL rule. Still open: in the membership view, an accepted membership appears in both `current` and `history` (pre-existing, deliberately untouched — a semantic change, not a pagination one). The macmini host map has been moved out of the repo (it described a personal host); it now lives in `envmgr-infra-notes/macmini-host-map.md`. (**env-topology SP4 is shipped** — it was listed here as outstanding twice on the strength of a case-sensitive grep that never matched `setGroupBy`.)
>
> **First prod deploy after this**: signs everyone out once (old 24h tokens have no refresh token), requires `SECRET_KEY` + `POSTGRES_PASSWORD` (plus `SECRETS_ENCRYPTION_KEY` once GitHub is connected — lose it and every stored credential is unrecoverable), runs migrations `basetimestamps` + `authsessions` from the entrypoint, and the SP1/SP2 tenant backfill scripts remain a standing step. See [docs/dependency-audit.md](docs/dependency-audit.md), [docs/pagination.md](docs/pagination.md), [docs/decisions/](docs/decisions/) and §8/§9/§12/§13/§14 of the architecture reference.
> **Current Phase (2026-07-29)**: Everything merged + pushed to GitHub `main`. Phase 1 ✅ | Phase 2 ✅ | Phase 2.5 ✅ | Phase 3 Sub-1/Sub-2 ✅ (Sub-3 Jira deferred) | Phase 4 ✅ (incl. user/admin manual, `build_number` required, `GET /api/v1/webhooks/can-deploy` preflight, GitLab-CI dogfooding pipeline). **Phase 5 ✅ COMPLETE + in-app verified** — 5 sub-projects: SP1 Incident Tracking, SP2 DORA Metrics, SP3 Environment Health, SP4 PIR, SP5b Release/Booking-conflict metrics, SP5a Environment Operating Hours + Utilization (DST-correct, `zoneinfo`); latest migration `environment_operating_hours` (`7441806378e5`). Health-alert closed-booking bug fixed. **Release RAID log fully shipped + UI-verified** (backend + frontend + docs + enterprise rollup; migration `raidlogtables`). **UI audit done** — P1 fixes landed, P2/P3 backlog. Phase 5 follow-on: SP1/SP2 tenant backfill scripts are a standing **prod**-deploy step (dev confirmed clean). Next: per [docs/plan.md](docs/plan.md) / [docs/gap-analysis.md](docs/gap-analysis.md) (Phases 6–13).
> **Requirements**: [docs/requirements.md](docs/requirements.md)
> **App Architecture**: [docs/prod architecture.md](<docs/prod%20architecture.md>)
> **Infra (macmini)**: kept outside this repo — see `envmgr-infra-notes/macmini-host-map.md` alongside the checkout (removed when the repo went public; it mapped a personal host, not this project)
> **Roadmap**: [docs/plan.md](docs/plan.md) | **Phase 1 summary**: [docs/phases/phase-1.md](docs/phases/phase-1.md) | **Phase 2 summary**: [docs/phases/phase-2.md](docs/phases/phase-2.md) | **Phase 3 summary**: [docs/phases/phase-3.md](docs/phases/phase-3.md)
> **Gap analysis (2026-07-16)**: [docs/gap-analysis.md](docs/gap-analysis.md) — capability coverage vs the Release/Environment Management intro docs; added Phases 9–13 (Release Governance, Test Data Management, Cost/FinOps, Compliance/Audit, ITSM) + expanded Phases 6 & 7.
> **Admin Guide**: [docs/admin-guide.md](docs/admin-guide.md)
> **User Guide**: [docs/user-guide.md](docs/user-guide.md)
> **CI**: [.github/workflows/ci.yml](.github/workflows/ci.yml) — pytest on SQLite **and** PostgreSQL, lint, build, image builds, dependency audits. The GitLab pipeline ([docs/gitlab-ci-setup.md](docs/gitlab-ci-setup.md)) is deployment-tracking dogfooding, not the gate on `main`.
> **Dependency policy**: [docs/dependency-audit.md](docs/dependency-audit.md) | **Pagination**: [docs/pagination.md](docs/pagination.md) | **Decisions**: [docs/decisions/](docs/decisions/)
> **UI Audit (2026-07-22)**: [docs/ui-audit.md](docs/ui-audit.md) — ranked usability/consistency/a11y findings; P1 fixed, P2/P3 remain as backlog.

EnvManager is a multi-tenant test environment management platform: inventory, booking, change management, CI/CD tracking, DORA metrics, and infrastructure topology visualization.

Stack: FastAPI + PostgreSQL + Redis + **NATS** (backend) / React 18 + TypeScript + MUI + Redux Toolkit (frontend).

---

## Dev Environment

Runs fully containerised on **OrbStack** (macOS). `docker-compose up -d` starts all services locally; OrbStack provides DNS at `<service>.orb.local` for inter-container access.

```bash
# 1. Start infrastructure (PostgreSQL, Redis, NATS)
docker-compose up -d

# 2. Backend env (once) — DEBUG=true is what permits the repo's placeholder
#    SECRET_KEY; with DEBUG=false the app refuses to start without a real one
cd backend && cp .env.example .env

# 3. Run migrations
cd backend && alembic upgrade head

# 4. Backend (separate terminal)
cd backend && uvicorn app.main:app --reload

# 5. Frontend (separate terminal)
cd frontend && npm run dev
```

| Service      | Dev URL                       | Notes                           |
| ------------ | ----------------------------- | ------------------------------- |
| Frontend     | http://localhost:5173         | Vite dev server                 |
| Backend API  | http://localhost:8000         | FastAPI                         |
| API Docs     | http://localhost:8000/docs    | Swagger UI                      |
| NATS Monitor | http://localhost:8222         | Local NATS container            |
| Metrics      | http://localhost:8000/metrics | Prometheus exposition           |
| PostgreSQL   | localhost:5432                | Local Postgres container        |
| Redis        | localhost:6379                | Local Redis container           |
| Jira         | http://localhost:8090         | Dev/testing only — not in prod |
| GitLab       | http://localhost:8929         | Dev/testing only — not in prod |
| GitLab SSH   | localhost:2224                | Dev/testing only — not in prod |

Demo login: `admin` / `admin123` (tenant: `demo`)

Master admin login: `masteradmin` / `masteradmin123` (tenant: `system`)
Run once to seed: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_master_admin.py`

---

## Production Deployment

Production runs on **macmini** (Tailscale network). EnvManager's containers are deployed via docker-compose. Several infrastructure services are shared from the macmini host rather than duplicated.

```bash
SECRET_KEY=$(openssl rand -hex 32) POSTGRES_PASSWORD=... \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    --profile app up -d --build
```

- `backend` and `frontend` live under the compose **`app` profile** so the dev flow above (`docker-compose up -d` for infra, uvicorn + vite on the host) doesn't fight them for ports 8000/5173.
- `SECRET_KEY` and `POSTGRES_PASSWORD` are **required** — compose fails fast without them, and the backend refuses to start with `DEBUG=false` and the repo's placeholder key.
- **`SECRETS_ENCRYPTION_KEY`** is required once any tenant connects a third-party credential (today: GitHub). Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. It is **deliberately not `SECRET_KEY`** — that one signs JWTs, and the two have different blast radii and rotation schedules. **Losing this key makes every stored credential unrecoverable**: nothing can decrypt them, and every tenant must reconnect. Rows carry a `key_version` so a future rotation can re-encrypt in place.
- **`GITHUB_OAUTH_CLIENT_ID`** is optional. Absent, the GitHub integration endpoints answer 503 with a clear message and nothing else is affected. It is the client id of an OAuth App used for the device flow, which needs no client secret.
- The backend image's entrypoint runs `alembic upgrade head` **before** uvicorn. That order matters: `init_db()` calls `create_all`, so if the app started first it would build the schema itself and leave `alembic_version` empty, after which migrations fail on "relation already exists". Set `RUN_MIGRATIONS=0` to skip.
- The frontend image is nginx serving the built bundle and proxying `/api` to `BACKEND_ORIGIN` (`src/services/api.ts` uses a relative `/api/v1` baseURL, so whatever serves the bundle must also proxy the API).
- Port lists in `docker-compose.prod.yml` use `!override`; without it compose **appends** to the base list and republishes the base port too.

| Service     | Source                      | Prod connection                        |
| ----------- | --------------------------- | -------------------------------------- |
| PostgreSQL  | EnvManager docker-compose   | `localhost:5435` (own container)     |
| Redis       | EnvManager docker-compose   | `localhost:6379` (own container)     |
| NATS        | **Shared — macmini** | `nats://macmini:4222`                |
| Grafana     | **Shared — macmini** | `http://macmini:3003`                |
| Prometheus  | **Shared — macmini** | `http://macmini:9093`                |
| Backend API | EnvManager docker-compose   | `http://macmini:8100`                |
| Frontend    | EnvManager docker-compose   | `http://macmini:5173` (or via Caddy) |

**No graph database**: Neo4j was provisioned early but never used — topology is PostgreSQL-backed. Removed 2026-07-30, see [docs/decisions/2026-07-30-drop-neo4j.md](docs/decisions/2026-07-30-drop-neo4j.md). The macmini Neo4j instance is a shared host service for other projects and still runs; EnvManager just doesn't connect to it.

Prod architecture reference: the macmini host map is kept outside this repo (`envmgr-infra-notes/macmini-host-map.md`).

---

## Code Conventions

**Python**: PEP 8, type hints, async/await throughout. `snake_case` functions/vars, `PascalCase` classes.

**TypeScript**: Strict mode, explicit types, functional components. `camelCase` functions/vars, `PascalCase` components/types.

**Git**: Branch names like `feature/phase1-environment-crud`. Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`.

---

## Adding a New Feature (checklist)

1. `backend/app/db/models/<entity>.py` — SQLAlchemy model with `tenant_id`; all enum columns use `native_enum=False` (stores as VARCHAR — keeps SQLite test compat)
2. `alembic revision -m "..."` then write DDL **manually** — do NOT use `--autogenerate` (init_db uses create_all so autogenerate sees nothing to do for new tables); use `op.create_table()` for new tables, `op.add_column()` for new columns
3. `alembic upgrade head`
4. `backend/app/services/<entity>_service.py` — business logic, no HTTP code; use `db.flush()` not `db.commit()` when you need the DB to assign an ID mid-transaction
5. `backend/app/api/v1/<entities>.py` — thin endpoints, delegate to service
6. `frontend/src/services/<entity>Service.ts` — API client
7. `frontend/src/store/<entity>Slice.ts` — Redux slice with async thunks
8. `frontend/src/pages/<EntityList>.tsx` — page component using Redux

---

## Common Pitfalls

- **Business logic in API endpoints** — keep endpoints thin, put logic in services
- **Missing tenant_id filter** — every query on tenant-scoped tables must filter by `tenant_id`; use `current_user.active_tenant_id` (not `.tenant_id`) to handle impersonation correctly
- **API calls in React components** — use Redux async thunks + service layer instead
- **Synchronous DB operations** — always use `async/await` with `AsyncSession`
- **Hard deleting records** — use soft deletes (`deleted_at = datetime.now(timezone.utc)`); only dependency/junction records use hard delete
- **Skipping migrations** — always create an Alembic migration for schema changes; write manual DDL (see checklist above)
- **`db.commit()` in services** — `get_db()` auto-commits on success; calling `db.commit()` inside a service will break the outbox pattern (event rows must commit atomically with the business write). Use `db.flush()` if you need the DB to assign an ID mid-transaction
- **Native enums** — always set `native_enum=False` on enum columns; PostgreSQL native ENUMs break SQLite-based tests and are hard to alter later
- **`--autogenerate` migrations** — `init_db()` calls `create_all`, so Alembic autogenerate sees tables as already existing and generates empty migrations. Always use `alembic revision -m "..."` and write the DDL manually
- **Fabricating foreign keys in tests** — never point a test row at an id you haven't created (`subsystem_id=1`, `raised_by=1`). SQLite silently ignored FKs until `PRAGMA foreign_keys=ON` was added, so ~40 tests were inserting broken rows and passing. Use the helpers in `backend/tests/factories.py`
- **Testing only on SQLite** — the suite defaults to in-memory SQLite, but partial unique indexes and other dialect-gated DDL are inert there. Run it against PostgreSQL too before trusting a schema or query change: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` (CI runs both legs)
- **Secrets in code** — use environment variables and `.env` files. `SECRET_KEY` must be set for any `DEBUG=false` deployment; the app refuses to start with the repo's placeholder
- **Self-service user creation** — there is no `/auth/register`; create users via `POST /api/v1/tenant/users`, which is admin-gated and forces the caller's tenant
- **Unbounded list endpoints** — new list endpoints take `page: Page = Depends(pagination())` (it's a factory — call it) and their service returns `(rows, total)` via `fetch_page` for a single-entity select or `fetch_page_rows` for a multi-column one; see [docs/pagination.md](docs/pagination.md). Order by a **unique** key — append the primary key as a tiebreaker, or `LIMIT`/`OFFSET` will duplicate and drop rows across pages once ties exist. Never add `limit` to an endpoint whose service filters in Python after the query, or merges two executed queries — the page would be windowed before the filter and the results quietly wrong. If the endpoint also needs a `sort_by`/`sort_dir`, use `sorting()` (same file) the same way: it's a **whitelist** mapping client field names to ORM columns — `sort_by` is never used to address a column directly (no `getattr`, no interpolation) — and an unknown `sort_by` is a **422**, not a silent fallback. Chain `apply_sort` **before** the tiebreaker, never instead of it (`apply_sort(query, sort).order_by(Model.id)`), and never whitelist a column a service computes in Python after the query — it isn't backed by a single column to sort by
- **Trusting the database's collation for text order** — `apply_sort` folds case itself (`lower(col)`) for `String` columns rather than letting `ORDER BY name` mean whatever the engine decides. Both engines here collate by **byte value**: SQLite's default is `BINARY`, and `postgres:15-alpine` runs musl libc, which implements no locales — the DB reports `en_US.utf8` but `SELECT 'a' < 'B'` is false, in prod as well as dev. Don't "fix" ordering by changing the image or the declared collation; keep it explicit in the query, the same way NULLs are pinned. When testing a sort, assert **rendered row order over mixed-case data** — an assertion on the emitted SQL string will stay green while users see the wrong order
- **Minting tokens by hand** — `create_access_token` alone produces an unrevocable session. Use `auth_session_service.issue_session`; anything that invalidates a password must call `revoke_all_for_user`
- **Parsing that writes as it goes** — a scanner detector returns a `DeclaredState` value and touches no database. `reconcile.apply()` writes it, `reconcile.diff()` compares it, and both read the *same* value — which is what stops the drift report describing a change a scan would not make. `test_reconcile_roundtrip.py` asserts it (`apply` then `diff` == zero drift) and has already caught the two sides de-duplicating repeated edges in opposite directions. Truncate to column widths **in the parser, never in `apply()`** — otherwise a stored row differs from the declaration it came from and `diff()` reports a phantom change on every run. **SQLite does not enforce column widths at all**, so a dropped truncation fails only on the PostgreSQL leg
- **Treating a partial read as a complete one** — `GET /systems/{id}/github/drift` computes "in the catalogue but not in the code" only when the whole tree was read. A truncated tree, the file cap, an unread path or a fetch error each make an unread file indistinguishable from a deleted one, so the absence categories come back **`null` with a reason, never `[]`**, and the UI omits the group instead of rendering it empty. Watch this at *every* level: a summary computed from "categories that were computed" reads as a clean bill of health when in fact nothing could be checked — the drift dialog announced "the catalogue matches the code" directly above its own truncation warning until that was fixed
- **A new grid column whose `field` collides with a tenant custom-field key** — `buildCustomFieldColumns` used to emit `field: def.field_key`, so a tenant with a custom field keyed `owner` got two columns sharing one id the moment B1 added a static `owner` column. MUI then emitted a spurious visibility change that the page's own `saveColumnModel` persisted, **silently hiding the real column**. No test could catch it: no fixture defines a colliding custom field. Environment columns are namespaced `cf_<key>`; **`BookingList.tsx` and `SystemCatalog.tsx` were namespaced the same way on 2026-08-04**, each with a test asserting no custom-field column's `field` can collide with a static one and one asserting the valueGetter still reads the *raw* `field_key` (the namespace is a grid-column id only — a valueGetter that looked up `cf_x` would render a correctly-named, permanently-empty column). Note the fix cannot retroactively repair a stored visibility entry whose key was already shared
- **Reading an API error from `result.error.message` on a rejected RTK thunk** — Redux Toolkit's default `miniSerializeError` copies only `name`/`message`/`stack`/`code`, and a real Axios error's `.message` is the generic `"Request failed with status code 409"`. The server's `response.data.detail` is dropped, so the user sees an HTTP status instead of the reason. Use `rejectWithValue(formatApiError(err))` (`services/apiError.ts`). A test that rejects with a plain `Error` carrying the final text **passes while the app is broken** — mock an `AxiosError` shape instead. `BookingTypesPanel`, `ComponentTypesPanel` and `LifecycleTemplatesPanel` were converted on 2026-08-04 — `componentTypeSlice` and `bookingLifecycleSlice`'s mutating thunks now `rejectWithValue(formatApiError(err))` and the panels read `result.payload`. One gap deliberately left: `LifecycleTemplatesPanel`'s **Copy** button dispatches `copyLifecycleTemplate` without inspecting the result at all, so a refused copy still fails silently — a missing-error-handling bug, not a wrong-message one
- **Day arithmetic by flooring a millisecond delta** — `formatExpiry` did this and reported an environment "overdue by 1 day" throughout the whole day it actually expired, because the form writes expiries at `T00:00:00Z`. Difference **UTC calendar days** (`Date.UTC(y,m,d)` on both sides), and drive any colour threshold from the same delta as the label, or the two disagree for a day
- **Assuming `current_user.id` belongs to `current_user.active_tenant_id`** — under master-admin impersonation they differ, so an owner/FK validation scoped to the active tenant 404s. In the spreadsheet import that `HTTPException` escaped the per-row `except (ValueError, ValidationError)` and killed the **entire upload**. Nothing in the suite covers the impersonation dimension of imports
- **`alembic downgrade -1` on the dev database** — it steps back from whatever the *current* head is, not from your new revision, so it will happily drop a table you did not write. Doing this while testing a migration dropped `tenant_secret` and wiped the dev tenant's stored GitHub token. Check `alembic current` first, and prefer a scratch database (`tests/test_migration_schema_drift.py` builds one) for exercising up/down

---

## Quick Reference

```python
# Sessions: 15-minute access token + 14-day rotating refresh token. Never mint a
# token with create_access_token directly — go through auth_session_service so the
# session gets a revocable database row.
from app.services import auth_session_service
session = await auth_session_service.issue_session(db, user)

# Logging — the root logger is configured at import; just take a module logger.
# Lines are stamped with the current request id automatically.
import logging
logger = logging.getLogger(__name__)

# Database session
from app.db.base import get_db
async def my_endpoint(db: AsyncSession = Depends(get_db)): ...

# Auth + tenant context (use active_tenant_id — handles impersonation)
from app.core.security import get_current_user
async def my_endpoint(current_user: User = Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id  # NOT .tenant_id

# Require master admin
from app.core.security import require_master_admin
async def my_endpoint(current_user=Depends(require_master_admin())): ...

# Require tenant admin (role="Admin")
from app.core.security import require_tenant_admin
async def my_endpoint(current_user=Depends(require_tenant_admin())): ...

# Require any specific role
from app.core.security import require_role, Role
async def my_endpoint(current_user=Depends(require_role(Role.RELEASE_MANAGER))): ...

# Publish event (outbox pattern)
from app.core.events import publish_event
await publish_event(event_type="BookingCreated", aggregate_id=booking.id, payload={...})
```

```typescript
// Frontend: dispatch async thunk
const dispatch = useDispatch();
useEffect(() => { dispatch(fetchEnvironments()); }, []);
```

---

## Architecture Reference

See [docs/prod architecture.md](<docs/prod%20architecture.md>) for:

- Multi-tier architecture diagram
- Layer responsibilities (API / Service / DB)
- Multi-tenancy pattern
- Event-driven architecture & outbox pattern (NATS/JetStream)
- Database design patterns
- Frontend state management
- GitHub-first infrastructure discovery
- API design standards & response formats
- Testing strategy
- Deployment architecture (dev OrbStack + prod macmini)

The macmini host service map (all running Docker services, ports, and endpoints) is kept outside this repo, in `envmgr-infra-notes/macmini-host-map.md`. It documented a personal host rather than this project, so it was removed when the repo went public.

---

> **Note**: `CLAUDE.md` (this file) is the authoritative guide for Claude Code sessions. The original Gemini-era guide is kept at [docs/archive/GEMINI.md](docs/archive/GEMINI.md) — see [docs/archive/](docs/archive/) for what else is there and why.
