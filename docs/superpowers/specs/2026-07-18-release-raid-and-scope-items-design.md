# Release RAID Log + Scope Items — Design

> **Status:** approved design (2026-07-18). Feature request: a RAID log for releases
> (running a release is like running a project), with Risk→Issue promotion and linkage to
> the scope items (Jira/GitLab/GitHub stories) each release delivers, so the source projects'
> managers can see when their requirements are being worked.
>
> **Delivered as one feature, two sub-projects, both in the first full version:**
> **SP-1 Scope Items** (built first — brings scope forward, Jira-independent) →
> **SP-2 RAID Log** (links into SP-1). Requirements: [../../requirements.md](../../requirements.md)
> §2.5. Conventions: [../../../CLAUDE.md](../../../CLAUDE.md).

---

## 1. Goals & non-goals

**Goals**
- A per-release **RAID log** — Risks, Assumptions, Issues, Dependencies — with the full
  project-controls feature set: owners, dates, RAG, scoring, status lifecycles, audit history,
  a probability×impact heat-map, and a summary dashboard.
- **Risk → Issue promotion** (and the generalised invalidated-Assumption → Risk/Issue path),
  keeping the source item for traceability.
- **Scope items usable now**, independent of the deferred Jira importer: manual entry +
  **spreadsheet import**, each carrying a first-class **project code + project name** so a PM
  can see when their requirements are in flight.
- **RAID ↔ scope linkage** (M:N) as the PM-communication bridge, plus general RAID item↔item
  relations. Domain events emitted for a future external push-back.
- **Enterprise-release RAID rollup**, mirroring the existing systems/scope/timeline/members rollups.
- **Tenant-configurable scoring** (probability/impact scales + RAG bands per tenant).

**Non-goals (v1)**
- Jira / GitLab / GitHub **importers** for scope items — the `source` enum and fields are made
  ready, but only manual + spreadsheet import are built now.
- **Live outbound push** to Jira / PM tools — events are emitted; the consumer that pushes
  RAID/scope updates externally is future work.
- **Tenant-configurable RAID *status lifecycles*** — v1 ships fixed, well-defined status sets per
  type (configurable scales only, per the decision). Reusing the generalised `lifecycle_service`
  for RAID is a possible later extension.
- RBAC hard-enforcement inherits the project's existing deferred state (roles exist; OAuth/RBAC
  upgrade is post-roadmap).

---

## 2. Sub-project 1 — Scope Items (built first)

The `ReleaseChange` model already exists (`backend/app/db/models/release_change.py`) and is
manually creatable via `release_scope_service`. SP-1 makes it PM-useful without Jira.

### 2.1 Model changes — `release_change`
Add columns (all nullable, backfill-safe):
- `project_code: str | None` (String(50), indexed) — the source project's code (e.g. `PAY`, `RETAIL`).
- `project_name: str | None` (String(200)) — human-readable source project name.

Extend the `source` value set from `manual | jira` to **`manual | spreadsheet | jira | gitlab | github`**
(stored as VARCHAR; validated in the schema layer — no native enum, per project convention).

Migration: `op.add_column` for the two columns (manual DDL, no autogenerate). No data backfill needed.

### 2.2 Spreadsheet import
- `backend/app/services/scope_import_service.py` — mirrors `excel_import_service` structure:
  parse an `.xlsx`/`.csv`, validate rows, create `ReleaseChange` rows with `source="spreadsheet"`,
  return a per-row result summary (created / skipped / errored with reasons).
- Columns (template, in order): `external_key`, `title`, `description`, `change_kind`
  (`story|defect`), `external_status`, `project_code`, `project_name`, plus any tenant custom-field
  keys for the `release_change` subtype (validated against `custom_field_service`).
- Endpoint: `POST /api/v1/releases/{release_id}/scope/import` (multipart upload), tenant-admin /
  release-manager guarded, `active_tenant_id`, validates the release belongs to the tenant.
- Downloadable template: `GET /api/v1/releases/scope/import-template` (or a static asset), matching
  the existing Excel-template download pattern.
- Idempotency: a row whose `external_key` already exists on the release is **updated**, not
  duplicated (upsert on `(release_id, external_key)` when `external_key` is present; otherwise insert).

### 2.3 UI
- `ScopeItemDialog` gains **Project code** + **Project name** fields.
- A **Scope Import** dialog (file picker + template download + result summary table).
- Scope tab: add **group/filter by project** (project_code) and show project columns.

### 2.4 Tests
- `scope_import_service` parser tests (valid rows, bad change_kind, missing title, custom-field
  validation, external_key upsert-not-duplicate).
- Integration: import endpoint (auth, tenant isolation, malformed file → 400).
- Scope CRUD tests extended for `project_code/name` round-trip.

---

## 3. Sub-project 2 — RAID Log

### 3.1 Data model

**`raid_item`** — one polymorphic table, discriminated by `item_type`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `tenant_id` | FK tenant | indexed, isolation |
| `release_id` | FK release (CASCADE) | indexed |
| `item_type` | str | `risk \| assumption \| issue \| dependency` (VARCHAR) |
| `seq` | int | per `(release_id, item_type)` sequence → `ref_code` = prefix+seq (`R-001`, `A-001`, `I-002`, `D-001`) |
| `title` | str(500) | |
| `description` | text | |
| `status` | str | per-type fixed lifecycle (see §3.3) |
| `owner_id` | FK user | accountable owner (nullable until assigned) |
| `raised_by` | FK user | |
| `raised_at` | datetime | |
| `target_date` | datetime? | target resolution / mitigation-by |
| `review_date` | datetime? | next review; drives an "overdue review" flag |
| `closed_at` | datetime? | |
| `probability` | smallint? | risk/issue — 1..N per tenant scale |
| `impact` | smallint? | risk/issue — 1..N per tenant scale |
| `response_strategy` | str? | risk — `avoid \| reduce \| transfer \| accept` |
| `mitigation_plan` | text? | risk |
| `contingency_plan` | text? | risk |
| `validation_status` | str? | assumption — `unvalidated \| validated \| invalidated` |
| `validated_at` | datetime? | assumption |
| `evidence` | text? | assumption |
| `resolution_plan` | text? | issue |
| `resolved_at` | datetime? | issue |
| `direction` | str? | dependency — `inbound \| outbound` |
| `counterparty` | str? | dependency — the team/vendor depended on |
| `due_date` | datetime? | dependency |
| `release_dependency_id` | FK release_dependency? | dependency — optional cross-link to an existing release-ordering dependency |
| `promoted_from_id` | FK raid_item? (self) | set on an item created by promotion (Issue←Risk, Risk/Issue←invalidated Assumption) |
| `custom_fields` | JSON? | tenant custom fields for the `raid_item` subtype |
| `deleted_at` | datetime? | soft delete |

**Severity** = `probability × impact` (computed, not stored); **RAG** derived from the tenant's
`rag_bands`. Items store raw integers so relabelling scales never rewrites history.

`ref_code` uniqueness: partial unique index on `(release_id, item_type, seq) WHERE deleted_at IS NULL`
(Postgres-only, following the `nameuniqguard` convention). `seq` allocated as `MAX(seq)+1` within
`(release, type)` at creation (via `db.flush()`); the unique index backstops the check-then-insert race.

**`raid_config`** — one row per tenant (configurable scoring), seeded with defaults on tenant creation:
| Column | Type | Notes |
|--------|------|-------|
| `tenant_id` | FK tenant (unique) | |
| `probability_scale` | JSON | `[{level, label, color}, …]` (default 5-point) |
| `impact_scale` | JSON | `[{level, label, color}, …]` (default 5-point) |
| `rag_bands` | JSON | `[{rag, min, max, color}, …]` mapping severity → RAG (default green 1–5 / amber 6–14 / red 15–25) |

Editable via an admin **RAID Settings** page. Changing a scale's size is guarded when items already
reference out-of-range levels (warn, don't silently break).

**`raid_item_scope_link`** — M:N `raid_item ↔ release_change`:
`id, tenant_id, raid_item_id (FK CASCADE), release_change_id (FK CASCADE)`,
unique `(raid_item_id, release_change_id)`. The **PM-communication bridge** — a linked scope item's
`project_code/project_name` identifies which project/PM to inform.

**`raid_item_relation`** — general M:N `raid_item ↔ raid_item` (beyond promotion):
`id, tenant_id, from_item_id, to_item_id, relation (relates_to | caused_by | duplicates | blocks)`,
unique `(from_item_id, to_item_id, relation)`, self-link forbidden (CheckConstraint).

**`raid_item_history`** — field + status-change audit, mirroring `release_change_history`:
`id, tenant_id, raid_item_id, field_name, old_value (JSON), new_value (JSON), changed_by, changed_at`.

### 3.2 Scoring & RAG
- `severity = probability × impact`; RAG from `raid_config.rag_bands`.
- A **probability×impact heat-map** view (grid coloured by band, cells list the risks/issues at that
  P/I coordinate).
- `raid_service` exposes pure helpers `severity(p, i)` and `rag(severity, config)` — unit-tested.

### 3.3 Status lifecycles (fixed, v1)
- **Risk:** `open → mitigating → closed`; `→ promoted` (on Risk→Issue promotion; risk retained).
- **Assumption:** status `open → closed`; independent `validation_status` `unvalidated → validated |
  invalidated`. An `invalidated` assumption can be promoted to a Risk or Issue.
- **Issue:** `open → in_progress → resolved → closed`; `escalated` boolean flag.
- **Dependency:** `identified → in_progress → met | closed`; `at_risk` boolean flag.

Transitions validated in `raid_service` (simple per-type maps); every transition writes `raid_item_history`.

### 3.4 Promotion
`POST /api/v1/releases/{release_id}/raid/{item_id}/promote` with `{ target_type: "issue" | "risk" }`:
- Creates a new item of `target_type` (its own `seq`), copying `title`, `description`, `owner_id`,
  and (for risk→issue) `probability/impact`; sets `promoted_from_id = source.id`.
- Transitions the source: Risk → `promoted`; Assumption stays (already `invalidated`) with a relation.
- Writes history on both; emits `RaidItemPromoted`.
- Response returns the new item; the UI links source↔target (`promoted_from_id`).

### 3.5 PM routing & events (outbox)
RAID item → `raid_item_scope_link` → `release_change.project_code/project_name`. Surfaced on the
Release RAID tab and the scope views (which project each risk/issue touches). Domain events published
via `publish_event` (outbox): `RaidItemRaised`, `RaidItemStatusChanged`, `RaidItemAssigned`,
`RaidItemPromoted`, `RaidItemClosed`, `RaidItemLinkedToScope`. **No live external push in v1** — the
events are the seam a future Jira/GitLab/PM-notification consumer attaches to.

### 3.6 Enterprise rollup
Add a **RAID rollup** for enterprise releases, aggregating accepted member project releases'
RAID items: counts by type × RAG, open-issue count, top risks by severity, overdue reviews. Mirrors
`enterprise_rollup_service` patterns (systems/scope/timeline/members) and re-asserts `tenant_id` +
member scoping.

### 3.7 API surface
Thin endpoints → `raid_service` (no HTTP logic in the service; `db.flush()` not `commit()`):
- `GET  /releases/{id}/raid` — list, filters: `item_type`, `status`, `owner_id`, `rag`, `overdue`.
- `POST /releases/{id}/raid` — create.
- `GET/PATCH/DELETE /releases/{id}/raid/{itemId}` — read/update (history-logged)/soft-delete.
- `POST /releases/{id}/raid/{itemId}/promote` — promotion.
- `POST/DELETE /releases/{id}/raid/{itemId}/scope-links` — add/remove scope link (validates the
  `release_change` belongs to the same tenant **and** release — IDOR guard).
- `POST/DELETE /releases/{id}/raid/{itemId}/relations` — add/remove item↔item relation.
- `GET  /releases/{id}/raid/summary` — counts by type/RAG + heat-map matrix.
- `GET/PUT /tenant/raid-config` — admin scale/band config (tenant-admin guarded).
- `GET  /releases/{enterpriseId}/rollup/raid` — enterprise RAID rollup.

### 3.8 UI
- **RAID tab** on Release detail: sub-tabs R/A/I/D as MUI DataGrids (ref_code, title, owner, status,
  RAG, severity, dates); toolbar filters; **heat-map** + **summary cards**.
- **RAID item dialog**: type-aware fields (scoring for risk/issue, validation for assumption,
  direction/counterparty for dependency), owner, dates, scope-link picker (search scope items by
  title/external_key/project), relation picker, promote action.
- **RAID Settings** admin page: edit probability/impact scales + RAG bands (live preview of the
  heat-map colouring).
- Enterprise release **RAID rollup** tab.
- Redux slice + service layer per `frontend/src` conventions; reuse `useConfirm` for destructive actions.

### 3.9 Permissions & tenant isolation
- Create/edit/promote/config = Release Manager / Admin (follow existing release sub-resource guards
  used by gates/scope); item owners may update their own items.
- Every table carries `tenant_id`; endpoints use `active_tenant_id`; all FK inputs (release_id,
  scope_change_id, related raid_item_id, owner_id) validated to belong to the caller's tenant —
  the IDOR-write pattern established in `change_request_service._validate_*`.

### 3.10 Migrations
Manual DDL (no autogenerate): `create_table` for `raid_item`, `raid_config`, `raid_item_scope_link`,
`raid_item_relation`, `raid_item_history`; partial unique indexes (`(release_id, item_type, seq)`,
`(raid_item_id, release_change_id)`, `(from_item_id, to_item_id, relation)`, `(tenant_id)` on config)
Postgres-only per the `nameuniqguard` convention. Seed default `raid_config` in the tenant-creation
seed path (alongside lifecycles / event types / scope-change rules).

### 3.11 Tests
- **Service:** `severity`/`rag` derivation across configs; status-transition validation per type;
  promotion (Risk→Issue keeps source + links + history); seq allocation; scope-link + relation
  tenant/release validation.
- **Integration:** RAID CRUD + auth + tenant isolation; **cross-tenant scope-link rejection**
  (400, per the IDOR tests); promotion endpoint; summary/heat-map; enterprise rollup scoped to
  members; `raid_config` admin round-trip.
- **Migration:** applies cleanly; partial uniques enforce.

---

## 4. Build order & roadmap placement

1. **SP-1 Scope Items** — model columns, source enum, spreadsheet import, UI, tests. Ships first;
   independently valuable (PM-visible scope without Jira).
2. **SP-2 RAID Log** — models/config/services/endpoints/UI/rollup/events/tests, linking to SP-1's
   scope items.

Roadmap: a release-management enhancement extending Phase 3 (Releases). Complements the deferred
Jira importer (Phase 3 Sub-3) and the Phase 9 Release-Governance direction from
[../../gap-analysis.md](../../gap-analysis.md) (intake/go-no-go/risk-scoring), which can later consume
RAID risk data.

## 5. Open follow-ups (explicitly deferred)
- Jira / GitLab / GitHub scope importers (fields + `source` values ready now).
- Outbound push consumer (Jira comments / PM notifications) on the RAID events.
- Tenant-configurable RAID status lifecycles (reuse `lifecycle_service`).
- RBAC hard-enforcement (inherits project-wide deferral).
