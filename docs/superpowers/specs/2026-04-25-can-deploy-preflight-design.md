# Deployment preflight: `can-deploy` API

**Status:** Spec — implementation in progress on `docs/user-manual-spec` (will rebase or land separately)
**Date:** 2026-04-25
**Phase:** Phase 4 follow-up (Sub-3)
**Driver:** Stakeholder ask — fast CI pipelines must be able to ask "may I deploy?" before deploying, so they don't trample exclusive bookings or active change-request outage windows.

## Summary

Add a single read-only HTTP endpoint:

```
GET /api/v1/webhooks/can-deploy
    ?environment_slug=<slug>
    &subsystem_slug=<slug>
    [&release_id=<int>]
    [&change_request_id=<int>]
    [&booking_id=<int>]
```

Returns `200 OK` with `{ok, blockers, warnings, claim_matched}` so CI can decide whether to proceed. Auth via the existing `webhooks:deployment` scope. Advisory only — there is a race window between preflight and the actual `POST /webhooks/deployment`; documented as such.

## Goals

1. CI pipelines can call the endpoint with a few slugs + optional claim tokens and get an authoritative "can I deploy now?" answer in one round trip.
2. The project that has exclusively booked an environment can keep deploying. Other projects cannot. The mechanism: CI passes `release_id` (or `booking_id`) and the gate matches against the exclusive booking's identity.
3. The response carries enough context (`blockers`, `warnings`, `claim_matched`) that a CI log line tells the human what was checked and why the call was allowed or blocked.

## Non-goals

- Hard locking / reservation tokens. This is **advisory**. The actual gate is still `POST /webhooks/deployment` accepting the deployment record after the fact. Hard locks are a future feature if races become a real problem.
- Booking-level approvals or owner notification.
- Claim via change-request linkage to bookings. The booking model has no `change_request_id` FK today — only `release_id`. CR-based claims would need a model change first; out of scope.
- Time-window queries (e.g. "can I deploy at 14:00 tomorrow?"). Always evaluates "now" (server `datetime.now(timezone.utc)`).
- Any frontend UI. The endpoint is a CI integration only.

## Endpoint contract

### Request

`GET /api/v1/webhooks/can-deploy`

Query parameters:

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `environment_slug` | string | yes | Resolved against the tenant's environments (slug = sluggified name). 404 if not found. |
| `subsystem_slug` | string | yes | Same as above. 404 if not found. |
| `release_id` | int | no | Claim token: "I'm deploying this release." |
| `change_request_id` | int | no | Claim token: "I'm deploying this CR." Useful for logs / future-compat; doesn't unlock exclusive bookings today (no booking↔CR FK). |
| `booking_id` | int | no | Direct claim: "I'm the booking owner." |

Auth: `X-Api-Key` with `webhooks:deployment` scope (same as the deploy webhook).

### Response

`200 OK` always (unless auth fails). The body answers the question; HTTP status is not the gate.

```json
{
  "ok": false,
  "environment_slug": "uat-1",
  "subsystem_slug": "payments-api",
  "checked_at": "2026-04-25T16:42:00Z",
  "blockers": [
    {
      "type": "exclusive_booking",
      "ref_kind": "booking",
      "ref_id": 47,
      "title": "Q2 regression — checkout team",
      "until": "2026-04-26T18:00:00Z"
    }
  ],
  "warnings": [
    {
      "type": "deployment_in_progress",
      "ref_kind": "deployment",
      "ref_id": 199,
      "since": "2026-04-25T16:40:11Z"
    }
  ],
  "claim_matched": null
}
```

When a claim unlocks an exclusive booking:

```json
{
  "ok": true,
  "environment_slug": "uat-1",
  "subsystem_slug": "payments-api",
  "checked_at": "...",
  "blockers": [],
  "warnings": [],
  "claim_matched": {
    "booking_id": 47,
    "matched_via": "release_id",
    "claim_value": 42
  }
}
```

`ok` is `false` if `blockers` is non-empty, otherwise `true`. `warnings` does not affect `ok`.

### Auth failures

- Missing key → `401 Unauthorized`.
- Wrong scope → `403 Forbidden`.
- Resolved slugs don't match a tenant entity → `404 Not Found` with a short message.

## Blocker / warning rules

Evaluated in this order; a single condition can produce one entry. All datetime comparisons use the server's UTC clock.

### Blockers

1. **`environment_inactive`** — emit if `environment.status != "active"`. Includes the current status in the entry (`current_status: "maintenance"`).
2. **`exclusive_booking`** — emit if there exists a non-deleted Booking on this environment such that:
   - `booking.start_date <= now < booking.end_date`
   - `booking.status` is in the "active" set (`approved`, `extension_requested`)
   - `booking.booking_request.exclusive_use_requested = True`
   - and **none** of the claim tokens unlock the booking:
     - `booking_id == query.booking_id`, OR
     - `booking.release_id IS NOT NULL AND booking.release_id == query.release_id`
   If any of those match, the booking is *not* a blocker — instead, surface it in `claim_matched` with `matched_via: "booking_id" | "release_id"`.

3. **`change_request_outage`** — emit if there exists a non-deleted ChangeRequest such that:
   - `cr.has_outage = True`
   - `cr.outage_start <= now < cr.outage_end`
   - The CR is linked to this environment via the env-CR join
   - The CR's `subsystem_id` is NULL OR matches the target subsystem

### Warnings

4. **`non_exclusive_booking`** — same shape as blocker 2 but `exclusive_use_requested = False`. Surfaces context, doesn't block.
5. **`deployment_in_progress`** — emit if there exists a non-deleted Deployment on (env, build's subsystem == target subsystem) with `status in ("pending", "in_progress")` whose `deployed_at` is within the last 30 minutes. Surfaces possible races with another concurrent deploy; doesn't block.

## Implementation outline

- **Schema**: `app/api/v1/schemas/preflight.py` — Pydantic models `CanDeployBlocker`, `CanDeployWarning`, `ClaimMatched`, `CanDeployResponse`.
- **Service**: `app/services/preflight_service.py` — single function `evaluate(db, tenant_id, env_slug, sub_slug, release_id?, change_request_id?, booking_id?) -> CanDeployResponse`. Pure DB reads, no writes.
- **Route**: `app/api/v1/webhooks/preflight.py` — `GET /can-deploy`, mounted under the existing webhooks router. Reuses `api_key_auth(required_scope="webhooks:deployment")`.
- **Tests**:
  - `tests/services/test_preflight_service.py` — 11 unit tests covering each blocker/warning rule, claim matches, all-clear.
  - `tests/integration/test_webhook_can_deploy.py` — 4 HTTP tests for auth (missing/wrong scope), happy path, slug-not-found.

## Acceptance criteria

1. The endpoint exists at `GET /api/v1/webhooks/can-deploy`, requires `webhooks:deployment` scope, and returns a `CanDeployResponse` shaped exactly as specified above.
2. Each of the five blocker/warning rules has at least one direct test that passes.
3. Claim-via-`release_id` and claim-via-`booking_id` both unlock an otherwise-blocking exclusive booking; the response reports `claim_matched`.
4. Admin guide ch. 10 has a new subsection ("Preflight: `can-deploy`") between *Worked example: deployment webhook* and *Idempotency*. Includes the curl, the response shape, and the claim-token guidance.
5. The new endpoint is added to the webhook scope row in admin guide ch. 10's *Available scopes* table.
6. All existing tests still pass.

## Out-of-scope but worth noting

- **Race window**: between the preflight call and the deploy, state can change. The advisory model is documented; if races become a real problem, follow-up work is a short-lived deploy reservation token (CI takes a 5-minute lock, releases on completion or expiry).
- **Booking ↔ CR link**: today bookings have no `change_request_id` FK. If you later want CR-based claims to unlock exclusive bookings, add the FK and extend the claim logic.
