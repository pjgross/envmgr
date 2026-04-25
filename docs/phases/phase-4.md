# Phase 4: Build Tracking + CI/CD Deployment Tracking

> Status: ✅ **Sub-1 (backend) merged** via MR !20 on 2026-04-23 · ✅ **Sub-2 (frontend + API keys) merged** via MR !21 on 2026-04-25 (merge commit `d802797`) | Roadmap: [../plan.md](../plan.md)
> Both sub-projects on `main`. After the post-merge banner update (MR !22), main tip = `dc5ca92`. Latest alembic revision = `p4s1builddeploy`.
> Backend tests on main: **601 passed, 1 skipped**. Frontend typecheck: clean.

---

## Sub-project 1 — Backend (Build, Deployment, webhook ingest, code-deployment auto-CR) ✅ Merged

Delivered via **MR !20** on 2026-04-23.

| Artefact | Path |
|----------|------|
| Spec | `docs/superpowers/specs/2026-04-23-phase-4-sub1-build-deployment-design.md` |
| Plan | `docs/superpowers/plans/2026-04-23-phase-4-sub1-build-deployment.md` |
| Migration | `p4s1builddeploy` |

### What's delivered

**Data models**
- `ApiKey` — `key_hash` (SHA-256 of the raw secret), `name`, `scopes` (JSONB), `created_by`, `last_used_at`, `expires_at`, soft-delete; raw key shown once on creation, never persisted.
- `Build` — `subsystem_id`, `release_id`, `git_sha`, `git_branch`, `build_number`, `commit_timestamp`, `build_started_at` / `build_finished_at`, `jira_tickets` (JSONB), `pipeline_steps` (JSONB), `custom_fields`, soft-delete.
- `Deployment` — `build_id`, `environment_id`, `release_id`, `change_request_id` (NOT NULL), `event_id` (UUID, idempotency key), `deployer_name`, `deployed_at`, `completed_at`, `status` (`pending | in_progress | success | failed | rolled_back`), `custom_fields`, soft-delete.
- `event_id` modelled as `String(36)` (SQLite test compatibility); enums use `native_enum=False`.

**Services**
- `api_key_service` — `create_key` (returns ORM row + raw secret), `list_keys`, `revoke_key`, `authenticate`.
- `build_service` — `upsert_by_sha` keyed by `(tenant_id, subsystem_id, git_sha)`; merges `pipeline_steps` and `custom_fields` on replay.
- `deployment_service.ingest` — idempotent on `event_id` (replay returns the original record); resolves system/subsystem/environment by slug; auto-creates a `code_deployment` ChangeRequest via the seeded `Code Deployment` lifecycle template if no `change_request_id` supplied; transitions the linked CR (`deploying → deployed | failed`) and records a row in `change_history` for that transition.
- `EnvironmentService.get_environment_schedule` populates the `deployments[]` array (placeholder shape introduced in Phase 2).

**API endpoints**
- `POST /api/v1/webhooks/deployment` — authenticated by API key (`X-Api-Key` header) with `webhooks:deployment` scope.
- `GET /api/v1/api-keys`, `POST /api/v1/api-keys`, `DELETE /api/v1/api-keys/{id}`.
- `GET /api/v1/builds` (filters: `subsystem_id`, `release_id`, `branch`, date range), `GET /api/v1/builds/{id}`.
- `GET /api/v1/deployments` (filters: `environment_id`, `release_id`, `build_id`, `status`, date range), `GET /api/v1/deployments/{id}`, `POST /api/v1/deployments/{id}/link-change`, `GET /api/v1/environments/{id}/deployments`.

**Auth**
- `verify_api_key` dependency for the webhook endpoint; user JWT path unchanged.

**Custom fields**
- `entity_type` accepts `"build"` and `"deployment"`; admin custom-field manager picks them up automatically.

---

## Sub-project 2 — Frontend UI + API keys ✅ Merged

Delivered via **MR !21** on 2026-04-25 (merge commit `d802797`). 18 commits.

| Artefact | Path |
|----------|------|
| Spec | `docs/superpowers/specs/2026-04-24-phase-4-sub2-frontend-design.md` |
| Plan | `docs/superpowers/plans/2026-04-24-phase-4-sub2-frontend.md` |
| Cross-tenant test | `backend/tests/integration/test_phase4_tenant_isolation.py` |

### What's delivered

**Frontend pages and components**
- **API key admin** at `/tenant/api-keys` — list / create / revoke; raw key shown ONCE in `ApiKeyCreatedDialog` with copy-to-clipboard.
- **Top-level Builds**: `/builds` list (subsystem name / branch / SHA / build # / release / commit time / latest pipeline step) with name-based filtering; `/builds/:id` detail showing pipeline steps, jira tickets, custom fields, linked deployments.
- **Top-level Deployments**: `/deployments` list (environment name / build SHA / status / deployer / release / change-request title); `/deployments/:id` detail with build summary + linked CR + relink dialog.
- `LinkChangeDialog` — relink only enabled when the current CR's lifecycle template is `Code Deployment` (i.e. an auto-created CR); human-authored CRs are guarded by a tooltip.
- **Deployments tab** on `EnvironmentDetail` and `ReleaseDetail`.
- **EnvironmentSchedule** (FullCalendar) — deployments rendered as coloured events (`success` green, `failed` red, `rolled_back` amber, in-progress slate); legend chips added; click-through to `/deployments/:id`.
- **Admin EntityConfig** — `build` and `deployment` slugs added to `ENTITY_SLUG_TO_TYPE` and `ENTITY_LABELS`; nav entries in `AdminLayout`.
- Shared `DeploymentStatusChip` component with palette + vitest tests.
- Redux slices: `apiKeySlice`, `buildSlice`, `deploymentSlice` (with `byBuild` cache for build detail page).

**Backend follow-on (in support of the "render names, never `#N` fallbacks" feedback rule)**
- `BuildRead` joins `subsystem` + `release` and returns `subsystem_name`, `release_name`.
- `DeploymentRead` joins `build` + `environment` + `release` + `change_request` and returns `build_sha_short`, `environment_name`, `release_name`, `change_request_title`.
- `_get_deployments_for_schedule` joins `build` and returns `build_sha` + `build_sha_short` so calendar event labels are meaningful.
- New conftest fixture `second_tenant_factory` for multi-tenant test scenarios.

**Tests**
- `test_phase4_tenant_isolation.py` — Tenant A's JWT cannot list/get Tenant B's api_keys / builds / deployments; cross-tenant link-change request → 400.
- Existing schedule deployments test extended to assert `build_sha_short` denormalisation.

---

## Architectural decisions preserved

- **Auto-created `code_deployment` ChangeRequest** uses a dedicated seeded `Code Deployment` lifecycle template (separate from human-authored CRs). Only deployments linked to that template can be relinked via `link-change`; human-authored links return 409 to avoid clobbering decision history.
- **Idempotent ingest** keyed on `Deployment.event_id` (UUID) — webhook retries are safe.
- **Build upsert** keyed on `(tenant_id, subsystem_id, git_sha)` — multiple deployment events from the same SHA replay onto a single Build row, merging `pipeline_steps` + `custom_fields`.
- **Denormalised names on read endpoints** (subsystem / environment / release / change_request title; build SHA short) so the UI never has to render `Env #5` or `SubSystem #2` placeholders. Trade-off: extra joins on list endpoints, accepted because the lists are bounded (default `limit=100`).
- **API keys** are hashed with SHA-256; only the hash is stored. Scopes are JSONB arrays (`["webhooks:deployment"]` is the only scope used today, future-proofed for additional webhook flows).
- **`change_request_id` is NOT NULL on Deployment** — every deployment must be tied to a change record (audit), even if auto-generated.

---

## Deferred / not in this phase

- Jira webhook integration (Phase 3 Sub-3, deferred).
- DORA metrics dashboard, incident tracking, PIR — Phase 5.
- Environment health check dashboard — Phase 5.
- GitHub repository scanning + topology — Phase 6.
- Native enum types in PostgreSQL — kept as VARCHAR with `native_enum=False` to preserve SQLite test compatibility.
