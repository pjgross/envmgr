# Test Environment Coverage — plan test envs from a release's systems

**Date:** 2026-07-27
**Status:** Approved (design) — pending implementation plan
**Builds on:** release-systems (PR #13) — uses `ReleaseSystem.role` (changing/regression/config_only).

## Problem

A release manager knows which systems the release is **Changing** and which need **Regression**
testing (captured on the release's Systems tab). To test, they must book the test environments
that host those systems. Today `AddPhaseBookingDialog` offers a flat dropdown of *all*
environments — nothing tells the RM which environments host the systems they need to test, or
which needed systems have **no** environment at all.

This feature adds the missing **coverage insight**: for a release, show its testable systems
against the environments that host them, flag the gaps, and suggest a set of environments that
covers everything — then let the RM book via the existing dialog. It deliberately reuses the
existing booking flow (which already derives a deployment/regression `context_tag` from the
release-system roles) rather than building new booking logic.

## Decisions (locked)

1. **Testable roles = `changing` + `regression`.** `config_only` systems are excluded from
   coverage.
2. **Coverage insight first.** This spec delivers the coverage view + gap detection + a suggested
   environment set. Booking still goes through the existing `AddPhaseBookingDialog` (with the
   environment pre-selected). Guided multi-env booking is a follow-on.
3. **Any hosting counts as coverage.** An environment covers a system if an `EnvironmentSystem`
   link exists, regardless of mock status. (Mock-aware coverage is a follow-on.)
4. **Placement:** a "Test Environment Coverage" section above the existing Gantt + bookings on the
   release **Environments** tab.
5. **Exclude `DECOMMISSIONED` environments** from candidates; **greedy suggested set** included;
   the **Book** button pre-fills the existing dialog.

## Backend

### Endpoint
`GET /releases/{release_id}/environment-coverage` → `ReleaseEnvironmentCoverageRead`.

### Response schema (`schemas/release.py` or a new `schemas/release_env_coverage.py`)
```python
class CoverageSystem(BaseModel):
    system_id: int
    system_name: str
    role: str  # 'changing' | 'regression'

class CoverageEnvironment(BaseModel):
    environment_id: int
    name: str
    environment_type: str
    status: str
    covered_system_ids: list[int]   # subset of needed system ids this env hosts

class ReleaseEnvironmentCoverageRead(BaseModel):
    needed_systems: list[CoverageSystem]
    environments: list[CoverageEnvironment]     # only envs hosting >= 1 needed system
    uncovered_system_ids: list[int]             # needed systems no env hosts
```

### Query (all tenant-scoped)
1. **needed_systems** — `ReleaseSystem` for the release with `role IN ('changing','regression')`,
   joined to `System` (non-deleted) for the name. If empty, return all three lists empty.
2. **environments** — `EnvironmentSystem` where `system_id IN needed_ids`, joined to `Environment`
   (`deleted_at IS NULL`, `status != DECOMMISSIONED`), grouped by environment; each environment
   carries the subset of needed system ids it hosts.
3. **uncovered_system_ids** — needed ids not hosted by any candidate environment.

Verified models: `ReleaseSystem(release_id, system_id, role, tenant_id)`; `System(id, name,
tenant_id, deleted_at)`; `EnvironmentSystem(environment_id, system_id, tenant_id)` (no status
field); `Environment(name, environment_type, status[enum ACTIVE/INACTIVE/MAINTENANCE/
DECOMMISSIONED], tenant_id, deleted_at)`.

## Frontend

### `ReleaseEnvironmentCoverage` component
New component rendered at the top of `components/releases/ReleaseEnvironmentsTab.tsx` (above the
`EnvironmentResourceGantt` + `ReleaseBookingsTable`). Fetches
`releaseService.getEnvironmentCoverage(releaseId)` into local state.

- **Coverage matrix**: rows = `needed_systems` (system name + a role chip reusing the
  `releaseSystemRoles` map), columns = `environments` (header = `name` + coverage count
  `covered/total`, e.g. `SIT-1 (2/3)`), cell = ✓ where `environment.covered_system_ids` contains
  the row's `system_id`.
- **Gap banner**: when `uncovered_system_ids` is non-empty, show a warning listing those system
  names ("N system(s) need testing but no environment hosts them: …") and highlight those rows.
- **Suggested set**: compute a greedy set-cover over `environments` covering all *coverable*
  needed systems (i.e. excluding the uncovered ones); render "Booking SIT-1 + PERF-1 covers all
  testable systems." When one env covers everything, name just that one; when nothing is coverable,
  omit the line.
- **Book action**: each environment column header has a small **Book** button that opens the
  existing `AddPhaseBookingDialog` with that environment pre-selected (new optional
  `initialEnvironmentId` prop on the dialog). All existing dialog behaviour (phase, booking type,
  dates, context_tag derivation) is unchanged.
- **Empty state**: when `needed_systems` is empty, render a hint: *"Add Changing or Regression
  systems on the Systems tab to plan test environments."*

### `AddPhaseBookingDialog` change
Add an optional `initialEnvironmentId?: number` prop; when provided and the dialog opens,
pre-select that environment in its environment dropdown. No other behaviour changes.

### Types / service (`types/release.ts`, `services/releaseService.ts`)
- Add `CoverageSystem`, `CoverageEnvironment`, `ReleaseEnvironmentCoverageResponse` types.
- Add `releaseService.getEnvironmentCoverage(releaseId): Promise<ReleaseEnvironmentCoverageResponse>`
  → `GET /releases/{id}/environment-coverage`.

## Testing

**Backend** (`tests/integration/test_release_env_coverage_api.py`)
- A release with a Changing system hosted by env A and a Regression system hosted by envs A + B:
  `needed_systems` has both (correct roles); `environments` A and B carry the right
  `covered_system_ids`; `uncovered_system_ids` empty.
- A needed system hosted by no environment → appears in `uncovered_system_ids`.
- A `config_only` system on the release is **excluded** from `needed_systems`.
- A `DECOMMISSIONED` environment hosting a needed system is excluded from `environments`.
- Tenant scope: another tenant's environment hosting the same system id is not returned; the
  endpoint 404s for a cross-tenant release id.
- No changing/regression systems → all three lists empty.

**Frontend** — no unit tests (project convention); verify `tsc --noEmit` + `npm run build`.

## Out of scope (follow-on)
- Guided multi-environment booking from the matrix (select rows/cols → create bookings in one
  flow, with `check_overlap` conflict warnings surfaced).
- Mock-aware coverage (a mocked instance not counting as a real target for a Changing system —
  needs `EnvironmentSubSystem.is_mocked` logic).
- Per-test-phase coverage (which environments each phase needs).
- Auto-creating bookings / booking suggestions beyond the greedy set hint.

## Affected files (indicative)
- `backend/app/api/v1/schemas/release_env_coverage.py` — coverage schemas (create), or add to `schemas/release.py`.
- `backend/app/api/v1/releases.py` — `GET /releases/{id}/environment-coverage` handler.
- `backend/tests/integration/test_release_env_coverage_api.py` — coverage API tests.
- `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx` — new coverage section (create).
- `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx` — render the coverage section on top.
- `frontend/src/components/releases/AddPhaseBookingDialog.tsx` — optional `initialEnvironmentId` prop.
- `frontend/src/types/release.ts`, `frontend/src/services/releaseService.ts` — coverage types + service method.
