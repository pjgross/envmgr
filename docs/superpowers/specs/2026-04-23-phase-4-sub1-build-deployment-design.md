# Phase 4 Sub-1 — Build + Deployment Ingestion (Backend)

**Status:** Draft — awaiting user review
**Date:** 2026-04-23
**Phase:** Phase 4 (CI/CD Deployment Tracking), sub-project 1 of 2

## Summary

First backend slice of Phase 4. Introduces `api_key` + `build` + `deployment`
tables and a single custom-JSON webhook, `POST /api/v1/webhooks/deployment`,
authenticated with an `X-Api-Key` header. Ingestion creates or upserts
`Build` + `Deployment` rows, auto-links them to a `ChangeRequest` (or uses
one supplied by the caller), updates the `environment_subsystem_version`
audit trail on success, and emits outbox events. Both `Build` and
`Deployment` accept custom fields defined per-tenant via the existing
`custom_field_definition` machinery so companies can capture metadata
unique to their pipelines (security-scan ids, blast radius, rollout %,
…). No frontend — that's Sub-2.

## Goals

1. A GitHub Actions workflow (or any CI/CD) can post a deployment event to
   EnvManager with a single authenticated HTTP call.
2. The posted event creates a durable record of the build artefact, the
   deployment to an environment, and the change request that authorised
   it — with enough metadata to drive DORA calculations in Phase 5.
3. Each deployment that succeeds updates the "what's installed where"
   state (`environment_subsystem_version`) without a second round-trip.
4. Teams can attach their own metadata to builds and deployments through
   the custom-field system, validated at ingest.
5. API keys give CI/CD callers credentials that are distinct from user
   JWTs and can be revoked/scoped independently.

## Non-goals

- Frontend pages (Sub-2 of Phase 4).
- GitHub's native `deployment_status` webhook format — rejected in
  brainstorming in favour of a custom payload shape that carries DORA
  metadata directly.
- Incident creation on rollback — deferred to Phase 5 where the Incident
  model lives.
- Full human-approval flow on auto-created change requests — we use a
  minimal two-state `code_deployment` lifecycle instead.
- Pipeline-step diffing on re-delivery — callers own the canonical view;
  we replace wholesale.
- Multi-subsystem builds (a build belongs to exactly one subsystem).
- Deployment retries/re-runs as a first-class concept — each run gets a
  new `event_id` from the caller.

## Data model

### New tables

**`api_key`**

- `key_hash` `String(64)` — SHA-256 hex of the raw key (not stored raw).
- `name` `String(120)` — label shown in the admin UI.
- `scopes` `JSONB` — array of scope strings, e.g. `["webhooks:deployment"]`.
- `created_by` FK → `user.id` (required; set to the admin's user id at
  creation time). Used as `raised_by` on any CR auto-created from the
  webhook, since `change_request.raised_by` is NOT NULL.
- `last_used_at` `DateTime(tz=True)` (nullable).
- `expires_at` `DateTime(tz=True)` (nullable).
- Standard `id`, `tenant_id`, `created_at`, `updated_at`, `deleted_at`.
- Unique index on `(tenant_id, key_hash)`.

**`build`**

- `subsystem_id` FK → `subsystem.id` (required, cascade restrict).
- `release_id` FK → `release.id` (nullable).
- `git_sha` `String(64)` — full hash.
- `git_branch` `String(255)` (nullable).
- `build_number` `String(80)` (nullable) — e.g. `"#247"`.
- `commit_timestamp` `DateTime(tz=True)` — required; source of truth for
  DORA Lead Time.
- `build_started_at` / `build_finished_at` `DateTime(tz=True)` (both
  nullable — present on completed builds, absent on builds ingested mid-
  pipeline).
- `jira_tickets` `JSONB` — string array, default `[]`.
- `pipeline_steps` `JSONB` — array of `{name, status, started_at,
  finished_at}`, default `[]`.
- `custom_fields` `JSONB` — default `{}`, validated against
  `custom_field_definition` rows with `entity_type='build'`.
- Standard `id`, `tenant_id`, `created_at`, `updated_at`, `deleted_at`.
- Unique index on `(tenant_id, subsystem_id, git_sha, build_number)` — a
  given subsystem+sha+build_number pair is one row. Webhook replays
  upsert into this row.

**`deployment`**

- `build_id` FK → `build.id` (required).
- `environment_id` FK → `environment.id` (required).
- `release_id` FK → `release.id` (nullable; inherited from `build.release_id`
  at ingest time if the payload doesn't override it).
- `change_request_id` FK → `change_request.id` (required). Set either from
  the payload or from the auto-created `code_deployment` CR.
- `event_id` `UUID` (required). Idempotency key.
- `deployer_name` `String(255)` (nullable) — e.g. `"github.actor:alice"`
  or the API key's `name`.
- `deployed_at` `DateTime(tz=True)` — required.
- `completed_at` `DateTime(tz=True)` (nullable — set when status moves to
  a terminal state).
- `status` `String(20)` — one of `pending | in_progress | success | failed
  | rolled_back`. `native_enum=False`.
- `custom_fields` `JSONB` — default `{}`, validated against definitions
  with `entity_type='deployment'`.
- Standard `id`, `tenant_id`, `created_at`, `updated_at`, `deleted_at`.
- Unique index on `(tenant_id, event_id)` — drives idempotency.

### Existing tables — changes

**`environment_subsystem_version`**

- Rename `build_id` (`String(200)`) to `build_identifier`. Keeps the
  denormalised human label (short sha, semver, release tag) and preserves
  every existing row without re-parsing.
- Add `build_fk_id` (nullable integer FK → `build.id`, indexed). Populated
  by new webhook-driven deployments; stays `NULL` for historical rows.

**`custom_field_definition`**

- No schema change. `entity_type` is already a `String`. The application
  layer begins accepting `'build'` and `'deployment'` as legal values.

### Seed data (tenant creation)

A system-owned `LifecycleTemplate` with:

- `entity_type='change_request'`
- `name='Code Deployment'`
- `is_system=True`
- States: `created → deployed | failed` (single path + failure branch).
- Terminal states: `deployed`, `failed`.
- No field-permission matrix (fields are set at ingest, not edited after).

Added to the tenant-seeding routine used today by the Enterprise Releases
backfill script, and included in the migration's per-tenant upsert step.

## Webhook contract

`POST /api/v1/webhooks/deployment`

**Auth:** `X-Api-Key: <raw key>` — API key must be non-deleted,
non-expired, and carry the scope `webhooks:deployment`.

**Body** (required fields marked `*`):

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",   // *
  "system_slug": "orders",                                // *
  "subsystem_slug": "orders-api",                         // *
  "environment_slug": "sit",                              // *
  "status": "success",                                    // *
  "deployed_at": "2026-04-23T14:30:00Z",                  // *
  "release_id": 42,
  "change_request_id": 12,
  "deployer_name": "github.actor:alice",
  "build": {
    "git_sha": "abc1234567890def...",                     // *
    "git_branch": "main",
    "build_number": "#247",
    "commit_timestamp": "2026-04-23T14:00:00Z",            // *
    "build_started_at": "2026-04-23T14:02:00Z",
    "build_finished_at": "2026-04-23T14:29:00Z",
    "jira_tickets": ["PROJ-101", "PROJ-102"],
    "pipeline_steps": [
      {"name": "test", "status": "success",
       "started_at": "2026-04-23T14:05:00Z",
       "finished_at": "2026-04-23T14:15:00Z"}
    ],
    "custom_fields": {"security_scan_id": "SS-9932", "license_check": "passed"}
  },
  "deployment_custom_fields": {"blast_radius": "us-east-1", "rollout_percent": 100}
}
```

**Responses**

- `200 OK` `{"deployment_id": 17, "build_id": 42, "change_request_id": 83, "replayed": false}`
  — `replayed: true` when we deduped on `event_id`; all other fields
  reflect the existing row.
- `400 Bad Request` — malformed JSON, missing `event_id`, unknown slug
  (with `{"detail": "unknown subsystem_slug 'orders-apii'"}`).
- `401 Unauthorized` — bad or missing API key.
- `403 Forbidden` — API key lacks `webhooks:deployment` scope.
- `422 Unprocessable Entity` — field validation (missing required custom
  field, wrong type, etc.).

### Idempotency semantics

Dedup on `(tenant_id, event_id)`. A replay returns `200` with
`replayed: true` and the ids of the existing rows. No side effects on
replay — no duplicate events, no version-row inserts, no CR transitions.

### Status transitions

The same endpoint accepts updates for an in-flight deployment — the caller
posts the same `event_id` with a later `status`. Allowed transitions:

- `pending → in_progress`
- `pending → success | failed`
- `in_progress → success | failed`
- `success | failed → rolled_back` (explicit rollback after-the-fact)
- Any other transition → `409 Conflict`.

On transition to `success`, the service inserts the
`environment_subsystem_version` row and transitions the CR to `deployed`
(see *Service behaviour*). On `failed`, the CR moves to `failed`. On
`rolled_back`, a `DeploymentRolledBack` event fires; the CR's state is
unchanged (the rollback is itself the audit signal).

## Service behaviour

`DeploymentService.ingest(db, tenant_id, payload)` — single transactional
entry point.

1. Resolve slugs via three one-shot queries (`system_slug` → `system.id`,
   `(system_id, subsystem_slug)` → `subsystem.id`, `environment_slug` →
   `environment.id`). All tenant-scoped, filtered by `deleted_at IS NULL`.
2. Upsert by `(tenant_id, event_id)`. If an existing deployment is found,
   diff the `status` field; if unchanged, return early with `replayed:
   true`. If changed, apply the transition (see table above) and proceed
   to step 6.
3. **Build upsert** — look up by `(tenant_id, subsystem_id, git_sha,
   build_number)`. If found, update `pipeline_steps` /
   `build_finished_at` / `jira_tickets` / `custom_fields` with the
   incoming values (full replacement per field). If not, insert. Custom
   fields validated via
   `custom_field_service.validate(tenant_id, 'build', data.build.custom_fields)`.
4. **CR resolution** —
   - If `change_request_id` given, load + verify tenant scope. 404 → 400
     with a clear message. If the CR is deleted → 400.
   - Else auto-create via
     `change_request_service.create_code_deployment(tenant_id, build_id,
     environment_id, api_key)` using the seeded `Code Deployment`
     lifecycle. The CR is inserted in state `created` with
     `raised_by = api_key.created_by` (which is NOT NULL on `api_key`,
     satisfying the `change_request.raised_by` NOT NULL constraint).
5. **Deployment insert** — new row with `status` from the payload,
   `custom_fields` validated as `entity_type='deployment'`,
   `change_request_id` bound in step 4.
6. **State-driven side effects:**
   - `success`: insert a new `environment_subsystem_version` row
     (`build_fk_id=build.id`, `build_identifier=git_sha[:12]`,
     `version_label = build_number or git_sha[:8]`). Transition the CR to
     `deployed` via `lifecycle_service.transition`.
   - `failed`: transition CR to `failed`.
   - `rolled_back`: no version-row insert; no CR transition; just emit
     the event.
7. **Outbox event** — exactly one of `DeploymentStarted` |
   `DeploymentCompleted` | `DeploymentFailed` | `DeploymentRolledBack`
   depending on final status. Payload: `{deployment_id, environment_id,
   release_id, build_id, status, deployed_at, change_request_id}`.
   `aggregate_type='Deployment'`.
8. Update `api_key.last_used_at` outside the request's critical DB path
   (post-commit hook, fire-and-forget).

All writes happen in a single `AsyncSession` transaction. `get_db()`'s
auto-commit on success applies; no explicit `db.commit()`.

### `EnvironmentService.get_environment_schedule()` extension

Populate the `deployments: []` array (already structurally in the Phase 2
response). Filter: `environment_id == env_id`, `deployed_at` within the
date range, `deleted_at IS NULL`. Shape per row: `{id, build_id, release_id,
change_request_id, status, deployed_at, deployer_name}`.

## Auth — API keys

New FastAPI dependency `api_key_auth(required_scope: str)`:

1. Read `X-Api-Key` header. Missing → 401.
2. `sha256` the raw value. Look up `api_key` by `(key_hash, deleted_at IS
   NULL)`. None → 401.
3. Check `expires_at`. Past → 401.
4. Check `required_scope` in `scopes`. Miss → 403.
5. Set `request.state.api_key = key` and `request.state.active_tenant_id
   = key.tenant_id`. Return.

`last_used_at` bumped asynchronously via an `after_request` hook that
enqueues a task to a tiny in-process queue drained on a short timer — no
extra DB round-trip in the request path.

JWT auth is untouched. Endpoints choose one or the other via their
dependency — no fallback. The webhook uses `api_key_auth('webhooks:deployment')`;
all JWT endpoints keep `get_current_user`.

## API surface

All JWT-authenticated unless noted.

**API key admin** (tenant admin only — `require_tenant_admin()`):

- `GET /api/v1/api-keys` — list `{id, name, scopes, created_by_username,
  last_used_at, expires_at, created_at}`. Never returns the hash.
- `POST /api/v1/api-keys` — body `{name, scopes, expires_at?}`. Returns
  `{id, ...metadata, raw_key}` once. The raw key is shown exactly in
  this response and never again.
- `DELETE /api/v1/api-keys/{id}` — soft delete.

**Builds:**

- `GET /api/v1/builds` — filters `subsystem_id`, `release_id`, `branch`,
  `date_from`, `date_to`, `limit`, `offset`.
- `GET /api/v1/builds/{id}` — full detail including `pipeline_steps`,
  `custom_fields`, and a `deployments: []` array of linked deployments.

**Deployments:**

- `GET /api/v1/deployments` — filters `environment_id`, `release_id`,
  `build_id`, `status`, `date_from`, `date_to`, `limit`, `offset`.
- `GET /api/v1/deployments/{id}` — build metadata (joined), environment
  metadata (joined), linked CR summary, `custom_fields`.
- `POST /api/v1/deployments/{id}/link-change` — body
  `{change_request_id}`. Replaces the currently-linked CR **only** if the
  current CR was auto-created (i.e. its lifecycle template is `'Code
  Deployment'`). Prevents stealing a human-authored CR by accident. 409
  on mismatch.
- `GET /api/v1/environments/{id}/deployments` — env deployment history,
  ordered descending by `deployed_at`.

**Webhook** (API-key auth):

- `POST /api/v1/webhooks/deployment` — documented above.

## Custom fields integration

Both `Build` and `Deployment` participate in the existing
`custom_field_service` machinery (same paths already used by
`release_change`, `release`, `booking`, `environment`, `system`).

- `CustomFieldDefinition.entity_type` gains two accepted values: `'build'`
  and `'deployment'`. No schema change — validation lists move to include
  these. The admin UI to manage definitions reuses
  `CustomFieldDefinitionsPanel` in Sub-2; Sub-1 relies on the existing
  `POST /api/v1/admin/custom-fields` endpoint accepting them.
- `Build.custom_fields` and `Deployment.custom_fields` are JSONB columns,
  default `{}`.
- Validation happens inside `DeploymentService.ingest` after slugs are
  resolved (so we've already raised 400 for unknown slugs before doing
  the more expensive validation work).
- No subtypes — unlike `release_change` which scopes by `change_kind`,
  build/deployment custom fields are tenant-global.
- Field read on responses is verbatim JSON — same pattern as every other
  custom-field consumer.

## Migration

Single alembic revision:

- Revision id: `p4s1builddeploy`
- Down-revision: `p3s8gateduedate` (current head after MR !17).
- Date: `20260424_1200_p4s1_build_deployment.py`.

Steps (manual DDL, in `upgrade()`):

1. `op.create_table("api_key", …)` + indices.
2. `op.create_table("build", …)` + unique index `(tenant_id,
   subsystem_id, git_sha, build_number)` + FK indices.
3. `op.create_table("deployment", …)` + unique index `(tenant_id,
   event_id)` + FK indices.
4. `op.alter_column("environment_subsystem_version", "build_id",
   new_column_name="build_identifier")` (keep type + nullability).
5. `op.add_column("environment_subsystem_version", sa.Column("build_fk_id",
   sa.Integer(), nullable=True))` + FK + index.
6. Per-tenant upsert of the `Code Deployment` lifecycle template (one
   row per tenant). Written as a data-migration step using the existing
   `lifecycle_template` model — idempotent via "insert if not exists".

`downgrade()` reverses steps 5, 4, 3, 2, 1 and drops the Code Deployment
lifecycle rows. Not going to be run in anger — this is a dev migration.

## Testing strategy

**Unit**

- `api_key_service` — `create_key` returns raw once, stores only the
  hash; `authenticate` rejects deleted/expired/wrong-scope keys.
- `build_service.upsert_build` — inserts new, updates pipeline_steps on
  re-post, validates custom fields.
- `deployment_service.ingest` — one test per status path (pending,
  in_progress, success, failed, rolled_back), idempotency replay, status
  transition table enforcement, unknown-slug 400, missing-event_id 400,
  unknown-custom-field 422.

**Service integration**

- Full webhook round-trip hits the service layer and asserts:
  - `Build` + `Deployment` rows created.
  - `environment_subsystem_version` row inserted on success with correct
    `build_fk_id` and `build_identifier`.
  - CR transitioned to `deployed` / `failed` / unchanged per the status.
  - Correct outbox event emitted (exactly one per ingest).

**HTTP integration** (`backend/tests/integration/test_webhook_deployment.py`)

- Happy path: valid API key, all slugs, status=success → 200, DB rows
  present.
- Replay: same event_id, different `status` → enforces transition table.
- Replay: same event_id, same status → 200 with `replayed: true`, no
  side effects.
- Auth: bad key → 401; wrong scope → 403; JWT instead of API key → 401.
- Custom fields: definitions created, valid payload accepted, invalid
  key → 422.
- CR linking: pass `change_request_id` of a human-authored CR → used;
  omit → auto-created; link-change swap → 409 if swapping a human CR.

**Regression**

- Backend suite must stay at 560+ passing. New tests lift the total by
  ~20–25.

## Rollout

Single MR onto `main` via GitLab. No feature flag (the webhook endpoint
doesn't exist today; turning it on means starting to accept traffic that
doesn't currently exist). The Code Deployment lifecycle seed runs as a
data step inside the migration; existing tenants are back-filled
automatically.

Post-merge action: none — Sub-2 (frontend) picks up next and gives
tenant admins a UI to create API keys. Until Sub-2 ships, tenant admins
can provision keys via the API directly (see `POST /api/v1/api-keys`
endpoint documented above).

## Open decisions

None. All four brainstorming questions answered (two subs /
custom-JSON webhook / dedicated code_deployment lifecycle / Build+
Deployment custom fields) and all inline calls (slugs / idempotency via
`event_id` / subsystem-level builds / rename `build_id` →
`build_identifier` with new FK column / rollback → event only) are locked
in this document.
