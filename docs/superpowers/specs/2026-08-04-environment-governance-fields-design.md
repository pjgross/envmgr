# Environment governance fields — design

**Status**: implemented (backend); frontend follows in a later PR. Phase 7, sub-project B1 of ten.

## Where this sits in Phase 7

`docs/phases/phase-7.md` lists eleven tasks under "Multi-Project Coordination". `docs/plan.md`
then expands the same phase with the whole of `requirements.md` §2.12, "Environment Lifecycle
& Governance". Together that is two independent programmes and roughly ten sub-projects — far
too much for one spec, so Phase 7 is decomposed first:

**A — Multi-Project Coordination**

- **A1** `Project` entity + members; promote the free-text `BookingRequest.project_name` to an FK
- **A2** `EnvironmentGroup` + booking a group as one unit
- **A3** `UsageAgreement` (project A may use environment E in window W), checked by `BookingService`
- **A4** Project-aware contention: priority-ordered resolution + escalation with a response window

**B — Environment Lifecycle & Governance (§2.12)**

- **B1** Governance fields: tier, Reserved/Idle, named owner, expiry — **this spec**
- **B2** Naming & tagging conventions + untagged quarantine after a grace period
- **B3** Environment Request Form + auto-generated Welcome Pack
- **B4** Soft (preemptible) vs hard reservations + time-slot bookings
- **B5** Decommissioning workflow + idle auto-detection
- **B6** Forward contention as a calendar leading indicator

A1 gates A3 and A4; B1 gates B2, B3 and B5. The two programmes are otherwise independent. B1
goes first because it is the smallest surface that unblocks the most, it needs no new
integration, and every field it adds is visible in the app the day it ships.

## What the code actually looks like today

Checked against the code, not the roadmap — `phase-6.md` was two-thirds wrong and cost a
correction pass, so this is now the first step of any phase work here.

| Phase 7 / §2.12 says | Reality |
|---|---|
| `Project` model | **Absent.** The concept leaks as free text in four places: `BookingRequest.project_name`, `ReleaseChange.project_code`/`project_name`, `release_kind="project"`, `release_membership.project_release_id` |
| `EnvironmentGroup` model | **Absent.** Only a dangling `Booking.environment_group_id` column, no FK, commented `# no FK yet (Phase 7)` since the March booking migration |
| `UsageAgreement` model | **Absent** |
| Project-aware conflict detection | `conflict_service.list_conflicts` exists but is per-environment, first-come, with no project or priority notion |
| Environment tier | **Absent as a concept — present as data.** `environment_type` is free text; the dev database holds `SIT`, `sit`, `uat` |
| Reserved / Idle status | **Absent.** `EnvironmentStatus` is `ACTIVE / INACTIVE / MAINTENANCE / DECOMMISSIONED` |
| Named owner, expiry | **Absent.** No owner column, no expiry column |

Two findings shape the design below.

**`environment_type` is already a tier, badly.** It holds `SIT`, `sit`, `uat` — the same tier
spelled two ways, because nothing constrains it. It is filterable, sortable and rendered on
the environment list today, so it is not a dead field that can be ignored.

**The `status` column stores the enum *name*, not its value** — `ACTIVE`, not `active`. That
is the storage gotcha `docs/pagination.md` warns about, and it is a reason not to add a second
enum-backed column here.

## Decisions

### Tier is a tenant-configurable table, not an enum

New table `environment_tier`, shaped like the existing `ComponentTypeDefinition` and
`BookingType` vocabularies:

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | FK → tenant, indexed | |
| `name` | `String(200)`, not null | |
| `description` | `Text`, nullable | |
| `category` | `String(50)`, nullable | The standard tier this maps onto: `dev`, `sit`, `uat`, `preprod`, `performance`, `training`, `production`, `other` |
| `color` | `String(7)`, nullable | Badge colour, as `BookingType.color` already does |
| `display_order` | `Integer`, default 0 | Tiers have a progression, Dev → … → Prod. Alphabetical order is wrong |
| `is_active` | `Boolean`, default true | |
| `deleted_at` | `DateTime(timezone=True)`, nullable | Soft delete, per the repo convention |

`category` is a plain `VARCHAR`, deliberately **not** an `SAEnum` — `ComponentTypeDefinition.category`
sets that precedent, and the `status` column already demonstrates what an `SAEnum` stores.

Name uniqueness per tenant is enforced **in the service**, matching `ComponentTypeDefinition`,
rather than by a partial unique index — a partial index is inert on the SQLite leg, so it would
guard only half the test suite.

*Rejected*: a fixed enum of the eight §2.12 tiers. It would have been less code, but this
codebase configures its vocabularies per tenant (`ComponentTypeDefinition`, `BookingType`,
scope change kinds, lifecycle templates), and a tenant whose tiers are "Dev / Integration /
Staging" should not have to file them all under Other.

### The tier replaces `environment_type` rather than sitting beside it

`environment` gains `tier_id` (FK → `environment_tier`, `NOT NULL` once backfilled) and loses
`environment_type`.

Keeping both was considered and rejected: two overlapping fields means every future filter,
report and sort has to decide which one it means, and the answer would drift.

Because the tier vocabulary is per-tenant, the migration loses nothing — each tenant's existing
distinct values *become* tier rows, so there is no bucketing into Other and no judgement call
about what `"imported"` really meant.

Deleting a tier that environments still reference is **refused** (409), not cascaded.
Soft-deleted environments do not count as references — otherwise a tier can never be retired
once anything that used it has been deleted.

`is_active` and `deleted_at` are not the same thing, and the difference matters for pickers: an
inactive tier is **hidden from pickers but still rendered** on environments already using it, so
retiring a tier stops new assignments without blanking existing rows. A soft-deleted tier is one
nothing references at all.

### Reserved and Idle are a derived second axis, not status values

`status` keeps its four administrative values. They are human-set, mutually exclusive and
describe intent. Reserved and Idle are neither: they are derived from data, and an environment
that is reserved is *still* active.

Folding them into the same enum would mean `status = reserved` silently discards whether the
environment is active or in maintenance, and would let a human mark an environment Reserved
that nobody has booked.

So `reserved_now: bool` is **computed in SQL** as an `EXISTS` over bookings — not deleted,
status not a live claim, and `start_date <= now < end_date` (half-open, matching the overlap
convention `conflict_service` already uses). In the query rather than applied in Python
afterwards, which means it is safe to filter on: a Python-side filter would window the page
before the filter and quietly return wrong results (`docs/pagination.md`).

**"Not a live claim" is `{draft, rejected, closed}`** — and it is already duplicated in
`environment_health_service.INACTIVE_BOOKING_STATUSES` and
`environment_utilization_service._INACTIVE_BOOKING_STATES`. This work adds the fourth consumer,
which is the moment to hoist it into one shared constant those two import.

`conflict_service.TERMINAL_STATES` (`{rejected, closed}`) stays separate on purpose — it counts
drafts *as* conflicts, which is a different question. Do not merge it into the shared constant.

### B1 ships no `idle` field at all

Not even one that is always false. A field reading "not idle" when it means "never checked" is
exactly the failure the drift work had to fix — a summary computed from what could be computed
reads as a clean bill of health. Idle arrives in B5 together with its N-day threshold and its
activity sources.

### Owner is required by the API; expiry is required only on create

`owner_user_id` (FK → user) and `expires_at` (`DateTime(timezone=True)`) are both **nullable in
the database**. What the API requires of each:

- `POST /environments` requires both. 422 without them. The form path is unchanged.
- `PATCH /environments/{id}` requires that the environment have an **owner after the patch**. An
  environment that already has an owner can be patched freely, whatever its expiry. One with no
  owner — a legacy row, or any other row missing one — cannot be patched at all until the patch
  supplies one.

**This reverses a position taken earlier in this design.** The paragraphs above originally read
"required going forward" for both fields, and both PATCH's compliance rule and `governance_gap`
originally treated a missing owner *or* a missing expiry as non-compliant. During implementation
the product owner decided that a null `expires_at` means **"no expiry planned"** — a legitimate,
permanent state, not a value someone forgot to fill in. Owner has no equivalent legitimate null:
an environment nobody has ever been assigned to is exactly the ghost-environment signal §2.12
asks for, and there is no honest "nobody will ever own this" to distinguish it from. So the PATCH
compliance rule and `governance_gap` (see API, below) now key on owner alone; a null expiry never
blocks a patch. Without this reversal, a spreadsheet-imported row — owned, but with no expiry
recorded — would have been frozen against even a description edit.

The consequence is deliberate and worth stating: on a row with no owner, changing the status or
the description means supplying an owner at the same time. That is the point. Every edit is an
opportunity to close the gap, and a rule that exempts "small" edits never closes it.

Legacy environments therefore keep a null owner rather than a fabricated one. Backfilling the
owner to the tenant admin was rejected for the migration: it invents a person who never agreed to
own the environment, and it converts the exact signal §2.12 is asking for — which environments
have no accountable owner — into noise. The spreadsheet import is a different case: it sets
`owner_user_id` to the importing admin and leaves `expires_at` null. The importer is present,
acting and identifiable at the moment of import, so recording them as owner is truthful — unlike
fabricating an owner for a pre-existing row nobody touched, which is exactly what the migration
refused to do.

Instead the owner gap is **counted and filterable**: `governance_gap=true` returns environments
with a missing owner. Unowned environments are the ghost-environment problem, so surfacing them
is a feature, not a migration compromise.

`expires_at` is a timezone-aware `DateTime` for consistency with every other date in this
codebase, even though it is a date-grained concept in practice.

## Migration

Hand-written DDL, per the repo checklist — `init_db()` calls `create_all`, so `--autogenerate`
sees nothing to do.

1. `op.create_table("environment_tier", ...)`
2. Add `tier_id`, `owner_user_id`, `expires_at` to `environment`, all nullable
3. Data migration, per tenant:
   - seed the eight standard tiers (`category` set, `display_order` in progression order)
   - fold each tenant's distinct `environment_type` values onto them **case-insensitively**, so
     `SIT` and `sit` both resolve to the seeded standard row named `SIT` — the standard spelling
     wins, and no tenant-specific duplicate is created for a value that only differed by case
   - anything unmatched — `excel_import_service.py:96` writes the literal `"imported"` when a
     spreadsheet has no type — becomes a tenant-specific tier with `category = NULL`. Nothing is
     silently bucketed into Other
4. Set `tier_id` on every environment
5. Alter `tier_id` to `NOT NULL`; drop `environment_type`

Step 5 needs `batch_alter_table`: SQLite cannot alter a column's nullability in place, and the
table rebuild batch mode performs also covers the column drop.

Steps 3 and 4 are a data migration, so they run inside the migration itself with Core
statements — not the ORM, whose models will by then describe a schema the earlier revisions do
not have.

New tenants get their tiers from `environment_tier_defaults.py`, following `release_defaults.py`
— idempotent, called from `tenant_service.create_tenant()`, and re-runnable as a per-tenant
backfill.

**Do not run `alembic downgrade -1` against the dev database while testing this.** It steps back
from the current head, not from the new revision; doing it during the GitHub work dropped
`tenant_secret` and wiped the dev tenant's stored token. Use a scratch database, as
`tests/test_migration_schema_drift.py` builds.

## Consumer sweep

`environment_type` has readers beyond the environment list. All of these move to the tier.

**Backend**

| File | What |
|---|---|
| `app/db/models/environment.py:30` | Column definition |
| `app/api/v1/environments.py:46,56,67` | Sort whitelist entry, filter parameter, service call |
| `app/api/v1/schemas/environment.py:13,21,32` | Create / update / response |
| `app/api/v1/releases.py:850` | Selected into the release environment-coverage query |
| `app/api/v1/schemas/release_env_coverage.py:13` | `CoverageEnvironment.environment_type` |
| `app/services/environment_service.py:29,46,47,90,132,133` | Filter, create, update |
| `app/services/excel_import_service.py:96` | Writes `"imported"` — must now resolve a tier (see below) |

The spreadsheet import resolves a row's type name against the tenant's existing tiers
case-insensitively. An unmatched or blank value falls back to the tenant's **`Other`** tier and
is reported in the import summary — it does **not** create a tier. A vocabulary the admin
configures should not be extendable by uploading a spreadsheet; the migration creates
tenant-specific tiers because that data already existed, which is a different situation.

**Frontend**

| File | What |
|---|---|
| `types/environment.ts:7,41,49` | Response / create / update types |
| `types/release.ts:280` | Declared on the coverage environment type (not currently rendered) |
| `constants/sortWhitelists.json:13` | Sortable column list — asserted by `environmentListServerGrid.test.tsx` |
| `pages/environments/EnvironmentList.tsx` | Column, filter key, create form, validation |
| `pages/environments/EnvironmentDetail.tsx` | Edit form field and detail render |
| `services/environmentService.ts:19`, `store/environmentSlice.ts:46` | Filter parameter |

## API

### Tier configuration

`GET / POST / PATCH / DELETE /api/v1/environment-tiers`. Writes are tenant-admin-gated; reads
are open to any tenant member, because every environment form needs the list.

The list takes `page: Page = Depends(pagination())` and `sorting()` over `{name, display_order,
created_at}`, **ordered by `display_order` then `id`**. The `id` tiebreaker is not decorative:
`display_order` defaults to 0, so ties are the normal case, and `LIMIT`/`OFFSET` over a
non-unique order duplicates and drops rows across pages.

`DELETE` refuses with 409 while any environment references the tier.

### Environment

`EnvironmentResponse` gains `tier_id`, `tier_name`, `tier_color`, `owner_user_id`,
`owner_username`, `expires_at`, `reserved_now`.

Display names **travel with the row**, following the `owner_username` precedent set by
`ReleaseSystemRead.system_name` and the RAID owner fix. They are never resolved in the browser
against a separately-fetched collection: that collection is capped, so a `.find()` miss renders
the entity as `—` and loses information a truncation banner cannot recover.

New list filters, all applied in SQL:

- `tier_id`
- `owner_user_id`
- `expiring_within_days` (int) — environments whose `expires_at` falls within the window.
  A null expiry is **not** a match: it means no expiry was ever planned, not that one is
  overdue, and it is excluded from this filter for the same reason it does not block a `PATCH`
  or count toward `governance_gap`
- `governance_gap` (bool) — owner missing (`owner_user_id IS NULL`). A null expiry is a
  legitimate "no expiry planned" state, not a gap — see "Owner is required by the API; expiry
  is required only on create", above

The `environment_type` query parameter **goes**, replaced by `tier_id`. This is a breaking API
change, taken knowingly: the field it filtered on no longer exists, and keeping a name-matching
shim would reintroduce the free-text matching the tier table exists to end.

The sort whitelist replaces `environment_type` with `tier` → `EnvironmentTier.name`, and adds
`owner` → `User.username` and `expires_at`. Both are real columns on joined tables, so they
satisfy the whitelist rule; `apply_sort` case-folds `String` columns itself, which matters
because both engines here collate by byte value.

The list query now joins two tables and returns extra columns, so `list_environments` moves
from `fetch_page` to `fetch_page_rows`.

## Frontend

**Admin — tier configuration.** A "Tiers" tab on the existing `/admin/config/environment` page.
`EntityConfig.tsx` already renders a tab strip there and already composes panels this way
(`BookingTypesPanel`, `ComponentTypesPanel`, `LifecycleTemplatesPanel`), so this is a new
`EnvironmentTiersPanel` alongside them, not a new page. CRUD, ordering, colour, active flag.

**EnvironmentList.** The type column becomes a Tier badge coloured from `tier_color`; Owner,
Expires and a Reserved indicator are added. Expires renders relatively ("in 12 days",
overdue emphasised) — an absolute date alone makes the reader do the arithmetic that the whole
field exists to prompt. Filters gain tier, owner and the governance gap.

**Create / edit forms.** A tier picker, an owner picker, an expiry date; tier and owner and
expiry all required. `EnvironmentList.tsx` and `EnvironmentDetail.tsx` each carry their own
copy of the environment form, so both change.

**Environment detail.** A governance panel: tier, owner, expiry, reserved.

Three things to honour, each of which has already cost a defect here:

- **Pickers must not read a paged slice.** The tier picker uses a shared full-list hook
  (`useSharedList`, which coalesces in-flight duplicate requests), not the paged grid data.
- The owner picker uses `GET /tenant/users/lite`, which is **knowingly unbounded** — it is one
  of the five growth-bearing endpoints listed as not yet done in `docs/pagination.md`. This adds
  a consumer to it deliberately; bounding it is that backlog item's job, and doing it here would
  break every picker at once.
- **A filter vocabulary containing `all` collides with `buildParams`' "no selection" sentinel** —
  both states build byte-identical params and the grid never refetches. The new tier and owner
  filters must not use `all` as a value.

## Testing

Both engines, per the standing rule — `TEST_DATABASE_URL=postgresql+asyncpg://...` as well as
the default in-memory SQLite. The migration especially: SQLite does not enforce column widths
at all, and its `batch_alter_table` path differs from PostgreSQL's.

- **Migration**, on a scratch database built the way `test_migration_schema_drift.py` does: seed
  environments with `SIT`, `sit`, `uat` and `imported` across two tenants, upgrade, then assert
  `SIT`/`sit` collapsed to one tier, `imported` survived as a tenant-specific tier with a null
  category, every environment has a `tier_id`, and no tier crossed a tenant boundary.
- **`reserved_now`** asserted per booking status: draft, rejected and closed must **not** reserve;
  an approved booking covering now must. This is the assertion that would have caught the
  closed-booking health-alert bug in Phase 5.
- **Sorting by tier and owner** asserted on **rendered row order over mixed-case data**. Not on
  the emitted SQL — the pagination pilot's SQL-token assertions stayed green while the order
  users saw was wrong.
- **`governance_gap`** returns exactly the rows with a null owner — a null expiry alone does not
  count — and the count is the total, not the page length.
- **The PATCH compliance rule**: patching an environment that already has an owner succeeds
  regardless of its expiry; patching a row with no owner is 422 on the description alone, and
  succeeds once the same patch supplies an owner — a null `expires_at` never blocks it.
- **Spreadsheet import** falls back to `Other` for a blank or unrecognised type and creates no
  tier — asserted by counting tiers before and after.
- **Tier delete** refused with 409 while referenced, and permitted once the only environment
  referencing it is soft-deleted.
- **Tenant isolation** on every new endpoint: a tier belonging to another tenant is invisible and
  unassignable. Environments are tenant-scoped and this adds a new cross-entity FK write, which
  is the shape of the four IDOR-class gaps found in the 2026-07-16 isolation audit.
- **Open the pages.** The environment list, the environment detail, the create and edit forms,
  and the new admin tab. Six defects in the pagination programme were found only this way, every
  one of them with a fully green suite.

## Delivery

Two PRs against GitHub `main`:

1. **Backend + migration** — table, columns, data migration, defaults seeding, tier endpoints,
   environment response and filter changes, the shared booking-state constant, the consumer sweep.
2. **Frontend** — admin tier panel, list columns and filters, both forms, detail panel.

`docs/phases/phase-7.md` is corrected as part of PR 1: it currently lists only programme A and
says "detailed task breakdown to be added when Phase 6 is complete". Phase 6 is complete, and
leaving it is how the next person plans against a roadmap that is half the phase.

## Out of scope

Named here so the boundary is deliberate, not accidental:

- **Idle detection** — B5, with its thresholds and activity sources
- **Enforcement of expiry** — B1 records and surfaces it; the warning → extension → teardown
  workflow is B5
- **Naming patterns and mandatory tags** — B2
- **Soft vs hard reservations** — B4. `reserved_now` here is a fact about bookings, not a policy
- **Anything in programme A** — no `Project`, no `EnvironmentGroup`, no `UsageAgreement`
