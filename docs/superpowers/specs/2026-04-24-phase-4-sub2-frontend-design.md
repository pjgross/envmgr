# Phase 4 Sub-2 — Frontend: Build + Deployment UI + API keys

**Status:** Implemented on `feature/phase-4-sub2-frontend` — awaiting MR merge
**Date:** 2026-04-24
**Phase:** Phase 4 (CI/CD Deployment Tracking), sub-project 2 of 2

## Summary

Frontend surface for Phase 4 Sub-1's backend. Builds and Deployments are
read-only in the UI (they are webhook-created). Admins can create and
revoke API keys. A single write surface exists on the deployment side:
`POST /deployments/{id}/link-change` to swap an auto-created
`code_deployment` CR for a human-authored CR. Deployments are surfaced
alongside bookings and change requests on the existing
`EnvironmentSchedule` (Phase 2) and via new tabs on `EnvironmentDetail`
and `ReleaseDetail`.

## Goals

1. Tenant admins can provision API keys for CI/CD with a one-time reveal
   of the raw key, and revoke them later.
2. Any tenant member can browse Builds and Deployments via top-level nav
   and see detail pages including pipeline steps, custom fields, and
   linked CR state.
3. Deployments appear on `EnvironmentSchedule` and on per-release /
   per-environment detail tabs.
4. Tenant admins can swap the auto-created `code_deployment` CR on a
   deployment for a human-authored CR when required for audit.
5. No write path exists for Builds or Deployments from the UI — those
   records are owned by the webhook.

## Non-goals

- Build form / Deployment form — webhook-only.
- Pipeline step editor or "re-run build" action.
- Frontend-side outbox event viewer (admin-only future work).
- Jira ticket deep resolution — we render external links to Jira,
  nothing fancier.
- Tenant-admin UI for configuring which webhook scopes exist (the set is
  hardcoded in the backend for this release).
- Vitest coverage for every slice/service; smoke tests only.

## Tenant isolation — explicit guarantees

The backend (Sub-1) already enforces strict tenant isolation. The
frontend upholds it by convention:

- **No `tenant_id` in any request body or query string.** Every API call
  from the frontend relies on the JWT's `active_tenant_id` for scoping.
  Do not introduce form fields, selectors, or URL params that let a
  user pick a tenant for the write.
- **API key creation, revoke, and list** hit
  `/api/v1/api-keys` with JWT only. The backend writes
  `tenant_id = current_user.active_tenant_id` on create and filters by
  it on list / revoke.
- **Build + Deployment list/detail** respect the same — the backend
  filters by `active_tenant_id`; the UI never sends a tenant selector.
- **Link-change dialog** posts only the target `change_request_id`. The
  backend verifies both the deployment and the CR are in the caller's
  tenant; a cross-tenant CR id will 400 or 404. The CR autocomplete
  dropdown fetches from the same JWT-scoped `/api/v1/change-requests`
  endpoint, so the user can only see — and therefore only attempt to
  link — CRs in their own tenant.
- **Schedule response** for `/api/v1/environments/{id}/schedule` is
  tenant-scoped at the environment level; the environment itself is
  only addressable by a user in its tenant.

**Verified by integration test** (see *Testing strategy*): log in as
tenant A, create API key + seed a Build and Deployment; log in as tenant
B and assert that none of them are reachable via any list or detail
endpoint, and that attempting to link-change a deployment owned by
tenant A returns 404.

**Maintenance rule** — if a future change introduces a write surface
(new form, new action), reviewers must confirm there is no client-side
tenant selector and that the backend service derives `tenant_id` from
the auth context, not from the payload. Flag any PR that accepts a
`tenant_id` in a write body as a regression.

## Architecture

Two new top-level pages (`BuildList`, `DeploymentList`) plus their
detail pages. One admin page (`ApiKeyManagement`). Four reusable
components. Two existing pages gain a tab (`EnvironmentDetail`,
`ReleaseDetail`). One existing page gets a new event type
(`EnvironmentSchedule`). No routing refactor — we add routes to the
existing `App.tsx` router in the style of Phase 3 additions.

### File structure

```
frontend/src/types/
  apiKey.ts            # ApiKey, ApiKeyCreatePayload, ApiKeyCreated
  build.ts             # Build, PipelineStep, BuildFilters
  deployment.ts        # Deployment, DeploymentStatus, DeploymentFilters

frontend/src/services/
  apiKeyService.ts     # list / create / revoke
  buildService.ts      # list(filters) / get(id)
  deploymentService.ts # list(filters) / get(id) / linkChangeRequest(id, crId)

frontend/src/store/
  apiKeySlice.ts       # thunks: fetchApiKeys, createApiKey, revokeApiKey
  buildSlice.ts        # thunks: fetchBuilds, fetchBuildById
  deploymentSlice.ts   # thunks: fetchDeployments, fetchDeploymentById, linkChange

frontend/src/pages/
  admin/ApiKeyManagement.tsx
  builds/BuildList.tsx
  builds/BuildDetail.tsx
  deployments/DeploymentList.tsx
  deployments/DeploymentDetail.tsx

frontend/src/components/
  apikeys/ApiKeyCreateDialog.tsx       # form: name + scopes + expires_at
  apikeys/ApiKeyCreatedDialog.tsx      # shows raw key once, copy button
  deployments/DeploymentStatusChip.tsx # status → coloured chip
  deployments/LinkChangeDialog.tsx     # autocomplete CR selector
```

Plus targeted edits to:

```
frontend/src/App.tsx                             # new routes
frontend/src/components/AppLayout.tsx            # main nav entries
frontend/src/pages/admin/AdminLayout.tsx         # admin-drawer entries
frontend/src/pages/environments/EnvironmentDetail.tsx  # Deployments tab
frontend/src/pages/environments/EnvironmentSchedule.tsx # render deployments on FullCalendar
frontend/src/pages/releases/ReleaseDetail.tsx    # Deployments tab
```

## Navigation

**Main sidebar** (`AppLayout.tsx`): add two entries, placed alphabetically:

- `Builds` → `/builds`
- `Deployments` → `/deployments`

**Admin drawer** (`AdminLayout.tsx`): add one entry under the existing
**Admin** section (alongside User Management):

- `API keys` → `/tenant/api-keys` (icon: `VpnKeyIcon`)

Admin drawer's **Entity Config** section gains two entries that reuse
the existing `CustomFieldDefinitionsPanel` — the panel is already
generic over `entity_type`:

- `Builds` → `/admin/config/build`
- `Deployments` → `/admin/config/deployment`

## Pages

### `ApiKeyManagement.tsx`

Under `frontend/src/pages/admin/`. Wired to the tenant-admin path
`/tenant/api-keys`.

**Layout** — header with page title + **New key** button, DataGrid
below. Columns: `Name`, `Scopes` (chips), `Created by` (username),
`Last used` (relative time or `—`), `Expires` (absolute date or `Never`),
`Actions` (revoke button → `useConfirm`).

**Flow** — click **New key** → `ApiKeyCreateDialog`. Submit → service
call → dispatch `createApiKey` → on success, open
`ApiKeyCreatedDialog` with the raw key. That dialog has a copy-to-
clipboard button, warning text ("You will not see this key again"),
and a single **I've copied it** dismiss button that closes and refreshes
the list.

**Route** — `/tenant/api-keys` (matches the existing `/tenant/settings`
and `/tenant/users` convention).

### `BuildList.tsx`

Under `frontend/src/pages/builds/`. Top-level route `/builds`.

DataGrid columns: `Subsystem` (from linked System + SubSystem names),
`Branch`, `SHA` (first 8 chars + copy button), `Build #`, `Commit at`,
`Latest pipeline step` (name + status chip — derived client-side from
`pipeline_steps[-1]`). Filters (top bar): `Subsystem` select,
`Branch` text, `Release` select, date-range picker (commit timestamp).
Row click → `/builds/:id`.

### `BuildDetail.tsx`

Route `/builds/:id`. Single-page vertical layout, no tabs.

Sections (top to bottom):

- **Header**: subsystem breadcrumb (System/SubSystem), SHA (copy),
  branch, build number, commit timestamp, linked release (link if set).
- **Pipeline steps** — vertical timeline. Each step shows `name`,
  status chip (uses the same chip palette as DeploymentStatusChip for
  consistency), duration (`finished - started`), clickable to expand
  no-op for now.
- **Jira tickets** — chips, each an external link to
  `{jira_base_url}/browse/{key}` (base URL read from a tenant setting if
  available, else unlinked).
- **Custom fields** — read-only `CustomFieldsSection` with the
  definitions for `entity_type=build` and the build's `custom_fields`
  values.
- **Deployments** — list of `DeploymentSummaryCard`s (small reused
  component or inline) with `Environment`, `Status`, `Deployed at`,
  click → `DeploymentDetail`.

### `DeploymentList.tsx`

Route `/deployments`. DataGrid columns: `Environment`, `Build` (short
SHA), `Status` (chip), `Deployer`, `Deployed at`, `Release`, `CR`.
Filters: `Environment`, `Release`, `Status`, date range.

### `DeploymentDetail.tsx`

Route `/deployments/:id`. Single-page layout.

Sections:

- **Header** — env, build summary (SHA short, build #), release, CR
  summary (title + state chip), `DeploymentStatusChip`, `Deployed at`,
  `Deployer`.
- **Build detail** inline summary, `View full build` link.
- **Change request** — title + current state chip. **Link a different
  change request** button is shown only when the current CR was auto-
  created (determined by checking if its `lifecycle_id` matches the
  Code Deployment template — the frontend fetches this via an existing
  endpoint at detail time). Tooltip explains the rule when disabled.
  Clicking opens `LinkChangeDialog`.
- **Custom fields** — read-only `CustomFieldsSection` for
  `entity_type=deployment`.

## Integration edits

### `EnvironmentDetail.tsx`

Add a new tab labelled **Deployments**. Tab content is a `DeploymentList`-style
DataGrid pre-filtered by this environment. Uses the same
`deploymentSlice` thunk with `environment_id` filter. Tab position:
after **Bookings**, before **Events** (or wherever fits the existing
tab order).

### `ReleaseDetail.tsx`

Add a new tab labelled **Deployments**. Same pattern, filter by
`release_id`.

### `EnvironmentSchedule.tsx`

The Phase 2 FullCalendar timeline currently renders bookings + change
requests. The Phase 4 Sub-1 backend populates `response.deployments[]`
on the schedule endpoint. Map those entries into the calendar's `events`
array alongside the other two types. Event mapping:

```typescript
deployments.map((d) => ({
  id: `deployment-${d.id}`,
  title: `Deploy ${d.build_sha_short} → ${d.status}`,
  start: d.deployed_at,
  end: d.deployed_at,  // point-in-time; render as a diamond
  backgroundColor: deploymentColour(d.status),
  extendedProps: { kind: 'deployment', id: d.id },
}))
```

`deploymentColour` mapping: `success` → `#43a047` (green),
`failed` → `#e53935` (red), `rolled_back` → `#ffb300` (amber),
`pending` / `in_progress` → `#607d8b` (slate). Clicking a deployment
event navigates to `/deployments/:id`.

Bookings stay blue, CRs amber-outline. Legend updated to show the new
colours.

**Note** — the backend's `deployments[]` array from Sub-1 Task 18
currently returns minimal fields (`id, build_id, release_id,
change_request_id, status, deployed_at, deployer_name`). The frontend
may need to do one extra fetch per deployment to get the short SHA for
the title, OR the backend helper can be extended to include
`build_sha_short`. **This spec chooses to extend the backend helper**
in Sub-2 (one-line change to `_get_deployments_for_schedule`) to
include `build_sha` so no N+1 calls are needed.

## Shared components

**`DeploymentStatusChip`** — props `{ status: DeploymentStatus }`.
Renders an MUI Chip with the palette above. Centralised so every
list/detail/calendar uses the same colours.

**`ApiKeyCreateDialog`** — fields: `name` (required), `scopes` (multi-
select; only option for now is `webhooks:deployment` but rendered as a
proper multi-select so adding scopes later is a one-line change),
`expires_at` (date picker, optional — empty = never expires). Submit
button disabled until `name` is non-empty. On success, emits the
created-key payload to the parent.

**`ApiKeyCreatedDialog`** — renders the raw key in a monospace box, a
**Copy** button (uses the `navigator.clipboard` API; toast on success),
a warning paragraph ("This is the only time you will see this key.
Store it somewhere secure."), and a single **I've copied it** button.
Escaping out of the dialog is disabled — the admin must click the
dismiss.

**`LinkChangeDialog`** — autocomplete field fetching from
`/api/v1/change-requests?search=` (the existing endpoint; assumes it
supports a text search — if not, the dialog falls back to paginated
select). Submit calls `linkChange` thunk. Shows a confirmation on
success + updates the deployment detail page.

## State management details

All three new slices follow the Phase 3 pattern: `items` array,
`current` for detail, `loading`/`error` fields, thunks keyed by name.

Filters are carried on the thunks' payloads (`fetchBuilds({ subsystem_id,
branch, release_id, date_from, date_to })`). The list page owns the
filter state locally and re-dispatches on change.

The `DeploymentsTab` components on Env/Release detail don't need their
own slice — they dispatch the same `fetchDeployments` thunk with a
tighter filter. To avoid clobbering each other's `items` arrays, the
tab uses a selector that filters `state.deployment.items` by the
relevant id on render. If that gets awkward, extract a `fetchEnvDeployments`
and `fetchReleaseDeployments` thunks that write to separate sub-state
branches (`state.deployment.byEnvironment`, `byRelease`).

## Backend edits (minor)

Sub-2 includes one backend change beyond Sub-1:

- `_get_deployments_for_schedule` (in
  `backend/app/services/change_request_service.py` — that's where
  `get_environment_schedule` lives, confirmed during Sub-1 Task 18)
  gets a join on `Build` and includes `build_sha_short` (first 8 chars
  of `build.git_sha`) in each returned row. Avoids N+1 on the FullCalendar.

This is the only backend diff in Sub-2.

## Testing strategy

- **Frontend unit/component tests** (vitest):
  - `DeploymentStatusChip` — 5 status → 5 correct colours.
  - `ApiKeyCreatedDialog` — renders raw key, copy button calls clipboard
    API, dismiss closes.
  - `LinkChangeDialog` — disabled state when deployment has human-
    authored CR; enables when it's code_deployment-authored.
- **Backend integration test** added in Sub-2 — cross-tenant probe:
  1. Create two tenants (A, B) with their own admin + api key + build
     + deployment.
  2. Auth as tenant A admin. `GET /api/v1/builds` — only A's build.
     `GET /api/v1/deployments` — only A's. `GET /api/v1/api-keys` —
     only A's.
  3. `GET /api/v1/builds/{B's build id}` → 404.
  4. `GET /api/v1/deployments/{B's deployment id}` → 404.
  5. `POST /api/v1/deployments/{A's deployment id}/link-change` with
     body `{change_request_id: B's CR}` → 400 (target CR not found).
- **Frontend smoke** (manual, documented in the Sub-2 smoke checklist):
  - Create an API key from the admin UI; copy the raw key.
  - Use curl to post a deployment webhook with that key.
  - See the Build + Deployment appear on the respective list pages.
  - Open the EnvironmentSchedule and see the new event.
  - Open ReleaseDetail's Deployments tab and see the deployment.
- **Frontend typecheck** — `npx tsc --noEmit` clean after all changes.

## Rollout

Single MR to `main` via GitLab. Post-merge: the Phase 4 spec can be
marked shipped (both sub-projects merged); Phase 5 scoping is the next
major design task.

## Acceptance criteria

- Admin can create + revoke API keys from `/tenant/api-keys`.
- Raw key is shown once and cannot be re-retrieved.
- `BuildList` and `DeploymentList` load with tenant-scoped data and
  support all documented filters.
- `BuildDetail` shows pipeline steps + custom fields + linked
  deployments.
- `DeploymentDetail` shows build + CR + custom fields + link-change
  dialog (only for auto-created CRs).
- `EnvironmentSchedule` renders deployments as status-coloured events
  with click-through.
- `EnvironmentDetail` and `ReleaseDetail` each have a Deployments tab.
- Cross-tenant integration test passes.
- `npx tsc --noEmit` clean.
- All new components have their documented component tests passing.

## Open decisions

None. Defaults presented during brainstorming accepted; tenant-isolation
concerns addressed in the dedicated section above.
