# Phase 9 C2 — Typed gates, evidence and waivers

> Status: design approved 2026-08-19. The first sub-project of Phase 9 to be
> built, though not the first in lifecycle order — see §9 for the phase
> decomposition and why this one goes first.
>
> Phase 9 was decomposed into nine clusters (C1–C9) because
> [requirements.md §2.11](../../requirements.md) is roughly 48 capability rows,
> Phase-7-sized or larger. The labels are lifecycle order, not build order.

## 1. The problem

Release gates already exist and are already used. `ReleaseGate` carries a name,
a due date, a status (`pending` / `passed` / `failed` / `overridden`), and who
decided it when and why; `GateCriterion` hangs a checklist off it with an
assignee or an assigned role. Templates materialise gates when a release is
created, and `release_service` auto-creates the Scope Sign-off gate.

Three things are missing, and they compound.

**A gate has no type**, so nothing can distinguish a security sign-off from an
accessibility check, and there is nowhere to declare how a failure behaves.
§2.11 asks for typed gates with per-gate failure behaviour — block, warn, or
accept-with-exception — and the model has no room for the question.

**A gate has no evidence.** The only record that a gate was genuinely satisfied
is free text in `decision_notes`. Phase 12's evidence pack has nothing to
gather.

**A waiver is an unstructured override.** `override_gate` sets the status and
demands notes; there is no approver rule, no expiry and no remediation. A gate
waived once is waived for ever, and nothing ever comes back to ask.

Compounding them: `pass_gate` does not check open criteria, so a gate can be
passed with its checklist untouched, and nothing anywhere reads gate state —
`lifecycle_service` never references `release_gate`. **Gates are records that
stop nothing and prove nothing.**

## 2. What C2 does, and the limit of it

C2 gives a gate a tenant-configurable **type** that declares its failure
behaviour and the evidence it expects; makes **evidence** structured and linked
to the deployment it vouches for; and replaces the informal override with a
**waiver** carrying an approver, an expiry and a remediation note.

**C2 refuses nothing.** No release transition is blocked. `can-deploy` is not
touched — not one blocker, not one warning. This is the same promise A3, A4, B2
and B4 each made, and it is guarded the same way, by a named test (§6).

**But the verdict is machine-readable.** The UI advises; a DevOps pipeline can
ask directly, through a new endpoint that answers and does not act. EnvManager
never refuses a deployment; it answers a question the pipeline chose to ask, and
the pipeline enforces. That is the standing architectural boundary — Phase 4
tracks deployments rather than running them, §6 of requirements.md puts
provisioning pipelines out of scope as "future REST API integration by customer
tools — not built by EnvManager", and B5 made the identical call about teardown.

**Evidence is a reference, never an artefact.** This application has no file
storage: the only `UploadFile` anywhere is the spreadsheet import, parsed in
memory and never persisted. Evidence is a URL plus an attestation of who
vouched for it and what deployment it concerns. Building a blob store to hold
test reports is a different project, and Phase 12 wants evidence *indexed* for
audit rather than *held*.

## 3. The data model

### 3.1 `gate_type` — tenant-configurable, seeded with the eight

Shaped exactly like `environment_tier`, which B1 introduced for the same reason:
a standard vocabulary that real tenants do not quite match. The eight types from
§2.11 — functional, NFR/performance, integration, security, license,
accessibility, business, ops-readiness — are seeded per tenant with a
`category`; a tenant's own types leave `category` NULL. Name uniqueness is
enforced **in the service**, not by a partial unique index, which is inert on
SQLite — the same call `environment_tier` and `user_group` made.

Columns beyond the usual tenant/name/category/`is_active`/`deleted_at`:

- **`failure_behaviour`** — `block` / `warn` / `accept_with_exception`, a
  `native_enum=False` VARCHAR like every other enum here.
- **`expected_evidence`** — a JSON list of evidence *kind* names, e.g.
  `["Test execution report", "Defect summary"]`. Empty means none expected.
- **`requires_deployment_link`** — whether evidence of this type must name a
  deployment.

**This is where the strictness ladder lives.** The requirement is that a test
sign-off demands more as a release climbs SIT → UAT → PreProd → Production. That
is expressed by a "UAT Sign-off" type expecting more kinds than "SIT Sign-off",
with a tenant's release template materialising the right one per phase.
Strictness is real but **emergent** — there is no second policy engine keyed on
(type, tier) that could drift out of step with the templates that actually
create the gates.

### 3.2 `release_gate` — two nullable columns, no backfill

- **`gate_type_id`** — nullable. Every existing gate stays valid as *untyped*,
  and untyped is a state the verdict handles explicitly (§4.1).
- **`test_phase_id`** — nullable, because **most gates have no phase**. Scope
  Sign-off is created early and belongs to no test phase; a Go/No-Go gate sits
  at the end and belongs to none either. Only test sign-off gates carry one.

Note what is deliberately *absent*: the gate has **no environment or tier
scope**. It does not need one. Staleness is computed from the environment on
the evidence's own deployment link (§4.2), so putting a tier on the gate would
add a second, redundant answer to "which environment is this about".

### 3.3 `gate_evidence`

`gate_id`, `kind`, `label`, `url`, `notes`, a nullable `deployment_id`,
`added_by`, `added_at`, `deleted_at`.

`kind` is **free text**, not a foreign key. The UI offers the type's
`expected_evidence` entries as the choices, but evidence of an unlisted kind is
accepted — it simply satisfies no expectation. "Expected kinds missing" in §4.1
is an exact-name comparison between the type's `expected_evidence` list and the
`kind` values present on the gate.

Evidence attaches to the **gate**, not to a criterion. The gate is the unit that
passes or fails, the unit the pipeline verdict names, and the unit Phase 12 will
package — so the evidence pack is one join rather than two. Criteria keep their
existing `notes` for working detail.

The `deployment_id` link is what makes evidence worth more than a bookmark. The
chain already exists end to end and C2 builds none of it:

**subsystem (the component) → `build` (git SHA + build number) → `deployment`
(into an environment, carrying `release_id` and a mandatory
`change_request_id`)**

So a deployment is already documented as a change linked to a release, and it
already pins which version of which component landed where and when. An evidence
row naming a deployment inherits all of it: not "here is a test report" but
"this test report concerns build `abc123` of Payments, deployed to UAT on the
14th".

### 3.4 `gate_waiver`

`gate_id`, `reason`, `approved_by_user_id`, `expires_at` (NULL means no
expiry), `remediation`, `created_by`, `created_at`, `deleted_at`.

Rows **accumulate as history**; the latest live one is current. Re-waiving after
an expiry must not overwrite the previous approver and reason — destroying that
history would destroy the one thing the waiver exists to create, and Phase 12
wants it.

Whether a waiver is live or expired is **computed on read** from `expires_at`,
never stored. A4's escalation and B5's decommission both took this shape: no
status column to invalidate, no scheduler, nothing to reconcile. The comparison
goes through `expiry_boundary` in `app/core/day_boundaries.py`, because **a
deadline is a day** — at instant precision a waiver expiring today reads as
expired from one minute past midnight, which is the exact bug A4 shipped and B2
inherited.

`override_gate` becomes the path that writes a waiver row. Existing
`overridden` gates keep their status and simply have no waiver row, rendering
as "waived, no expiry recorded".

## 4. The verdict — one evaluator, two surfaces

`gate_readiness_service.evaluate(release_id)` is the only place the rules live.
The UI panel and the pipeline endpoint both call it, so they cannot disagree —
A3's rule that one predicate decides and everything else derives from it. A gate
chip contradicting the endpoint a pipeline obeys would be worse than neither.

**`GET /api/v1/webhooks/release-ready?release_id=`** mirrors `can-deploy`
exactly: API-key auth, read-only, no writes, and **always 200 with a structured
body** — that endpoint's docstring states the contract outright, *"HTTP status
is not the gate"*, and this one inherits it.

It takes a **new scope, `webhooks:release`**, rather than reusing
`webhooks:deployment`. Reusing it would silently widen what every existing
deployment key can read to include governance detail — waiver reasons, approver
names, evidence URLs. The cost is granting the scope once per pipeline, and that
is the right trade.

### 4.1 The rules

A waiver and a failure are **mutually exclusive states, not overlapping ones**.
`override_gate` sets `status = "overridden"`, so a gate is failed *or* waived
and never both; the rules key on status and waiver together.

| Gate state | Result |
|---|---|
| `pending`, type behaviour `block` | blocker |
| `failed` | blocker — a failure is not waived, it is failed |
| `overridden`, waiver expired | blocker — the gate is unmet again |
| `overridden`, waiver live | warning, naming approver and expiry |
| `overridden`, **no waiver row** (legacy override) | warning — "waived, no expiry recorded" |
| `passed`, expected evidence kinds missing | warning |
| Evidence stale | warning, naming both deployments |
| Type behaviour `warn` or `accept_with_exception` | warning |
| Gate **untyped** | warning — no behaviour was declared, so none is invented |

To waive a failed gate you override it, which is the existing path and the
existing status transition. C2 adds the record, not a new state.

The untyped row matters on day one: `gate_type_id` ships nullable with no
backfill, so **every gate in every existing tenant is untyped until someone
types it**. Inventing `block` for them would turn on a wall of blockers nobody
configured; inventing `warn` is the honest reading of "nobody has said".

### 4.2 Staleness

Evidence links deployment *D* — build of subsystem *S* into environment *E* at
time *T*. The evidence is **stale** if a later **successful** deployment of *S*
into *E* exists.

Successful is load-bearing. A failed redeploy must not invalidate evidence that
still correctly describes what is running; `Deployment.status` decides, and
soft-deleted deployments are excluded.

This is the whole value of the deployment link. A QA sign-off recorded against
build 41 and then quietly undermined by a hotfix deploying build 42 is exactly
the failure the paperwork exists to prevent, and today nothing anywhere notices.
It is computed on read, never stored — a stored staleness flag would be
falsified by the next deployment webhook.

### 4.3 `ok` is derived, never stored

The response carries `ok`, `blockers` and `warnings`, mirroring
`CanDeployResponse` exactly — including `ok`, which `preflight_service`
computes in one place as `ok=len(blockers) == 0`.

A convenience boolean that could *disagree* with its own array would be two
sources of truth for one question, the shape this codebase has regretted
repeatedly. Derived in a single expression at the point of construction, it is
not: `ok` cannot drift from `blockers` because it is `blockers`. A pipeline
tests `ok`; anything wanting detail reads the array.

## 5. Surfaces

The release detail gates panel gains a type chip, the evidence list with
staleness markers, and a waiver chip showing approver and expiry. The bare
"override notes" prompt becomes a waiver dialog taking reason, approver, expiry
and remediation. Evidence is added by choosing a kind from the type's expected
list, a URL and a label, and picking a deployment from the release's own
components. Admin gets a Gate Types panel alongside Component Types and Booking
Types.

Two house rules the frontend half must honour: mutating thunks
`rejectWithValue(formatApiError(err))` and the panels read `result.payload`, or
a refused save shows an HTTP status instead of the reason; and any new grid
column namespaces custom fields `cf_<key>` so a tenant field keyed `waiver` or
`evidence` cannot collide with a static column id.

## 6. Testing

**`test_c2_advises_never_blocks.py` is the guard on the central promise**, in
the line of A3, A4, B2 and B4. A release with a failed `block` gate still
transitions; `can-deploy` answers byte-identically with and without gate state;
no write path refuses on gate state. It is proved non-vacuous by inserting a
real refusal into the transition path and watching it fail — an absence test
nobody has tried to break is not evidence of anything.

Beyond it:

- Staleness in **both** directions, including the failed-redeploy case that must
  *not* mark evidence stale.
- Waiver expiry **on the boundary day itself** — the waiver is still live on its
  expiry date, and expired the day after.
- The panel and the endpoint call the same evaluator, so they cannot diverge.
- Untyped gates produce warnings, never blockers.
- Tenant isolation on all four new tables. Assume every filter is unguarded
  until a named test fails without it: A1 shipped eight missing `tenant_id`
  filters that no pre-existing test caught.

Both engines. The frontend suite is a third run, not an afterthought.

## 7. Migration and deploy

Additive: three new tables (`gate_type`, `gate_evidence`, `gate_waiver`), two
nullable columns on `release_gate`, no backfill. Hand-written DDL —
`--autogenerate` sees nothing, because `init_db()` calls `create_all`.

**The eight seeded gate types need a per-tenant seeding function, and that is a
deploy step for existing tenants**, exactly as B3b's `envrequests` revision was.
A tenant with no seeded types has no vocabulary to type a gate with, and the
whole feature reads as broken rather than unconfigured.

Note that `tests/test_migration_schema_drift.py` compares **column name sets
only** — not types, defaults or indexes. Its passing is not evidence that this
migration matches these models.

## 8. Out of scope

- **Go / No-Go decision record** — C3. It reads gate outcomes, which is why C2
  goes first.
- **Rollback governance** — C4, including the rehearsal gate, which will be a
  `gate_type` row and needs nothing further from C2.
- **Risk-driven gate applicability** — C1. Which gates apply to which release is
  the intake sub-project's decision; C2 only declares what a gate *is*.
- **Evidence pack export** — Phase 12 assembles it; C2 makes it assemblable.
- **Blocking any transition, or altering `can-deploy`** — §2.
- **File upload** — §2.
- **A gate approver permission rule.** Who may pass, fail or waive stays on
  today's coarse roles. Separation of duties is Phase 12 and waits on the
  RBAC/OAuth upgrade.

## 9. The rest of Phase 9

The nine clusters, with what already exists. C2 ships first because it is the
least new surface for the most leverage: it extends entities that already exist,
and C1, C3, C4 and C5 all lean on the gate model.

| # | Cluster | Already there | Depends on |
|---|---|---|---|
| C1 | Intake + risk scoring | `environment_request`'s request-on-a-lifecycle-template pattern | C2 (risk selects gate types) |
| C2 | **Typed gates, evidence, waivers** | `ReleaseGate`, `GateCriterion`, templates | — |
| C3 | Go/No-Go decision record | nothing | C2, C4 |
| C4 | Rollback governance | nothing | C2 (rehearsal is a gate) |
| C5 | Deployment execution records | Phase 4 tracking, `can-deploy` | C2 (pre-deploy checklist is a gate) |
| C6 | Hyper-care + closeout | Phase 5 SP4 PIR is the retro half | C3 |
| C7 | Scope freeze completion | `scope_deadline`, Scope Windows, churn analytics — most of it | — |
| C8 | Feature-flag governance | nothing | — |
| C9 | Stable Windows | `can-deploy` to extend | — |

**C9 has an open question this spec does not settle**: whether a Stable Window
appears as a `can-deploy` blocker. Doing so would make EnvManager refuse
something for the first time, which is the enforcement boundary deliberately
declined here. It is C9's call to make, not C2's to assume.
