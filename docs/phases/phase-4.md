# Phase 4: Build Tracking + CI/CD Deployment Tracking

> Status: ⏳ **Planned** | Roadmap: [../plan.md](../plan.md)
> Duration: 6–8 weeks | Starts after Phase 3 completion

---

## Objectives

- Build entity: versioned software artifact (git SHA, branch, Jira tickets, pipeline steps) — primary DORA data source
- Deployment ingestion from **GitHub Actions** (primary CI/CD tool)
- Link deployments to builds, releases, and change requests
- Automatically update `EnvironmentSubSystemVersion` on successful deployment
- `Deployment.status = rolled_back` triggers optional incident creation prompt
- API key authentication for CI/CD integrations (required for webhook security)
- Extend Phase 2 unified schedule to include deployment events

---

## Backend Tasks

### Data Models & Migrations

- [ ] `ApiKey` model (`backend/app/db/models/api_key.py`)
  - Fields: `key_hash` (SHA-256 of the raw key), `name` (label for display), `tenant_id`, `scopes` (JSONB array of allowed endpoint patterns), `created_by` (user_id), `last_used_at`, `expires_at` (nullable), `deleted_at`
  - Raw key is shown once on creation and never stored; only the hash is persisted

- [ ] `Build` model (`backend/app/db/models/build.py`)
  - Fields: `system_id` (FK → System), `release_id` (nullable FK → Release), `git_sha`, `branch`, `build_number`, `commit_timestamp` (datetime — critical for DORA Lead Time calculation), `jira_tickets` (JSONB array of Jira issue keys), `pipeline_steps` (JSONB array: `{name, status, started_at, finished_at}`), `tenant_id`, `deleted_at`

- [ ] `Deployment` model (`backend/app/db/models/deployment.py`)
  - Fields: `environment_id` (FK → Environment), `release_id` (nullable FK → Release), `build_id` (FK → Build), `change_request_id` (nullable FK → ChangeRequest — phase 4 adds this FK; links deployment to its associated change request), `deployer` (user_id or CI/CD system name), `deployed_at` (datetime), `status` (enum: `pending | in_progress | success | failed | rolled_back`), `tenant_id`, `deleted_at`
  - Deployment linking modes:
    - **Automated**: `DeploymentService.ingest()` auto-creates a `ChangeRequest` (type = `code_deployment`) and sets `change_request_id`
    - **Manual**: CI/CD caller can pass an existing `change_request_id` in the webhook payload to link to a pre-existing change

- [ ] Phase 4 migration also adds FK constraint for `EnvironmentSubSystemVersion.build_id` → `Build` (column was created in Phase 1 migration without constraint)

- [ ] Alembic migrations for all new tables

### Service Layer

- [ ] `ApiKeyService` (`backend/app/services/api_key_service.py`)
  - `create_key(tenant_id, name, scopes)` — generates raw key (returned once), stores hash
  - `authenticate(raw_key)` → `ApiKey` or raise 401
  - `revoke_key(tenant_id, key_id)`
  - `list_keys(tenant_id)`

- [ ] `BuildService` (`backend/app/services/build_service.py`)
  - `create_build(tenant_id, data)` — registers a new build artifact
  - `get_build(tenant_id, build_id)`
  - `list_builds(tenant_id, filters)` — by system, release, branch, date range

- [ ] `DeploymentService` (`backend/app/services/deployment_service.py`)
  - `ingest(tenant_id, payload)` — entry point for GitHub Actions webhook; creates/updates Deployment record
  - `link_change_request(tenant_id, deployment_id, change_request_id)` — manual linking
  - `auto_create_change_request(tenant_id, deployment)` — creates a `code_deployment` ChangeRequest and links it
  - `on_success(tenant_id, deployment_id)` — updates `EnvironmentSubSystemVersion` with the new build
  - `on_rollback(tenant_id, deployment_id)` — emits `DeploymentRolledBack` event (notification consumers can prompt incident creation)
  - `list_deployments(tenant_id, filters)` — by environment, release, build, status, date range
  - `get_environment_deployments(tenant_id, env_id, start_date, end_date)` — for schedule endpoint extension

- [ ] Extend `EnvironmentService.get_environment_schedule()` (Phase 2) to include deployments in the response (populates the `deployments: []` array introduced in Phase 2)

### Authentication

- [ ] `ApiKeyMiddleware` (`backend/app/core/auth.py`) — authenticate requests using `X-Api-Key` header; used on webhook endpoints; falls back to JWT for user-facing endpoints
- [ ] Webhook endpoint `POST /api/v1/webhooks/github/deployment` requires API key auth; all other endpoints remain JWT

### API Endpoints

- [ ] `backend/app/api/v1/api_keys.py`
  - `GET /api/v1/api-keys` — list keys (hash + metadata; not raw key)
  - `POST /api/v1/api-keys` — create (returns raw key once)
  - `DELETE /api/v1/api-keys/{id}` — revoke

- [ ] `backend/app/api/v1/builds.py`
  - `GET /api/v1/builds` — list (system, release, branch, date filters)
  - `POST /api/v1/builds` — register build
  - `GET /api/v1/builds/{id}` — build detail (includes pipeline steps, linked deployments)

- [ ] `backend/app/api/v1/deployments.py`
  - `GET /api/v1/deployments` — list (env, release, build, status, date filters)
  - `GET /api/v1/deployments/{id}` — deployment detail (build info, change request link, environment)
  - `POST /api/v1/deployments/{id}/link-change` — manually link to a ChangeRequest
  - `GET /api/v1/environments/{id}/deployments` — deployment history for an environment

- [ ] `backend/app/api/v1/webhooks/github.py`
  - `POST /api/v1/webhooks/github/deployment` — GitHub Actions deployment event receiver (API key authenticated)
  - Verifies GitHub webhook signature (HMAC-SHA256)
  - Routes to `DeploymentService.ingest()`

### Events

- [ ] `DeploymentStarted`, `DeploymentCompleted`, `DeploymentFailed`, `DeploymentRolledBack`
- [ ] Notification consumer: on `DeploymentRolledBack`, send alert to release manager and environment owner with a prompt to raise an incident

---

## Frontend Tasks

### Services & State

- [ ] `frontend/src/services/buildService.ts` — build CRUD API calls
- [ ] `frontend/src/services/deploymentService.ts` — deployment list, detail, link API calls
- [ ] `frontend/src/services/apiKeyService.ts` — API key management
- [ ] `frontend/src/store/buildSlice.ts`
- [ ] `frontend/src/store/deploymentSlice.ts`

### TypeScript Types

- [ ] `frontend/src/types/build.ts` — `Build`, `BuildCreate`, `PipelineStep`
- [ ] `frontend/src/types/deployment.ts` — `Deployment`, `DeploymentStatus`, `DeploymentCreate`
- [ ] `frontend/src/types/apiKey.ts` — `ApiKey`, `ApiKeyCreate`

### Pages & Components

- [ ] `frontend/src/pages/BuildList.tsx` — list with system, release, branch, date filters
- [ ] `frontend/src/pages/BuildDetail.tsx` — build info, pipeline steps timeline, linked deployments
- [ ] `frontend/src/pages/DeploymentList.tsx` — list with status and environment filters
- [ ] `frontend/src/pages/DeploymentDetail.tsx` — linked build, release, environment, change request; rollback history
- [ ] Deployment history timeline component (reusable; used on EnvironmentDetail and ReleaseDetail)
- [ ] `frontend/src/pages/ApiKeyManagement.tsx` — admin: list keys, create (shows raw key once), revoke
- [ ] Add **Deployments** section to `EnvironmentDetail.tsx` and `ReleaseDetail.tsx`
- [ ] Show deployments on the unified `EnvironmentSchedule.tsx` timeline (Phase 2 component) as a third item type alongside bookings and TECRs

---

## Acceptance Criteria

- [ ] `POST /api/v1/webhooks/github/deployment` correctly creates Build + Deployment records from a GitHub Actions event payload
- [ ] On successful deployment, `EnvironmentSubSystemVersion` is updated with the new `build_id`, `version_label`, and `installed_at`
- [ ] `Deployment.change_request_id` is set on creation (automated) or via `POST /.../link-change` (manual)
- [ ] Rolled-back deployment emits a `DeploymentRolledBack` notification to the release manager
- [ ] `GET /api/v1/environments/{id}/schedule` response includes `deployments` array populated with deployment events (extends Phase 2 endpoint)
- [ ] API key authentication works: valid key grants access to webhook endpoint; invalid key returns 401; JWT endpoints are unaffected
- [ ] DORA-critical fields present: `Build.commit_timestamp`, `Deployment.deployed_at`, `Deployment.status`
- [ ] All service methods have unit tests; all API endpoints have integration tests
- [ ] Tenant isolation verified: builds and deployments from one tenant are never accessible to another
