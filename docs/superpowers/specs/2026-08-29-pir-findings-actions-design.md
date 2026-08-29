# PIR findings, actions and incident citations

> Status: design approved 2026-08-29.
>
> Rework of Phase 5 SP4 (Post-Implementation Reviews), which shipped a PIR as
> five free-text blobs and a single incident link. Referenced by Phase 9 C6
> (hyper-care + closeout), whose retro half is this feature.

## 1. The problem

A post-implementation review is held after a release goes live. It records a
number of things that **went well and need to keep happening**, and a number of
things that **did not go well** — each of which needs root-cause analysis and
actions so the same failure does not recur.

Crucially, the PIR is not how an incident gets fixed. An incident is its own
entity, raised by the ITIL incident-management process or by a monitoring tool
that has registered a production problem, and it already links to the release
that caused it (`incident.release_id`) and the release that will fix it
(`incident.fix_release_id`). Where an incident is complex, the release manager
uses the PIR to **fix the process that allowed the incident to reach
production** — not to fix the incident. The incident is *evidence* that the
process failed.

What exists today serves neither half.

**The record has no structure.** `pir` is one row per release with
`summary`, `root_cause`, `what_went_well`, `what_went_wrong` and `action_plan`,
all `Text`. A review that found six things cannot say which root cause belongs
to which failure, and "action plan" is a single textarea — so a PIR action has
no owner, no due date, no status, and no way to be reported on. There is no
such thing as a PIR action in the schema at all.

**The incident link points the wrong way and prompts the wrong thing.**
`PIR.incident_id` is a single nullable FK, and `pir_service.get_for_incident`
reads it with `scalar_one_or_none`, so the relationship is 1:1 in both
directions: one incident can back exactly one PIR, and one PIR can cite exactly
one incident. Worse, `IncidentDetail.tsx` renders a **Create PIR** button that
is *disabled* unless the incident has a `fix_release_id`, captioned "Link a fix
release to create a PIR", and creates the PIR against the **fix** release. That
is backwards twice over: it pushes people to invent or attach a release purely
so a PIR can exist, and it anchors the review to the release that will fix the
incident rather than the one whose delivery process failed.

## 2. What this does, and the limit of it

Three things:

1. A PIR becomes a **summary plus a list of findings**. A finding is
   `went_well` or `went_wrong`, carries a title, detail and — where it went
   wrong — a root cause.
2. A finding carries **actions**: a title, an owner, a due date and a status,
   tracked to closure and visible on a tenant-wide worklist, not only inside
   the release tab they were raised in.
3. An incident is **cited as evidence against a went-wrong finding**,
   many-to-many. The citation is raised from the incident page by choosing a
   release that has already gone live and then either picking an existing
   finding or creating one — creating the PIR silently if that release has none.

**This work refuses nothing.** No release transition is blocked, no incident
transition is blocked, `can-deploy` is untouched, and an incomplete PIR or an
overdue action changes no verdict anywhere.
`backend/tests/test_pir_records_never_refuses.py` is the guard — the seventh
sub-project in this codebase whose central promise is a named test rather than
an absence in the diff, after A3, A4, B2, B4, C2 and C4.

[requirements.md §2.5](../../requirements.md) also says "PIR completion can be
configured as a gate before a release is formally closed". That is deliberately
**not** built here; see §9.

## 3. The data model

Migration `pirfindings`: three new tables, one backfill, then five column drops
on `pir`.

### 3.1 `pir_finding`

| column | type | notes |
| --- | --- | --- |
| `tenant_id` | FK `tenant.id`, NOT NULL, indexed | |
| `pir_id` | FK `pir.id` ON DELETE CASCADE, NOT NULL, indexed | |
| `kind` | `String(10)` NOT NULL | `went_well` \| `went_wrong` |
| `seq` | `Integer` NOT NULL | per `(pir_id, kind)`, mirroring `RaidItem.seq` |
| `title` | `String(500)` NOT NULL | |
| `detail` | `Text` nullable | |
| `root_cause` | `Text` nullable | |
| `created_by` | FK `user.id` nullable | |
| `deleted_at` | timestamptz nullable | soft delete |

`root_cause` is meaningful on a went-wrong finding. Nothing **refuses** one on
a went-well finding: the column is nullable and unvalidated, because a
half-useful note on a thing that worked is not worth a 422.

### 3.2 `pir_action`

| column | type | notes |
| --- | --- | --- |
| `tenant_id` | FK `tenant.id`, NOT NULL, indexed | |
| `finding_id` | FK `pir_finding.id` ON DELETE CASCADE, NOT NULL, indexed | |
| `seq` | `Integer` NOT NULL | per `finding_id` |
| `title` | `String(500)` NOT NULL | |
| `detail` | `Text` nullable | |
| `owner_id` | FK `user.id` nullable | |
| `due_date` | timestamptz nullable | |
| `status` | `String(20)` NOT NULL, default `open` | `open` \| `in_progress` \| `done` \| `cancelled` |
| `closed_at` | timestamptz nullable | set on entering `done`/`cancelled`, cleared on leaving |
| `closure_note` | `Text` nullable | |
| `created_by` | FK `user.id` nullable | |
| `deleted_at` | timestamptz nullable | soft delete |

Actions hang off a **finding**, not off the PIR, so "which failure is this fix
for" is structural rather than prose. They are allowed on a `went_well` finding
too — "codify this in the release template" is a real PIR outcome.

There is deliberately **no denormalised `release_id` or `pir_id`** on
`pir_action`. The cross-release worklist joins action → finding → pir → release.
A denormalised copy is one more thing that can disagree with the row it was
copied from, and the join is two hops on an indexed FK.

### 3.3 `pir_finding_incident`

| column | type | notes |
| --- | --- | --- |
| `tenant_id` | FK `tenant.id`, NOT NULL, indexed | |
| `finding_id` | FK `pir_finding.id` ON DELETE CASCADE, NOT NULL, indexed | |
| `incident_id` | FK `incident.id`, NOT NULL, indexed | |
| `note` | `Text` nullable | why this incident evidences this finding |

`UniqueConstraint(finding_id, incident_id)` as `uq_pir_finding_incident`.
**Hard-deleted**, per the junction-record convention in CLAUDE.md — removing a
citation is a correction, not history.

One incident may evidence several findings, on several PIRs, on several
releases; one finding may cite several incidents. Neither direction is
constrained, because both happen: one incident often exposes two distinct
process failures, and one process failure often produces a run of incidents.

### 3.4 Changes to `pir`

Keeps `tenant_id`, `release_id`, `summary`, `status` (`draft` | `complete`),
`completed_at`, `created_by`, `deleted_at`. Still **exactly one PIR per
release** — `create_for_release`'s 409 is unchanged.

Drops `incident_id`, `root_cause`, `what_went_well`, `what_went_wrong` and
`action_plan`, along with the index `ix_pir_tenant_incident`, after the backfill
in §7.

## 4. Services

`pir_service` grows finding, action and citation operations, and the read model
becomes nested. Three rules:

- **The composite endpoint delegates; it does not re-implement.**
  `POST /incidents/{id}/pir-citation` (§5.3) calls the same
  `create_for_release` / `create_finding` / `create_action` / `add_citation`
  functions the release-side routes call. Two paths to one outcome must not be
  two definitions of that outcome.
- **`get_for_incident` is retired, not adapted.** It returns a single PIR by
  `scalar_one_or_none` on a column that is going away, and the relationship is
  no longer 1:1. It is replaced by
  `pir_service.citations_for_incident(db, tenant_id, incident_id) -> list[dict]`,
  which reads through `pir_finding_incident`.
- **`pir_status_for_incidents` keeps its name, vocabulary and batched shape**
  (`{incident_id: "draft" | "complete"}`, absent meaning `none`), but is
  computed over citations: `complete` if the incident is cited on any PIR whose
  status is `complete`, else `draft` if cited at all. The incident list column
  therefore needs no rework beyond its label. It stays one query for the whole
  page — a per-row lookup on a 50-row grid is 50 queries.

`list_actions` is the worklist query: joins action → finding → pir → release,
filters on status / owner / overdue / release / incident, and returns
`(rows, total)` through `fetch_page_rows`.

**Overdue** is `due_date < expiry_boundary(now)` on an action whose status is
`open` or `in_progress` — through `app/core/day_boundaries.py`, the same rule
A4's escalations, B2's grace periods, B5's teardown dates and C2's waivers
follow. The UI writes a due date at `T00:00:00Z`; comparing at instant
precision reads an action as overdue from one minute past midnight on the day it
is still due.

## 5. API

### 5.1 Release-side, under the existing `/releases/{release_id}/pir` prefix

- `GET /releases/{id}/pir` — the PIR with `findings[]`, each carrying
  `actions[]` and `incidents[]`. Nested lists are unbounded by page size and
  deliberately so: they are bounded by one entity's own structure, the class
  docs/pagination.md already exempts. That exemption gets written down there
  rather than left implicit.
- `POST /releases/{id}/pir/findings`, `PATCH` and `DELETE` on
  `.../findings/{finding_id}`.
- `POST /releases/{id}/pir/findings/{fid}/actions`, `PATCH` and `DELETE` on
  `.../actions/{action_id}`.
- `POST /releases/{id}/pir/findings/{fid}/incidents` (body: `incident_id`,
  optional `note`), `DELETE .../incidents/{incident_id}`.

`PATCH` bodies key on `model_fields_set`, so an omitted key means "leave alone"
and only an explicit null clears a value — the rule `ProjectUpdate` and
`EnvironmentUpdate` already follow. Every write schema declares
`extra="forbid"`: FastAPI and Pydantic drop unknown keys silently, and this
codebase has shipped that bug three times (`ProjectCreate.priority_rank`,
`POST /tenant/lifecycle-templates`' `required_fields`, `/releases/calendar`'s
date range).

### 5.2 The worklist

`GET /pir-actions` — a new router, `app/api/v1/pir_actions.py`:

- `page: Page = Depends(pagination())` and
  `sort: Sort = Depends(sorting(PIR_ACTION_SORTS, default="due_date"))`.
  Whitelist: `due_date`, `status`, `title`, `owner`, `release`, `created_at`.
  `apply_sort` first, then `pir_action.id` as the unique tiebreaker — due dates
  and statuses tie constantly, and without it `LIMIT`/`OFFSET` duplicates and
  drops rows across pages.
- Filters: `status`, `owner_id`, `overdue` (bool), `release_id`, `incident_id`.
  Every one runs in SQL before the window, so `X-Total-Count` describes the
  filtered set. No-selection is an **omitted key** in every case; there is no
  `all` value, because `buildParams`' own sentinel is `'all'` and a vocabulary
  containing it builds byte-identical params for two different states — four
  sub-projects have hit that already.

### 5.3 The incident-side composite

`POST /incidents/{incident_id}/pir-citation`, body:

```
{
  "release_id": 42,
  "finding_id": 7,          # cite an existing finding, OR
  "new_finding": {          # create one
    "title": "...", "detail": "...", "root_cause": "...",
    "actions": [{"title": "...", "owner_id": 3, "due_date": "..."}]
  },
  "note": "..."             # optional, on the citation
}
```

Exactly one of `finding_id` / `new_finding` — both, or neither, is a 422. The
handler creates the PIR for `release_id` if that release has none, creates the
finding if asked, and inserts the citation, all in the request's single
transaction. It exists because the dialog would otherwise make up to three calls
and `get_db` commits per request: a failure on call two leaves a PIR behind
that nobody asked for and no citation on it.

`release_id` is validated as a live release in the caller's active tenant. It is
**not** validated as implemented — the `COALESCE(actual_date, target_date) <=
now` rule in §6 is a picker filter, a helper for choosing well, not a rule about
what a PIR may be attached to. A release whose actual date nobody recorded must
not become unreviewable.

### 5.4 Two response shapes change

Both are consumed only by this repo's frontend.

- `IncidentDetailResponse.pir: IncidentPirRef | None` becomes
  `pir_citations: list[IncidentPirCitation]`, each
  `{pir_id, release_id, release_name, pir_status, finding_id, finding_title,
  root_cause, action_count, open_action_count, note}`.
- `IncidentListItem.pir_status` keeps its `none`/`draft`/`complete` vocabulary,
  derived as in §4.

Release and user names travel **with the row** rather than being resolved
against a separately-fetched collection — the rule the client-side-filtering
sweep produced, and the one `ReleaseSystemRead.system_name` and A3's
`owner_username` already follow. Owner names resolve through a batched lookup
that is **not tenant-qualified**, the rule A3, A4, B5 and C2 all state: under
master-admin impersonation the action's owner can legitimately sit outside the
PIR's own tenant, and a `User.tenant_id ==` join renders them as nobody.

## 6. Surfaces

### 6.1 The release's PIR tab

`ReleasePirTab.tsx` is 246 lines of five textareas today and would roughly
triple. It becomes `frontend/src/components/releases/pir/`:
`ReleasePirTab.tsx` (summary, draft ⇄ complete toggle, the two sections),
`PirFindingCard.tsx`, `PirFindingDialog.tsx`, `PirActionsTable.tsx`,
`PirActionDialog.tsx`, `PirIncidentCitations.tsx`.

Two sections — *What went well* and *What went wrong*. A went-wrong card shows
its root cause, its actions (title, owner, due date, status, with overdue
styled from the same delta that produces the label — `formatExpiry` disagreed
with its own colour threshold for a day by not doing this), and its cited
incidents as chips linking to `/incidents/{id}`.

### 6.2 The incident's PIR panel

The panel lists citations — "Reviewed in **Release 24.3** — *No load test
before go-live*" — each linking to that release's PIR tab. Its one button is
**Link to a PIR**, and it is **never disabled**. There is no *Create PIR*
button, no mention of a fix release, and nothing anywhere that suggests
creating a release.

`LinkIncidentToPirDialog`:

1. **Release** — a searchable picker over releases where
   `COALESCE(actual_date, target_date) <= now`, since a release that has not
   gone live cannot have caused a production incident. Delivered as a new
   `?implemented=true` filter on the existing bounded, sorted `GET /releases`;
   omitting the key means no filter. Defaults to the incident's causal release
   when that release qualifies, otherwise nothing is preselected.
2. **Finding** — a radio: *cite an existing finding* (a dropdown of that
   release's went-wrong findings, empty and disabled when the release has no
   PIR yet) or *create a new finding* (title, what went wrong, root cause, and
   optionally a first action with owner and due date).
3. Submit → §5.3.

The "release has no PIR yet" case is not an error and shows no warning: the
PIR is created as part of the citation. That is the *"choose a release and
create a PIR with an action to associate the incident with"* journey, and it
must not cost more clicks than citing an existing one.

### 6.3 The cross-release worklist

`frontend/src/pages/pir/PirActionList.tsx` at `/pir-actions`, on
`useServerGrid`, with a nav entry. Columns: action, release, finding, owner, due
date, status, incidents cited. Filters: status, owner, overdue, release. Bound
to the server-side filters in §5.2 — no fetching a page and filtering it in the
browser, and no `.find()` by id into a capped collection, both of which
docs/pagination.md's sweep found repeatedly.

This page is the point of the feature. Actions that live only inside the
release tab they were raised in are exactly the ones nobody does.

## 7. Migration and backfill

`pirfindings` creates the three tables, backfills, then drops the five columns
and `ix_pir_tenant_incident`. For each existing PIR row:

- A `went_well` finding titled **"What went well (migrated)"** with
  `detail` = the old `what_went_well`, if that text was non-empty.
- A `went_wrong` finding titled **"What went wrong (migrated)"** with
  `detail` = the old `what_went_wrong` and `root_cause` = the old `root_cause`,
  created if **any** of `what_went_wrong`, `root_cause`, `action_plan` or
  `incident_id` had a value — so nothing is stranded by the absence of one
  field.
- The old `action_plan`, if non-empty, as one `open` action on that went-wrong
  finding, titled **"Action plan (migrated)"**, with no owner and no due date.
- Where `incident_id` was set, a citation from that went-wrong finding —
  created bare and titled **"Incident (migrated)"** if there was no free text at
  all to hang it on.

Titles are fixed strings, never a truncation of the body, so no text is silently
lost to a 500-character column. `summary` is untouched throughout.

**Downgrade re-adds the five columns as nullable and does not reconstruct the
text.** That is stated in the migration's docstring rather than left for someone
to discover.

`tests/test_migration_schema_drift.py` compares column **name sets** only — not
types, defaults or indexes — so it is not evidence the hand-written DDL matches
the models. The backfill gets its own test on a scratch database. CLAUDE.md's
warning about `alembic downgrade -1` applies: it steps back from the current
head, not from your new revision, so never exercise this on the dev database.

No deploy step and no seeding: a tenant with no PIRs migrates to nothing.

## 8. Testing

- **`backend/tests/test_pir_records_never_refuses.py`** — the guard on the
  central promise. An incomplete PIR, a went-wrong finding, an overdue open
  action and a cited incident change nothing about the release's allowed
  transitions, the incident's allowed transitions, `GET /webhooks/can-deploy`,
  or `release_readiness_service.evaluate()`. Proved **non-vacuous** by inserting
  a real refusal into a transition path and watching the test fail — the step
  A1, A4, B4, B5 and B6 each took, and the reason those guards are trusted.
- **Migration backfill test** on a scratch database: legacy PIR rows with each
  combination of text and `incident_id` upgrade into the findings, actions and
  citations §7 describes, including the two edge cases (text but no incident,
  incident but no text).
- **Tenant isolation on every new endpoint**, each proved by mutation — the
  missing `tenant_id` filter appeared eight times on A1 alone and was never once
  caught by a pre-existing test. Note the trap B6 documented: when a fixture is
  built to make a row excluded, check which side of a join it lands on, or the
  filter under test is dead code in the test and live in production.
- **Both engines.** SQLite and PostgreSQL
  (`TEST_DATABASE_URL=postgresql+asyncpg://...`), because column widths, partial
  indexes and date arithmetic diverge.
- **Frontend suite**, plus tests that *re-render* rather than only mounting —
  stale-effect and referential-identity bugs on this codebase have survived
  mount-only tests three times.
- **A browser pass at the end**, walking the whole journey: incident → Link to a
  PIR → new finding + action → the release's PIR tab → the `/pir-actions`
  worklist. On C2 and C4 the browser pass is what found the defects a fully
  green suite had missed, including a tab strip that overflowed off screen.

## 9. Decisions and scope

**Permissions are unchanged.** Any authenticated tenant member reads and writes
PIR content, matching today's PIR endpoints and RAID item writes. No new role
gate is invented mid-feature.

**Out of scope, deliberately:**

- **The configurable close gate** of requirements.md §2.5 ("PIR completion can
  be configured as a gate before a release is formally closed"). It would make
  this the first PIR work that refuses something, on releases people consider
  finished, and it belongs with Phase 9 C6's closeout rather than here.
- **Readiness integration.** Overdue PIR actions do not appear in
  `release_readiness_service.evaluate()`. A PIR is written after go-live; a
  readiness verdict is read before one.
- **Promoting a PIR action to a RAID item on a future release.** A real
  workflow, and a second entity relationship to design; not needed to make PIR
  actions trackable.
- **Templates updated from PIRs** (requirements.md §2.2). The action can say to
  do it; nothing automates it.
