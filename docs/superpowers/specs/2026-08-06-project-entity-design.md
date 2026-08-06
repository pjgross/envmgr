# Project entity, members and usage agreements — design

**Status**: designed, not implemented. Phase 7, sub-project **A1**.

## Where this sits in Phase 7

Phase 7 is two programmes. **B** (environment lifecycle & governance) has shipped B1, B3a and
B3b. **A** (multi-project coordination) has shipped nothing; A1 is its first sub-project and
gates A3 and A4.

- **A1 — this spec.** The `Project` entity, its team, the links from bookings, releases and
  environments, and the usage-agreement table.
- **A2** `EnvironmentGroup` + booking a group as one unit — independent of A1.
- **A3** `UsageAgreement` enforcement — `BookingService` checking the agreements A1 records,
  plus the cooperation rules of [requirements.md §2.12](../../requirements.md).
- **A4** Project-aware contention: priority-ordered resolution and escalation.

## The roadmap line is wrong, and this spec corrects it

`docs/phases/phase-7.md` and `CLAUDE.md` both describe A1 as promoting a concept that "leaks as
`ReleaseChange.project_code`/`project_name`, `release_kind='project'` and
`release_membership.project_release_id`". Read against the code, three of those four are not
references to a project at all:

| Where | What it actually is |
|---|---|
| `BookingRequest.project_name` | Free text, `VARCHAR(200) NOT NULL`. **The one real case.** |
| `ReleaseChange.project_code` / `project_name` | **External** identifiers, populated by the spreadsheet scope import and a tracker. They sit directly beside `jira_project_config_id` under the comment *"Sub-project 3 promotes these to real FKs"*. Phase 3 Sub-3 (Jira, deferred) owns them. |
| `release_kind = 'project'` | A release **type discriminator** — "project" as opposed to "enterprise". Not a reference. |
| `release_membership.project_release_id` | The child release inside an enterprise release. "Project" is an adjective meaning non-enterprise. |

A1's real surface is **one existing field**, not four. Renaming the other three would be churn
with no consumer. Both documents must be corrected when this ships.

## What the code actually looks like today

Checked against the code, not the roadmap.

- `BookingRequest.project_name` is required free text, referenced in **67 places** across the
  backend and **60** across the frontend.
- **Users treat it as a booking label, not a project name.** The dev tenant's values are `test`,
  `Reserved check`, `booking 1`, `Health Demo Booking`, `Project 3`, `Project 1`. Most answer
  "what is this booking for", not "which project owns it".
- `UserGroup` exists (B3a) and is deliberately generic — it was not called `OperationsTeam`
  precisely so A1 could reuse it. `environment.operations_group_id` is the pattern to copy.
- There is no project entity, no usage agreement, and nothing linking a release to a project.

## Scope

**In scope**

1. A `Project` entity with a team, pointing at an existing `UserGroup`.
2. `booking_request.project_id` and `release.owning_project_id`, both nullable.
3. A `usage_agreement` table — project, environment and a window — **recorded, never enforced**.
4. CRUD API, admin UI, and the pickers and filters that make the links usable.

**Out of scope — and inherited by A3 and A4 as a fixed line**

- **No enforcement.** An agreement is a record. `BookingService` is untouched: a project may
  still book an environment it has no agreement for, nothing warns and nothing rejects. That is
  A3, with its rules. Keeping the enforcement out of the sub-project that introduces the schema
  is the same call B3a made with group membership, and for the same reason — a behaviour change
  deserves its own scrutiny.
- **No project priority field.** A4 owns contention ordering. A priority nothing reads is the
  failure B1 refused when it declined to ship `idle` before B5 defined detection.
- **No `project_member` table.** Membership is `team_group_id` → `user_group`, and it grants **no
  permissions**: every authorization rule stays role-based, plus the two group reads B3b added.
- **`ReleaseChange.project_code`/`project_name` untouched** — external, and Phase 3 Sub-3's.
- **`release_kind` and `release_membership.project_release_id` untouched** — naming, not
  references.
- **`BookingRequest.project_name` is not migrated or removed.** See below.

## Data model

```
project                              usage_agreement
  id, tenant_id                        id, tenant_id
  name          VARCHAR(200) NOT NULL  project_id      FK -> project.id
  code          VARCHAR(50)  NULL      environment_id  FK -> environment.id
  description   TEXT NULL              starts_at       TIMESTAMP NULL
  team_group_id FK -> user_group.id    ends_at         TIMESTAMP NULL
                             NULL      notes           TEXT NULL
  is_active     BOOLEAN NOT NULL       deleted_at      TIMESTAMP NULL
  deleted_at    TIMESTAMP NULL

booking_request.project_id     FK -> project.id  NULL   -- project_name KEPT
release.owning_project_id      FK -> project.id  NULL
```

### Decisions

**`project_name` stays, relabelled.** The field is required and in practice holds a booking
label. Promoting it to an FK would either manufacture projects named `test` and `booking 1` —
junk every tenant inherits permanently — or rewrite user-entered data. Instead `project_id`
arrives beside it, nullable, and the UI relabels the existing field **"Purpose"**. Nothing to
backfill, nothing lost: `Health Demo Booking` never has to become a project. The API field name
is unchanged, so the relabel is copy only.

**`release.owning_project_id`, not `project_id`.** `release_kind='project'` already lives in that
table meaning "not an enterprise release". Two things called *project* on one row is how a future
reader gets it wrong.

**A1 ships the usage-agreement table complete, with its window.** The alternative — a plain
project↔environment junction now — is that table minus two nullable timestamps, and A3 would have
to migrate it. Building it whole costs nothing and leaves A3 as what it actually is: the check
and the cooperation rules. **A3's line in `phase-7.md` must be rewritten accordingly**, or the
next person reads it as still owning the schema.

**One environment, many projects — deliberately not a single owning FK.** Shared estates are the
normal case, and §2.12 frames usage agreements as how projects "cooperate in a shared
environment". A one-to-many FK would have to be unpicked by A3.

**Members come from `team_group_id`.** A person's group memberships answer both "which
environments do you operate" and "which projects are you on". A second membership model is what
B3a's generic `UserGroup` existed to prevent.

**Name unique per tenant, enforced in the service.** A partial unique index is inert on SQLite,
so it would guard only the PostgreSQL leg — the same call `environment_tier` and `user_group`
both made. Case-insensitive.

## API

```
GET    /projects                              any member   bounded + sortable
POST   /projects                              Admin
GET    /projects/{id}                         any member
PATCH  /projects/{id}                         Admin
DELETE /projects/{id}                         Admin        soft delete, never refused

GET    /projects/{id}/usage-agreements        any member   bounded
POST   /projects/{id}/usage-agreements        Admin
DELETE /projects/{id}/usage-agreements/{agreement_id}   Admin
GET    /environments/{id}/usage-agreements    any member   bounded
```

Read for any tenant member, write for Admin — the split groups already use. Everyone needs to see
which project a booking belongs to.

**Deleting a project is always allowed.** This deliberately differs from `delete_group`, which
409s while any environment references it. A group operates a handful of environments; a project
accumulates every booking and release it ever had, so a reference check would make every project
permanently undeletable the moment someone booked against it. It soft-deletes; existing
references keep rendering the name marked archived, exactly as B3b handles a soft-deleted
operating group; and `is_active = false` is what removes it from pickers going forward.

**Both directions on the agreements, one table.** `/projects/{id}/usage-agreements` answers "what
may this project use"; `/environments/{id}/usage-agreements` answers "who may use this
environment". The second is what the environment detail page needs, and shipping only the first
guarantees someone adds a client-side filter over a capped list later.

Every list endpoint takes `pagination()` with a primary-key tiebreaker and emits
`X-Total-Count`. The projects list takes `sorting()` whitelisting `name`, `code` and
`created_at` — with a `sortWhitelists.json` entry **only if the grid sorts server-side**. B3a
shipped that entry for a client-side grid, where it was dead weight and its "422s on first click"
comment was false.

New filters: `?project_id=` on bookings and on releases.

### Errors

| Case | Response |
|---|---|
| Cross-tenant project, environment or agreement id | **404**, never 403 |
| Duplicate project name within the tenant | 409, naming the conflict |
| An agreement with the same project, environment AND identical window | 409 |
| `ends_at` before `starts_at` | 422 |

**Overlapping windows are allowed**, and only an exact duplicate is refused. A1 records rather
than enforces, so two agreements covering overlapping periods is a statement about intent, not a
contradiction the system must resolve — and deciding what an overlap *means* is A3's job, once
something reads them. Uniqueness is enforced in the service rather than by a constraint, for the
same reason the project name is: a partial unique index excluding soft-deleted rows is inert on
SQLite.

## Frontend

**Projects live under Administration**, beside User Groups and Environment Tiers — writes are
Admin-only and, like those, it is a vocabulary other entities point at.

- **Projects list** — `useServerGrid`; Name / Code / Team / Environments / Status, with create and
  edit dialogs following `EnvironmentTiersPanel`.
- **Project detail** — the team group, linking through to it, and the project's usage agreements
  with add and remove.
- **Booking form** — an optional Project picker beside the existing free-text field, **relabelled
  "Purpose"**. The relabel touches the booking form, the list column header, the detail page and
  the conflicts panel.
- **Release form** — an optional Owning Project picker.
- **Environment detail** — a "Projects using this environment" panel from the environment-direction
  endpoint.
- **Filters** — project on the booking and release lists, through `useServerGrid`'s `filterKeys`
  so they round-trip through the URL.

Three things built in from the first commit:

- `projectSlice` uses `rejectWithValue(formatApiError(err))` from the start.
- **The project name travels with the row** on bookings and releases. Resolving it client-side
  against a capped collection renders a miss as `—`, which is information lost, not hidden.
- **The project filter's "no selection" state must not be spelled `all` in the URL.**
  `buildParams` drops a filter valued `all`, so both states would build identical params and the
  grid would never refetch. Spell it `any` and restore at the fetch boundary, as
  `ScopeWindowsTable` does.

**The "Projects using this environment" panel needs copy saying it is a record, not a rule.** In
A1 nothing stops a project booking an environment it has no agreement for. Without that line the
first person to see the panel will assume it is enforced.

## Migration

Two `create_table`s and two `add_column`s. Additive and reversible; every new column is nullable,
so there is **no backfill** — which is the point of keeping `project_name`.

Write the DDL by hand — `init_db()` calls `create_all`, so `--autogenerate` emits an empty
migration. **Check the migration against its models by hand**: `tests/test_migration_schema_drift.py`
compares only column *name sets*, so a passing run is not evidence they agree. Four real drifts
passed it during B3a, including naive-versus-timezone-aware timestamps that would have reached
production. Build a scratch database each way and compare types, timezone-awareness, server
defaults and index names.

## Testing

Both engines.

- **Each of the four new FK write paths gets its own test, on create *and* update** —
  `booking_request.project_id`, `release.owning_project_id`, and the agreement's `project_id` and
  `environment_id`. A 2026-07-16 audit found four IDOR-class gaps of this kind; across B3a and
  B3b the same missing `tenant_id` filter appeared **four more times**, and not once was it caught
  by a test that already existed. Prove each by mutation: drop the filter, watch a named test fail.
- **Impersonation.** `current_user.id` and `active_tenant_id` belong to different tenants under
  master-admin impersonation. B3b's fulfilment shipped with `owner_user_id` unvalidated for
  exactly this reason.
- **A test that a usage agreement changes nothing.** Booking an environment the project has no
  agreement for must still succeed. If that starts failing, someone has added enforcement without
  the rules, and A3 should be a deliberate change rather than a surprise.
- Soft-deleting a project leaves its bookings and releases rendering the name, marked archived.
- Bounded-endpoint conformance rows for each new list endpoint.
- Frontend fixtures reject with an **AxiosError shape** — a plain `Error` carrying the final text
  passes against broken code.

## Documentation

Two corrections are required, not optional — both statements are wrong today:

- `phase-7.md`'s **A1** line, which claims the concept leaks through four places when three are
  not references.
- `phase-7.md`'s **A3** line, which still claims ownership of the schema A1 now ships.

Plus the usual: `pagination.md`'s bounded-endpoint and sortable-column tables, and the admin and
user guides.

## Sizing

Roughly eight implementation tasks — smaller than B3b's eleven, with no lifecycle machinery and
no enforcement.

## Open questions

None. Every fork raised during brainstorming was decided: `project_id` beside `project_name`
rather than replacing it; members via `UserGroup` rather than a second membership model; bookings,
releases **and** environments linked; the environment link many-to-many, which pulled A3's table
forward into A1 with its window intact.
