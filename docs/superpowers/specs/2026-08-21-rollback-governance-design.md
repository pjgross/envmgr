# Phase 9 C4 — Rollback governance

> Status: design approved 2026-08-21. The second Phase 9 sub-project to be
> built, after C2 (typed gates, evidence and waivers).
>
> Gated on C2, which built the readiness verdict this extends. C3 (Go/No-Go)
> is gated on C4: its mandatory question is *"have you tested the rollback?"*,
> which needs a rollback plan and a rehearsal record to point at.

## 1. The problem

[requirements.md §2.11](../../requirements.md) asks for four things, and
EnvManager has none of them:

> **Rollback governance**: documented rollback plan agreed **before** deploy;
> data-reversibility flags surfaced at Plan time; in-flight rollback
> authorisation recorded (time, trigger, rationale); rollback rehearsal tracked
> as a gate.

What exists today is the *fact* of a rollback and nothing else.
`Deployment.status` carries `rolled_back`, reachable from both `success` and
`failed`, and flipping to it publishes a `DeploymentRolledBack` event. So the
register knows a rollback happened. It does not know whether anyone had a plan,
whether the change could be reversed at all, who decided to pull the trigger,
why, or whether the procedure had ever been tried before the night it was
needed.

The gap that matters most is **data reversibility**. A stateless API rolls back
by redeploying the previous artefact; a schema migration may be one-way, or
reversible only if you accept losing everything written since the deploy. Today
that distinction lives in the heads of whoever wrote the migration, and it
surfaces — if at all — in the middle of an incident.

## 2. What C4 does, and the limit of it

C4 records four connected facts: a **plan** per changing component, a
**reversibility** verdict that rolls up to the release, an **authorisation**
record when a rollback actually happens, and a **rehearsal** record per system
whose freshness is computed. All four feed C2's existing readiness verdict.

**C4 executes nothing and refuses nothing.** EnvManager does not roll anything
back — CI does — and it must never stand between a team and a recovery at 2am.
The standing boundary set for Phase 9 holds: this application is a register that
records governance facts and answers questions, never an executor. Phase 4
tracks deployments rather than running them, §6 of requirements.md puts
provisioning pipelines out of scope, and B5 made the identical call about
teardown.

`tests/test_c4_records_never_refuses.py` is the guard, in the line of A3, A4,
B2, B4 and C2 (§6).

## 3. The data model

Four tables. No new columns on any existing entity.

### 3.1 `release_rollback_plan` — one row per (release, system)

Created only for components whose `release_system.role` is `changing` or
`config_only`. A `regression` component is not being changed, so it has nothing
to roll back and needs no row — and, importantly, produces no findings (§4).
That the role vocabulary already exists (`changing` / `regression` /
`config_only`) is why the plan attaches per component rather than per release.

- `steps` — text, the actual procedure
- `reversibility` — `reversible` | `lossy` | `irreversible`, a plain VARCHAR
  like every other enum here (`native_enum=False` semantics)
- `estimated_minutes` — nullable
- `notes` — nullable
- `agreed_by_user_id` + `agreed_at` — **both nullable**, and the distinction is
  load-bearing: §2.11 asks for a plan *agreed before deploy*, so "written" and
  "agreed" are two different states and an unagreed draft is legitimate
- Unique on `(release_id, system_id)`; tenant-scoped; soft-deleted

**The three reversibility values, and why the middle one exists.** `reversible`
means roll back and lose nothing. `irreversible` means no rollback exists — only
roll forward. **`lossy` is the value that earns its place**: teams routinely
call a change "reversible" when they mean "reversible if you accept losing an
hour of writes", and that is exactly the distinction a business sponsor needs at
go/no-go. A boolean forces it into one of the extremes, and either choice lies.

The vocabulary is **fixed, not tenant-configurable** — unlike `gate_type`,
`environment_tier` or `booking_type`. Reversibility is a property of a database
migration, not of a tenant's process, and a tenant-defined vocabulary could not
be reasoned about by any shared rule (§4's rollup would have nothing to order).

### 3.2 `release_rollback_authorisation` — raised when a rollback happens

- `release_id`, `decided_by_user_id`, `decided_at`, `trigger` (what went wrong),
  `rationale`
- `system_ids` — a **JSON list of system ids**, not a junction table. The set is
  small, it is never queried *from* the system side, and this codebase already
  stores such lists as JSON (`expected_evidence`, `pipeline_steps`,
  `jira_tickets`). Names are resolved through the existing batch name lookups at
  render time, which — following the rule A1 established and A4 restated —
  deliberately do **not** filter `deleted_at`: an archived system still renders
  its name on the rollback it was part of.
- The ids are validated against the release's own `release_system` rows on
  write, so an authorisation cannot name a system the release never touched.
  Validation is on the ids only; it never inspects plan state.
- Raisable **before or after the fact**

**Deliberately not attached to `Deployment`.** A rollback may span several
deployments, and the CI webhook that flips a deployment to `rolled_back` knows
the *what* but never the *why* — no trigger, no rationale, no named human, which
is precisely the content §2.11 asks for. Deriving the record from the status
change would produce an audit trail missing everything that matters.

**It never gates the rollback.** Requiring authorisation before a deployment may
move to `rolled_back` would mean the register refusing to record something that
has already happened in production, which produces a register that disagrees
with reality — worse than no record.

### 3.3 `rollback_rehearsal` — per system, not per release

- `system_id`, `rehearsed_at`, `rehearsed_by_user_id`, `outcome`
  (`passed` | `failed` | `partial`), `notes`
- Rows **accumulate as history**; the latest is current — the shape
  `gate_waiver` already uses

A rehearsal proves you can roll back *a system*, and that stays true for a
while. It is not per-release: one rehearsal serves every release that touches
that system until it goes stale. Modelling it as a per-release gate would ask a
team to re-assert per release something true per system for a quarter, which is
how gates become rubber stamps.

Freshness is **computed on read** — `rehearsed_at + validity` compared through
`expiry_boundary` — never stored. No status column, no scheduler, nothing to
invalidate: the call A4's escalation state, B5's decommission state and C2's
waiver state all made. **A deadline is a day**, so a rehearsal is current all
through its final day.

### 3.4 `rollback_policy` — one row per tenant

Shaped like `RaidConfig` and `environment_naming_policy` (`tenant_id` unique):

- `require_rollback_plan` — default **false**
- `require_current_rehearsal` — default **false**
- `rehearsal_validity_days` — default **90**

**Both requirements default off, deliberately.** Every release that predates C4
has no rollback plans at all. C2 learned this exact lesson: `gate_type_id`
shipped nullable so every existing gate was untyped, and inventing `block` for
them would have turned on a wall of blockers nobody configured. B5 made the same
call with idle detection defaulting off per tenant. A banner that is red for the
whole estate on day one teaches everyone to ignore the banner.

### 3.5 The release-level rollup is computed, never stored

The release's reversibility is the **worst** across its changing components, so
one `irreversible` component makes the release irreversible. Storing it would be
falsified the moment any component's plan changed — the same reason C2 computes
staleness and waiver state on read.

## 4. Verdict integration

**`gate_readiness_service` becomes `release_readiness_service`.** Its verdict is
no longer only about gates, and a name that lies about its scope is how the next
reader gets it wrong. Both routes keep their paths —
`GET /api/v1/releases/{id}/readiness` (JWT) and
`GET /api/v1/webhooks/release-ready` (API key, scope `webhooks:release`) — since
the endpoints were always release-shaped; only the service was gate-shaped.
C2's tests move with it.

This is the one place rollback findings appear. C2's central rule holds: **one
evaluator, and nothing recomputes any part of a verdict independently.** A
second rollback-readiness endpoint would give a pipeline two things to call and
two definitions of ready — the shape this codebase has repeatedly regretted.

### 4.1 The five new findings

| Finding | Severity |
|---|---|
| `rollback_plan_missing` — a `changing`/`config_only` component with no plan row | blocker if `require_rollback_plan`, else warning |
| `rollback_plan_unagreed` — plan written, never agreed | blocker if `require_rollback_plan`, else warning |
| `rollback_irreversible` — a component whose reversibility is `irreversible` | **always a warning** |
| `rollback_lossy` — reversibility is `lossy` | always a warning |
| `rehearsal_stale` / `rehearsal_missing` — a changing component's system has no current rehearsal | blocker if `require_current_rehearsal`, else warning |

**`rollback_irreversible` must never be a blocker, whatever the policy says.** A
one-way migration is a normal thing to ship; the requirement is that it is
*surfaced at plan time*, not that it is forbidden. Making it an error would push
teams to record irreversible changes as reversible to clear the banner,
destroying the one signal the flag exists to carry.

`regression` components produce **no findings at all** — they are not being
changed.

### 4.2 Batching and the clock

Every lookup is batched **once per response**, never once per component, and one
clock decides every freshness comparison in the payload — called per row, two
components could disagree about what day it is. Both rules are C2's, and C2 ships
tests pinning them (`latest_waivers_for_gates` and `criteria_reads_for_gates` are
each asserted to be called once for a multi-gate page); C4 adds the equivalent.

## 5. Surfaces

**Release detail — a Rollback panel.** One row per changing component: steps, a
reversibility chip, estimated time, and who agreed it or an *Agree* action.
Above them the release-level rollup — *"This release contains an irreversible
change"* is the sentence a sponsor needs at go/no-go. Below, any authorisations
recorded against the release.

**The readiness banner needs no work.** It already renders whatever the verdict
returns, so rollback findings appear the moment the service emits them. That is
the dividend of extending one verdict rather than adding a surface.

**"Record a rollback"** — an action on the release capturing decider, time,
trigger, rationale and affected systems. Always available, gated on nothing,
explicitly usable after the fact.

**System detail — a Rehearsals panel.** History plus the current one's freshness.
Rehearsals belong to the system, not to any release.

**Admin — a Rollback policy panel.** Two toggles and the validity period, with
copy stating plainly that enabling `require_rollback_plan` converts warnings into
blockers **in the verdict** and still refuses nothing.

House rules the frontend must honour: mutating thunks
`rejectWithValue(formatApiError(err))` with callers reading `result.payload`;
`<Select aria-label>` lands on the root node, so use
`inputProps={{ 'aria-label': ... }}`; and any new grid column namespaces custom
fields `cf_<key>`.

## 6. Testing

**`test_c4_records_never_refuses.py` is the guard on the central promise.** A
rollback authorisation can be recorded for a release with no plan; a deployment
still moves to `rolled_back` regardless of plan state; a release with missing
plans still transitions; `can-deploy` answers identically with and without
rollback state. Proved non-vacuous by inserting a real refusal and watching it
fail — an absence test nobody has tried to break is not evidence of anything.

Beyond it:

- The rollup is **worst-wins** across components, and `irreversible` never
  blocks even with policy on.
- Rehearsal freshness at the day boundary in **both** directions — current on
  the final day, stale the day after.
- Policy off yields warnings, policy on yields blockers — both directions
  tested, since a policy read backwards is invisible in one direction.
- `regression` components produce no findings.
- Tenant isolation on all four tables, **each proved by mutation**. Assume every
  filter is unguarded until a named test fails without it: A1 shipped eight
  missing `tenant_id` filters that no pre-existing test caught, and C2's final
  review found a staleness predicate whose three filters could all be deleted
  with the whole gate suite still green.

Both engines. The frontend gate is **lint + test + build**, not vitest and `tsc`
alone — CI caught C2's merge commit on an unused `eslint-disable` because
`npm run lint` runs `--report-unused-disable-directives --max-warnings 0`.

## 7. Migration and deploy

Additive: four new tables, no columns on existing entities, no backfill.
Hand-written DDL — `--autogenerate` sees nothing, because `init_db()` calls
`create_all`. `Base` supplies `created_at`/`updated_at`; omitting them from a
`CREATE TABLE` is a real defect that has bitten six tables here.

`rollback_policy` is seeded on tenant creation **and** read through a
get-or-create that returns defaults, so an unseeded tenant behaves correctly
rather than erroring. **There is no deploy step** — unlike B3b's `envrequests`,
and unlike what C2's docs initially and wrongly claimed.

## 8. Out of scope

- **Post-deploy verification triggering a rollback, traffic ramps, deploy
  patterns** — C5.
- **The "have you tested the rollback?" go/no-go question** — C3, which reads
  C4's rehearsal freshness rather than re-deriving it.
- **Executing a rollback** — permanently out of scope; EnvManager holds no
  credentials and no way to know the record still corresponds to anything
  running.
- **Rehearsal scheduling or reminders** — there is no scheduler in this
  application, and adding one deserves its own spec (the reason Phase 6 declined
  polling webhooks).
- **A criticality-scaled rehearsal rule.** §2.11 says "≥quarterly **for
  critical**", but EnvManager has no release-criticality field — that is C1's
  risk score, which is not built. The validity period is therefore per tenant,
  not per release criticality. **Deviation on record**; C1 can refine it.
