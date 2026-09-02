# Phase 9: Release Governance & Deployment Safety

> Status: 🟡 **IN PROGRESS** — sub-projects **C2 (Typed gates, evidence,
> waivers)** and **C4 (Rollback governance)** are complete; C1, C3, C5–C9 are
> not started. | Roadmap: [../plan.md](../plan.md)

Phase 9 answers [requirements.md §2.11](../requirements.md), which is roughly 48
capability rows — Phase-7-sized or larger. It was decomposed into nine clusters,
**C1–C9**, before any of it was built. The labels are lifecycle order (intake
before go/no-go before rollback before deployment before closeout), not build
order — C2 shipped first because it extends entities (`ReleaseGate`,
`GateCriterion`, release templates) that already existed, and because C1, C3, C4
and C5 all lean on the gate model C2 defines. See
[the C2 design spec, §9](../superpowers/specs/2026-08-19-typed-gates-evidence-waivers-design.md#9-the-rest-of-phase-9)
for the decomposition as originally recorded.

## The nine clusters

| # | Cluster | Already there before C2 | Depends on | Status |
|---|---|---|---|---|
| C1 | Intake + risk scoring | `environment_request`'s request-on-a-lifecycle-template pattern | C2 (risk selects gate types) | Not started |
| C2 | **Typed gates, evidence, waivers** | `ReleaseGate`, `GateCriterion`, templates | — | ✅ Complete |
| C3 | Go/No-Go decision record | nothing | C2, C4 | Not started |
| C4 | **Rollback governance** | nothing | C2 (folds into the same verdict) | ✅ Complete |
| C5 | Deployment execution records | Phase 4 tracking, `can-deploy` | C2 (pre-deploy checklist is a gate) | Not started |
| C6 | Hyper-care + closeout | The **PIR findings/actions/citations** work (2026-09-02) is the retro half — findings, trackable actions, a tenant-wide action worklist, incidents cited as evidence. Supersedes Phase 5 SP4. | C3 | Not started |
| C7 | Scope freeze completion | `scope_deadline`, Scope Windows, churn analytics — most of it already ships | — | Not started |
| C8 | Feature-flag governance | nothing | — | Not started |
| C9 | Stable Windows | `can-deploy` to extend | — | Not started |

**What C6 still owns, and this work deliberately did not build:** requirements.md §2.5's
*configurable "PIR complete" gate before a release is formally closed*. The PIR work refuses
nothing — no release transition, no deployment, no readiness verdict entry — and
`backend/tests/test_pir_records_never_refuses.py` is the named guard that fails the day someone
adds such a gate by accident. Building it on purpose is C6's job, and it will mean deleting or
amending that guard consciously rather than tripping over it.


## C2 — Typed gates, evidence and waivers — ✅ COMPLETE 2026-08-20

Release gates already existed and were already used — a name, an absolute due
date, a status (`pending`/`passed`/`failed`/`overridden`), and a checklist of
criteria. Three things were missing, and they compounded: **a gate had no
type**, so nothing could distinguish a security sign-off from an accessibility
check or declare how a failure should behave; **a gate had no evidence**, only
free text in `decision_notes`; and **an override was an unstructured escape
hatch** — no approver rule, no expiry, nothing that ever came back to ask again.

C2 gives a gate a tenant-configurable **type** (`gate_type`: name, category,
`failure_behaviour` = block/warn/accept_with_exception, an `expected_evidence`
list of kind names, `requires_deployment_link`), seeded per tenant with the
eight standard types from §2.11 (functional, NFR/performance, integration,
security, license, accessibility, business, ops-readiness). **Evidence**
(`gate_evidence`: kind, label, url, an optional link to a `Deployment` row) is a
reference, never an uploaded artefact — this application has no file storage
outside the spreadsheet import, which is parsed in memory and never persisted.
And the informal override became a **waiver** (`gate_waiver`: reason, approver,
optional expiry — empty means permanent — and a remediation note), computed
live-vs-expired on read the same way A4's escalations and B5's decommissions
are.

One evaluator, `gate_readiness_service.evaluate(release_id)`, folds all three
into a verdict — `ok`, `blockers`, `warnings` — served on two routes:
`GET /api/v1/releases/{id}/readiness` (JWT, backs the release detail page's
banner) and `GET /api/v1/webhooks/release-ready?release_id=` (API key, new
scope `webhooks:release`, for a DevOps pipeline). Both call the same function,
so the banner a human reads and the answer a pipeline gets can never disagree.

**C2 refuses nothing.** No release transition is blocked, and `can-deploy` is
untouched — not one blocker, not one warning. The same promise A3, A4, B2 and
B4 each made, guarded the same way, by
`backend/tests/test_c2_advises_never_blocks.py`. The UI advises; a pipeline can
ask the machine-readable question and enforce on the answer itself — the same
architectural boundary Phase 4 drew around deployment tracking and B5 drew
around teardown.

Migration `gatetypes` is additive: three new tables (`gate_type`,
`gate_evidence`, `gate_waiver`), two nullable columns on `release_gate`
(`gate_type_id`, `test_phase_id`). It **backfills the eight standard gate types
for every tenant that exists when it runs**, and `tenant_service.create_tenant`
seeds any tenant created afterwards — so no deploy step is required. The one
case that still needs `seed_gate_type_defaults_for_tenant` by hand is a tenant
restored from a backup taken before the migration; the seeder is idempotent, so
running it again is harmless. A tenant with no seeded types has no vocabulary to
type a gate with, and the feature reads as broken rather than unconfigured. Spec:
[docs/superpowers/specs/2026-08-19-typed-gates-evidence-waivers-design.md](../superpowers/specs/2026-08-19-typed-gates-evidence-waivers-design.md).

### What C2 established, and what will bite if forgotten

- **C2 ADVISES; IT NEVER BLOCKS.** `test_c2_advises_never_blocks.py` is the
  guard — a release with a failed `block`-behaviour gate still transitions,
  `can-deploy` answers byte-identically with and without gate state, and no
  write path anywhere refuses on gate state. Fifth sub-project in this
  programme whose central promise is a named test rather than an absence in
  the diff (after A3, A4, B2, B4).
- **ONE EVALUATOR, TWO ROUTES.** `gate_readiness_service.evaluate()` is the
  only place the rules live; the release page's banner and the pipeline
  endpoint both call it. A gate chip disagreeing with the endpoint a pipeline
  obeys would be worse than no chip at all.
- **`webhooks:release` IS A NEW SCOPE, AND THERE IS NO CANONICAL SERVER-SIDE
  SCOPE LIST.** `ApiKeyCreate.scopes` is a free-form `list[str]` — nothing
  validates a scope name against a whitelist server-side, so a typo'd scope on
  a key is silently unusable (the key saves, the plaintext is shown once, and
  every call 403s with a scope-missing message that gives no hint the typo is
  the cause). The frontend's `AVAILABLE_SCOPES` list is the only thing keeping
  the two scopes typeable at all.
- **EVIDENCE STALENESS IS COMPUTED ON READ, AND KEYS ON `status == "success"`
  EXACTLY.** Evidence links a deployment of subsystem *S* into environment
  *E*; it goes stale the moment a **later, successful** deployment of the same
  *S* into the same *E* exists. A failed redeploy must not invalidate evidence
  that still correctly describes what is running — a rolled-back deploy does
  **not** supersede anything. A stored staleness flag would be falsified by
  the next deployment webhook, so nothing is stored; `is_stale` on
  `GateEvidenceRead` and the `evidence_stale` warning are both computed fresh
  every time, and the warning names **both** deployments (the one the evidence
  cites and the one that superseded it) — a warning naming only one side is
  half a sentence.
- **A WAIVER IS LIVE ALL THROUGH ITS EXPIRY DAY.** `gate_waiver_service`
  compares `expires_at` against `expiry_boundary(now)`, not against the
  instant `now` — the same rule A4's escalations and B2's grace periods
  follow, for the same reason: the UI writes an expiry at `T00:00:00Z`, so
  comparing at instant precision would read a waiver as expired from one
  minute past midnight on the day it was still meant to hold. Confirmed in the
  browser: a waiver dated today read `state: "live"`, not `"expired"`.
- **`approved_by_username` MUST NOT BE TENANT-QUALIFIED.** Under master-admin
  impersonation the approver can legitimately sit outside the gate's own
  tenant; a `User.tenant_id ==` join would render them as nobody, losing the
  one name a waiver's audit trail exists to hold. Same rule as A3's
  `acknowledged_by_username`, A4's `usernames_for`, and B5's
  `environment_decommission_service.usernames_for`.
- **A WAIVED GATE IS OVERRIDDEN, NOT PASSED.** The waiver dialog says so in
  its own copy ("it still reads as unmet work, recorded rather than
  resolved") and the readiness verdict treats it as a warning, never a clean
  pass. **Waiving is re-waivable, not editable** — there is no edit path on a
  waiver, only a fresh override that records a new `GateWaiver` row and keeps
  the old one as history (the same shape A4's escalations and B5's
  decommission extensions took). Re-waiving with the last waiver still live
  is disclosed to the operator before they submit: the dialog shows the
  *current* waiver's reason, approver, expiry and remediation above the form,
  labelled "Currently overridden … Submitting below records a new waiver."
- **THE MUI GOTCHA THIS SUB-PROJECT'S FRONTEND HALF FOUND**: `<Select
  aria-label>` lands the accessible name on the **root** node, not on the
  `role="combobox"` element a query resolves to — a test (or an
  assistive-technology user) that queries the combobox by that label finds
  nothing. `GatesTable`'s per-row gate-type `Select` uses
  `inputProps={{ 'aria-label': ... }}` instead, which attaches the name to the
  right node. Worth checking on any future `<Select>` this codebase adds.
- **ONE DEFECT FOUND ONLY BY OPENING THE PAGE, FIXED IN THIS TASK**: the
  `gate_waived` readiness warning printed `f"Waived by user {id}."` — a raw
  database id, never resolved to a username, and never naming the expiry at
  all, contradicting the rules table's own row ("warning, naming approver and
  expiry"). No existing test pinned the wrong text (only the warning `type`
  was asserted), so a fully green suite shipped it. Fixed by reusing
  `gate_waiver_service.usernames_for` (already the batched, non-tenant-
  qualified lookup C2's own waiver-read path uses) inside the evaluator, with
  two new tests — a live waiver's detail names the approver's username and
  states the expiry date, a permanent waiver's detail says "no expiry" rather
  than printing a literal `None`. Green on both engines.

### Open questions the C2 design deliberately left for later clusters

- **Whether a Stable Window becomes a `can-deploy` blocker is C9's call, not
  C2's.** Every C2 sub-decision (the waiver, the untyped-gate default, the
  evidence-missing warning) stayed on the advisory side of the line
  `can-deploy` currently draws — EnvManager has never yet refused a
  deployment on its own authority. C9 is where that question gets asked
  directly, because a read-only Stable Window that never blocks anything is a
  calendar annotation, and one that does block a deploy would be the first
  time this application enforces rather than advises. The C2 spec states the
  choice is deliberately undecided rather than assumed away.
- **Gate approver permissions wait on the RBAC/OAuth upgrade, and are Phase
  12's problem.** Who may pass, fail or waive a gate today is governed by the
  same coarse roles as everything else in the product (Admin, Release
  Manager, …) — there is no separation-of-duties rule saying a gate's
  approver must differ from whoever built or deployed the change it gates.
  [requirements.md §2.15](../requirements.md) puts "builder ≠ approver ≠
  deployer" in Phase 12, which the roadmap already marks as depending on a
  future RBAC/OAuth upgrade this codebase does not have yet. C2 did not
  attempt a narrower version of that rule — the same call B3b, B4 and B5 each
  made about their own approval-shaped actions.

## C4 — Rollback governance — ✅ COMPLETE 2026-08-21

Four things per release, none of them present before this sub-project: a per
changing-or-config-only-component **rollback plan** (`steps`, `reversibility`
— `reversible`/`lossy`/`irreversible` — an `estimated_minutes`, and a
separate "agreed" state that clears the moment the plan's content changes); a
release-level **reversibility rollup** where the worst component's value wins
(computed on read, never stored); a **rollback authorisation** record — who
decided, when, what triggered it, why, and which systems it touched —
raisable before or after the fact and requiring no plan to exist at all; and
a per-system **rehearsal** record whose freshness (`current`/`stale`) is
computed on read against a per-tenant validity period. All four fold into the
ONE readiness verdict C2 built: `release_readiness_service.evaluate()`
(renamed from `gate_readiness_service` in this sub-project — gate findings
and rollback findings now live in the same function, so the release page's
banner and the pipeline endpoint can never disagree about a rollback finding
either), served on `GET /api/v1/releases/{id}/readiness` (JWT) and
`GET /api/v1/webhooks/release-ready` (API key, scope `webhooks:release`, C2's
scope). Two per-tenant policy flags, `require_rollback_plan` and
`require_current_rehearsal` — **both default off** — decide whether a gap is
a warning or a blocker in that verdict; neither one, nor anything else in
C4, blocks a deployment, a release transition or a booking.

**C4 records and never refuses.** `backend/tests/test_c4_records_never_refuses.py`
is the guard — recording an authorisation or transitioning a release never
409s on rollback state, the same promise A3, A4, B2, B4, B5 (its acting parts
aside) and C2 each made, guarded the same way. Verified live in the browser
in this task: a rollback was recorded against a component with an unagreed,
irreversible plan and against a release with no plan at all, and neither
attempt was refused. Migration `rollbackgov` is additive — four tables
(`release_rollback_plan`, `release_rollback_rehearsal`,
`rollback_authorisation`, `rollback_policy`), no column changes, no backfill;
the policy row is created lazily with both flags off for any tenant that
lacks one, the same lazy-seed shape B1's `environment_tier` and B2's naming
policy use. Spec:
[docs/superpowers/specs/2026-08-21-rollback-governance-design.md](../superpowers/specs/2026-08-21-rollback-governance-design.md).

### What C4 established, and what will bite if forgotten

- **`rollback_irreversible` IS ALWAYS A WARNING, WHATEVER THE POLICY SAYS.**
  Only a missing plan, an unagreed plan, a missing rehearsal and a stale
  rehearsal move between warning and blocker on `require_rollback_plan` /
  `require_current_rehearsal`. A component that genuinely cannot be rolled
  back is a fact, not a governance gap a tenant can configure away — turning
  `require_rollback_plan` on in the browser and re-checking the banner
  confirmed `rollback_irreversible` stayed a warning while
  `rollback_plan_unagreed` on the same component became a blocker in the same
  response.
- **A FAILED REHEARSAL IS NOT A CURRENT REHEARSAL — IT PROVES THE OPPOSITE.**
  `rehearsal_state` treats `rehearsal is None or rehearsal.outcome == "failed"`
  as one case (`rehearsal_missing`), not two. Recording a passed rehearsal
  and then a failed one on the same system in the browser flipped the
  release banner straight back to "No successful rollback rehearsal
  recorded", even though a rehearsal — two of them — genuinely exists; the
  Rehearsals panel itself says as much in its own copy ("A failed rehearsal
  is not a pass — the readiness verdict treats it as no successful rehearsal
  at all").
- **EDITING AN AGREED PLAN CLEARS THE AGREEMENT.** `upsert_plan` nulls
  `agreed_by_user_id`/`agreed_at` the moment `steps` or `reversibility`
  changes — the plan someone agreed to is what it said, not what it later
  becomes. The edit dialog states this up front ("Changing the steps or
  reversibility below clears that agreement") and it was proved live: adding
  one line to an agreed plan's steps reverted its Agreement column from
  "Agreed by admin" back to "Agree".
- **BOTH POLICY FLAGS DEFAULT OFF.** A freshly seeded `rollback_policy` row
  advises with warnings only; a tenant must opt in to either flag becoming a
  blocker. The admin panel's own copy says so twice over ("Off (default):
  it's a warning only") and states plainly that neither flag "stops a
  deployment, a release transition, or a rollback itself."
- **THE REVERSIBILITY ROLLUP IS COMPUTED WORST-WINS, NEVER STORED** —
  `rollback_plan_service.rollup()`, re-run on every readiness check the same
  way C2's evidence staleness and waiver state are. An unrecognised
  reversibility value sorts **last** (worst), not first, so a bad row is loud
  rather than silently read as safe.
- **THE ROLLUP AND THE FINDINGS ARE COMPUTED OVER DIFFERENT COMPONENT SETS,
  AND THIS IS REACHABLE, NOT THEORETICAL.** Findings
  (`rollback_plan_missing`/`_unagreed`/`_irreversible`/`_lossy`,
  `rehearsal_missing`/`_stale`) are only ever raised for `changing` and
  `config_only` components — `rollback_plan_service.changing_systems_for_release`
  excludes `regression` components by design, "a regression component has
  nothing to roll back." The rollup, `rollback_plan_service.rollup(plans)`,
  is computed over **every live plan for the release**, with no role filter
  at all. Nothing stops a plan being written against a `regression`-role
  component — `upsert_plan` validates only that the system is attached to
  the release (`release_system` membership), never its role — and the plan
  API is reachable directly (`PUT /releases/{id}/rollback-plans`) even though
  the release page's own "Create plan" control only ever offers it for
  changing/config-only rows. **Confirmed live in the browser and by direct
  API call in this task**: attaching a system with role `regression` to a
  release and writing a `lossy` plan against it changed
  `GET /releases/{id}/readiness`'s top-level `reversibility` from
  `"irreversible"` to `"lossy"` (and, once the release's only other plan was
  removed, produced `reversibility: "lossy"` with **zero** findings
  mentioning the system anywhere in the response) — while the release
  detail page's own `RollbackPanel` disagreed: its local rollup chip is
  computed from a `visiblePlans` list filtered to changing/config_only roles
  (`RollbackPanel.tsx`'s own comment claims this "mirrors" the backend
  rollup — it does not; only the *findings* share that exclusion) and so
  showed no chip and "No rollback plans yet" for the same release the
  pipeline endpoint reported as `lossy`. **A CI/CD pipeline reading the
  webhook endpoint can therefore see a different reversibility verdict than
  a human reading the release page, with no on-page explanation either
  way.** Not fixed here — flagged for the final review to triage; see the
  design spec's own note on this gap.
- **DELETING A ROLLBACK PLAN AND RE-CREATING ONE FOR THE SAME COMPONENT 500s
  — A NEW DEFECT FOUND ONLY BY OPENING THE PAGE, NOT FIXED IN THIS TASK.**
  `uq_rollback_plan_release_system` (migration
  `20260821_0823_rollbackgov_rollback_governance_schema.py`) is a whole-table
  `UniqueConstraint(release_id, system_id)` with no `deleted_at` scoping,
  while `upsert_plan` decides create-vs-update by selecting only rows with
  `deleted_at IS NULL`. After `delete_plan` soft-deletes a plan, the deleted
  row still occupies that unique slot; the next `upsert_plan` call for the
  same `(release_id, system_id)` pair takes the "no existing row" branch and
  attempts a second INSERT, which raises an uncaught `IntegrityError` and
  surfaces to the browser as a bare, unhelpful "Internal server error" in
  the plan dialog — reproduced live: create a plan, delete it, try to create
  a new one for the same component on the same release, 500. Confirmed by
  direct inspection of `release_rollback_plan` in the dev database (two
  soft-deleted rows sitting on the exact pairs that then failed to
  re-insert) and confirmed the diagnosis by hard-deleting the stale rows,
  which immediately let the same `PUT` succeed. **Any component whose
  rollback plan is ever deleted can never have a new one created for that
  release again**, through the API or the UI, until someone hard-deletes the
  old row by hand. Not fixed here — flagged for the final review; the fix is
  either a partial unique index scoped to `deleted_at IS NULL` (inert on
  SQLite per this codebase's own `uq_environment_tenant_name` precedent) or
  making `upsert_plan` look up and revive a soft-deleted row instead of
  always inserting when none is found live.
- **THE RELEASE DETAIL PAGE'S TAB STRIP OVERFLOWED THE MOMENT THIS SUB-PROJECT
  ADDED AN 11TH TAB — FOUND ONLY BY OPENING THE PAGE, FIXED IN THIS TASK.**
  `ReleaseDetail.tsx`'s `<Tabs>` had no `variant="scrollable"` (its sibling
  `EnterpriseTabs.tsx`, with the same eleven-tab shape, already carries
  `variant="scrollable" scrollButtons="auto"` for exactly this reason). At an
  ordinary ~1450px viewport the new "Rollback" tab — this sub-project's own
  panel — rendered completely outside the visible tab strip with no scroll
  affordance a real mouse could reach; only a synthetic browser automation
  click, which auto-scrolls its target into view as part of dispatching,
  could reach it, masking the defect from anyone testing that way. Fixed by
  adding the same `variant="scrollable" scrollButtons="auto"` props
  `EnterpriseTabs.tsx` already uses; verified afterwards that a scroll arrow
  appears and the tab is reachable. `npx tsc --noEmit`, `npm run lint`, the
  targeted `rollbackPanel.test.tsx` suite, and `npm run build` all stayed
  green.
- **`RecordRollbackDialog`'s "Affected systems" field has no visual
  asterisk but is functionally required** (`canSave` requires
  `systemIds.length > 0`, and the backend schema enforces the same:
  `system_ids: list[int] = Field(..., min_length=1)`, "a rollback of nothing
  is not a rollback"). A minor, cosmetic labelling gap, not a functional one
  — recorded here rather than fixed, since Task 10's brief scopes fixes to
  what the browser pass reveals as small and safe, and a label change on a
  form the guard test already exercises correctly is lower priority than the
  two defects above.
- **THE PIPELINE ENDPOINT AND THE RELEASE PAGE AGREE BYTE-FOR-BYTE WHEN THE
  COMPONENT SETS MATCH.** `GET /api/v1/webhooks/release-ready?release_id=`
  (API key, scope `webhooks:release`) was called against release 5 in this
  task's browser pass and returned the same blocker/warning wording, same
  `gate_name`/`gate_type: null` shape for rollback findings, and the same
  `reversibility` value as the release page's own banner — confirming the
  ONE-EVALUATOR promise holds whenever the rollup-vs-findings gap above
  isn't in play.
