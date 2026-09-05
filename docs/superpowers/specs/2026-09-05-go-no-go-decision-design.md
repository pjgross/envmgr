# Phase 9 C3 — Go/No-Go decision record

> Status: design approved 2026-09-05, not yet built.
> Phase: [docs/phases/phase-9.md](../../phases/phase-9.md) cluster **C3**.
> Requirement: [requirements.md](../../requirements.md) §2.11.
> Depends on: **C2** (typed gates, evidence, waivers) and **C4** (rollback governance) — both shipped.

## 1. What §2.11 asks for

> **Go / No-Go decision record**: joint sign-off (Test Manager quality + Release
> Manager process + Business Sponsor acceptance); records go / conditional-go /
> no-go, rationale, conditions, attendees, dissents; "have you tested the
> rollback?" is a required question.

Everything in that sentence is a **record**. C3 builds the place to keep it.

## 2. The central promise

**C3 RECORDS; IT REFUSES NOTHING.** No release transition is blocked, no
deployment is refused, `can-deploy` is untouched, and a recorded `no_go` changes
no behaviour anywhere in the product. `backend/tests/test_c3_records_never_refuses.py`
is the guard — the **eighth** sub-project running whose central promise is a
named test rather than an absence in the diff, after A3, A4, B2, B4, C2, C4 and
the PIR work.

**B5 is deliberately not in that list, and CLAUDE.md's PIR entry is wrong to
include it.** B5 *acts*, narrowly and on purpose (it sets
`environment.status → DECOMMISSIONED` at teardown and refuses a booking running
past a live teardown date); its guard asserts that those two changes are the
*only* ones, which is a different shape from "this refuses nothing". Counting
the series consistently — A3, A4, B2, B4, C2, C4, PIR — C3 is the eighth. The
PIR entry in CLAUDE.md adds B5 to its parenthetical while keeping the ordinal
that excluded it, so its "seventh" and its own list disagree by one. Worth a
one-line correction there when C3 lands.

It must be proved non-vacuous the way its predecessors were: insert a real
refusal into the record path, watch the test fail, remove it, watch it pass.

**This extends further than it first looks.** C3 also does not police the
completeness of its own record. A decision with no sign-offs at all is
recordable, because a meeting where nobody signed is a real thing and refusing
to record it would be C3 refusing something. The UI shows which perspectives are
unsigned; the API does not insist. Anyone tempted to add "a decision requires
three sign-offs" is adding the first refusal.

## 3. Data model

Four tables. Migration slug `gonogo`, additive: four creates, no column changes
on existing tables except the additive readiness response field (§5), which is
not a column at all.

### 3.1 `go_no_go_perspective` — tenant-configurable

| column | type | notes |
|---|---|---|
| `tenant_id` | FK tenant, indexed | |
| `name` | String(100) | *Quality*, *Process*, *Acceptance* as seeded |
| `description` | Text, nullable | what this perspective attests |
| `sort_order` | Integer | display order |
| `is_active` | Boolean, default true | retire without deleting |

Seeded with §2.11's three: **Quality** (the Test Manager's view), **Process**
(the Release Manager's), **Acceptance** (the Business Sponsor's). Seeded by the
migration for every tenant that exists when it runs **and** by
`tenant_service.create_tenant` for every tenant created afterwards — C2's
`gate_type` pattern exactly, so **there is no standing deploy step**. The one
case needing `seed_go_no_go_perspective_defaults_for_tenant` by hand is a tenant
restored from a backup predating the migration; the seeder is idempotent.

**Because these are tenant-configurable, nothing may assume a given perspective
exists.** No code path, message, report or test fixture may hardcode "the
Quality perspective". A tenant whose perspectives are all inactive gets an
explicit empty state pointing at the admin page — not a silently unsigned
decision that reads as an oversight.

### 3.2 `go_no_go_decision` — the meeting

| column | type | notes |
|---|---|---|
| `tenant_id` | FK tenant, indexed | |
| `release_id` | FK release, CASCADE, indexed | |
| `outcome` | String(20) | `go` \| `conditional_go` \| `no_go` |
| `rationale` | Text | why |
| `decided_at` | DateTime(tz) | when the meeting happened, caller-supplied; may be backdated, may not be in the future |
| `chaired_by_user_id` | FK user | who recorded the outcome |
| `attendees` | JSON | list of user ids — attendance is not sign-off |
| `snapshot_ok` | Boolean | frozen — see §4 |
| `snapshot_blockers` | JSON | frozen list of `{type, detail}` |
| `snapshot_warnings` | JSON | frozen list of `{type, detail}` |
| `snapshot_reversibility` | String(20), nullable | frozen |
| `snapshot_rehearsal_state` | String(30), nullable | frozen — answers §2.11's rollback question |

`outcome` is stored as a plain `String`, not a native enum
(`native_enum=False` is the house rule; a `String` column with a service-level
vocabulary is the shape `reversibility` and `protection_level` already use).

**No `deleted_at`, no update path.** See §4.2.

### 3.3 `go_no_go_signoff` — one row per signatory

| column | type | notes |
|---|---|---|
| `decision_id` | FK decision, CASCADE, indexed | |
| `perspective_id` | FK perspective | |
| `user_id` | FK user | any active tenant member |
| `verdict` | String(20) | `go` \| `conditional_go` \| `no_go` |
| `dissent_note` | Text, nullable | why they disagreed |

**The outcome is NOT a fold of these.** `decision.outcome = go` alongside a
sign-off of `no_go` is legal and is precisely what §2.11's "dissents" asks for:
a decision taken over someone's objection, with the objection on the record. A
computed outcome could not express it — the outcome and the dissent would
contradict each other by construction. A named test round-trips exactly this
combination.

Unique on `(decision_id, perspective_id, user_id)` so one person signing one
perspective twice on one decision is a conflict rather than two rows. **Two
different people signing the SAME perspective is deliberately allowed** — two
test leads may both attest quality, and refusing the second would be C3
refusing something. So "is the Quality perspective signed" is a question about
whether any sign-off exists for it, never about a single row.

### 3.4 `go_no_go_condition` — what a conditional go is conditional on

| column | type | notes |
|---|---|---|
| `decision_id` | FK decision, CASCADE, indexed | |
| `text` | Text | the condition |
| `owner_user_id` | FK user, nullable | who owes it |
| `due_date` | Date, nullable | |
| `met_at` | DateTime(tz), nullable | null = outstanding |
| `met_by_user_id` | FK user, nullable | |

A conditional go whose conditions nobody can check is just a go. This reuses the
shape the PIR work proved (owner, due date, closure) **without** its tenant-wide
worklist: C3's conditions belong to a release and are read there. A tenant-wide
conditions queue is a later question, not this one.

**Conditions are the one mutable part of an append-only record**, and the
distinction is exact: closing a condition records a *later fact about* the
decision, it does not rewrite what was decided. Nothing about `outcome`,
`rationale`, the sign-offs or the snapshot ever changes.

## 4. The two rules that will look wrong to a later reader

### 4.1 The snapshot is stored — the deliberate exception

Every other sub-project in this codebase computes state on read and stores
nothing: A4's escalation state, B5's decommission state, B2's quarantine, C2's
waiver liveness and evidence staleness, C4's reversibility rollup. Each one's
note explains that a stored value would be falsified by the next edit.

**C3 stores a snapshot, on purpose, and it is the only place this happens.**

A decision record is evidence of what was known when a decision was taken. If
the readiness verdict were recomputed on read, a release that shipped over three
blockers would render as clean the moment those blockers were cleared — and
"we went ahead knowing X" is the entire value of the record. An audit record
that silently rewrites itself is evidence of nothing.

So `snapshot_*` is captured **server-side** at record time by calling
`release_readiness_service.evaluate()` — the same single evaluator C2
established, never a second implementation, and **never a client-supplied
value**. A client-supplied snapshot is a client-supplied audit record.

A named test pins this: record a decision, then change the underlying gates, and
assert the snapshot has not moved.

**The snapshot is of the moment of RECORDING, not of `decided_at`.** A meeting
held on Tuesday and recorded on Thursday freezes Thursday's verdict, because
Tuesday's is not reconstructible — nothing in this codebase stores the history
of a gate's state. The API says so, the UI says so beside the frozen figures,
and a backdated `decided_at` therefore does not mean a backdated snapshot.
Pretending otherwise would put a precise-looking falsehood in an audit record,
which is worse than an honest one-line caveat.

### 4.2 Decisions are append-only

A release may have many decisions — a no-go on Tuesday, a go on Thursday — and
the latest is "current". A wrong decision is corrected by **recording another**,
never by editing, the same escape-hatch shape A4 gives a wrong or departed
contention owner and B5 gives a decommission that should not have been raised.

There is no `PATCH` and no `DELETE` for a decision, and no `deleted_at` column.
An editable record with a frozen snapshot is a contradiction: the snapshot would
describe a decision whose text had since changed.

A structural sweep asserts no edit or delete route exists for a decision — the
rule is otherwise a sentence nothing checks, which this repository's own notes
identify as the shape that survives review.

## 5. API

| method | path | who |
|---|---|---|
| `POST` | `/releases/{id}/go-no-go` | Admin or Release Manager |
| `GET` | `/releases/{id}/go-no-go` | any tenant member |
| `PATCH` | `/go-no-go-conditions/{id}` | the condition's owner, or Admin/RM |
| `GET`/`POST`/`PATCH` | `/tenant/go-no-go-perspectives` | read: any member; write: Admin |

**`POST` is composite and validates before it creates.** It writes the decision,
its sign-offs and its conditions in ONE transaction, and it creates nothing
until the whole request is known valid. This is the PIR citation endpoint's
lesson taken directly: the plan there had it create first and lean on
`get_db`'s rollback, which the shared-session `client` fixture cannot observe at
all. The rollback path gets its own test through a production-shaped session
fixture.

**Sign-off is open to any active tenant member.** The perspective is what is
being attested, not a system permission — the same call `gate_waiver.approved_by`
already makes.

**`GET` is bounded**, `pagination()`, ordered `decided_at DESC, id DESC`. The
`id` tiebreaker is not decoration: two decisions can share a `decided_at`, and
`LIMIT`/`OFFSET` duplicates and drops rows across pages the moment ties exist.
Sortable via `sorting()`: `decided_at`, `outcome`. **`unmet_condition_count` is
permanently unsortable** — it is computed after the page is fetched — and joins
the set recorded in [docs/pagination.md](../../pagination.md).

**Every username travels with its row, resolved through a lookup that is NOT
tenant-qualified.** Under master-admin impersonation a chair or signatory can
legitimately sit outside the decision's own tenant, and a `User.tenant_id ==`
join renders them as nobody — losing the one name a governance record exists to
hold. This has now bitten A3 (`acknowledged_by_username`), A4 (`usernames_for`),
B5 and C2 (`approved_by_username`); C3 gets its own named test rather than
relying on the reader remembering.

### 5.1 The readiness response gains one additive field

`ReleaseReadinessResponse` gains `latest_decision`: outcome, `decided_at`,
chair's username, unmet condition count — or null. It appears on **both** routes
C2 shipped, `GET /api/v1/releases/{id}/readiness` (JWT) and
`GET /api/v1/webhooks/release-ready` (API key, scope `webhooks:release`),
because they call one evaluator and a pipeline asking "is this release ready"
should see that a human recorded a no-go.

**It contributes no blocker and no warning.** It is reported, not judged — `ok`
is still exactly `len(blockers) == 0`. The field is additive, so existing
consumers are unaffected.

## 6. Frontend

A twelfth tab on release detail, `?tab=go-no-go` through `useUrlTab`. Twelve tabs
fit only because C4's Task 10 added `variant="scrollable" scrollButtons="auto"`
to that strip after the eleventh tab rendered entirely outside the visible area
at an ordinary ~1450px viewport, reachable only by a synthetic automation click.

The tab holds:

- **The decision history**, through `components/DataTable.tsx` with a unique
  `storageKey`, an entity-specific `emptyMessage` that is conditional on
  `error` (a failed fetch must never render as an authoritative empty), and
  `disableColumnFilter` — PR 4's contract.
- **A *Record decision* dialog** showing the live readiness verdict as it is
  about to be frozen, so the chair sees what they are signing over. §2.11's
  "have you tested the rollback?" is answered there from C4's rehearsal state
  rather than asked again — asking a human to restate what the system computes
  is how a chip and a verdict come to disagree.
- **The latest decision's conditions**, with met/unmet and a close control.

Any non-`DataGrid` table sits inside a `TableContainer` — PR 5's rule, now
guarded by `frontend/src/__tests__/tableScrollContainers.test.ts`.

An admin panel for perspectives under the existing `/admin/releases` entity
config, reads open to any member and writes Admin-only (B3a's rule).

## 7. Testing

Named tests for the promises, in the pattern this codebase uses:

- **`test_c3_records_never_refuses.py`** — a release with a recorded `no_go`
  still transitions, still deploys, and `can-deploy` answers byte-identically
  with and without a decision present. Proved non-vacuous by inserting a real
  refusal.
- **The snapshot does not move.** Record a decision, change the gates
  underneath it, assert `snapshot_blockers` is unchanged.
- **The outcome is not a fold.** `outcome: go` with a `no_go` sign-off and a
  dissent note round-trips intact.
- **A signatory outside the tenant resolves.** Fails if a `User.tenant_id ==`
  join is added.
- **No edit or delete route exists for a decision** — a structural sweep.
- **The paging tiebreaker** — a structural assertion on an exposed query seam.
  `contention_service.worklist_query` and `pir_finding_service.worklist_query`
  exist for exactly this reason: removing the tiebreaker leaves paging green on
  both engines, so a behavioural test cannot guard it.
- **A tenant with no active perspectives** gets the empty state, not an
  unsigned decision that reads as an oversight.
- **Three runs, not one.** This sub-project has backend code, so "the full
  suite" means SQLite, PostgreSQL **and** the frontend.
- **A browser pass**, recorded in the PR description. Every programme in this
  repository found its worst defects only by opening the page.

## 8. Deviations from §2.11, on record

- **There is no Business Sponsor role and C3 does not add one.** This product's
  roles (Admin, Release Manager, Test Manager, Developer, Viewer) are
  load-bearing in permission checks across the whole application; adding a sixth
  would touch far more than C3 and need a backfill decision for existing users.
  The sponsor is whoever signs the *Acceptance* perspective.
- **The three perspectives are tenant-configurable rather than fixed**, so a
  tenant may rename them, retire one, or add a fourth. The cost is that nothing
  may assume a given perspective exists.
- **"Required question" is answered, not asked.** §2.11 says "have you tested
  the rollback?" is a required question. C3 answers it from C4's rehearsal state
  and freezes the answer, rather than adding a field for a human to retype what
  the system already computes.

## 9. What C3 does not build

- **No tenant-wide conditions worklist.** Conditions live on their release. The
  PIR work has a tenant-wide action worklist and that is a different queue; a
  cross-release conditions view is a later question.
- **No notifications or reminders** on an overdue condition. Consistent with the
  IA programme's "no polling, no notifications" decision.
- **No approval routing or scheduling.** C3 records a meeting that happened; it
  does not convene one.
- **Nothing that refuses.** The configurable close gate §2.5 asks for belongs to
  **C6**, which owns the "PIR complete" gate and will have to amend a
  never-refuses guard consciously rather than trip over it.
