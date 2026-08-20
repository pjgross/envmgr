# Phase 9: Release Governance & Deployment Safety

> Status: 🟡 **IN PROGRESS** — sub-project **C2 (Typed gates, evidence, waivers) is
> complete**; C1 and C3–C9 are not started. | Roadmap: [../plan.md](../plan.md)

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
| C4 | Rollback governance | nothing | C2 (rehearsal is a gate) | Not started |
| C5 | Deployment execution records | Phase 4 tracking, `can-deploy` | C2 (pre-deploy checklist is a gate) | Not started |
| C6 | Hyper-care + closeout | Phase 5 SP4 PIR is the retro half | C3 | Not started |
| C7 | Scope freeze completion | `scope_deadline`, Scope Windows, churn analytics — most of it already ships | — | Not started |
| C8 | Feature-flag governance | nothing | — | Not started |
| C9 | Stable Windows | `can-deploy` to extend | — | Not started |

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
