# Environment comparison — design

**Status**: design, not started. Phase 6, sub-project 1 of 4.

## Why this, and what Phase 6 actually still needs

`docs/phases/phase-6.md` lists thirteen unchecked tasks. Six of them are already shipped and
one is obsolete. Verified against the code, not the roadmap:

| phase-6.md says pending | Reality |
|---|---|
| Terraform parser | **Shipped** — `terraform_import_service.py`, `POST /import/terraform`, UI on System detail |
| Docker Compose parser | **Shipped** — `docker_compose_import_service.py`, writes `ComponentDependency` with `source=docker_compose` |
| Topology API endpoints | **Shipped** — `/systems/{id}/topology`, `/environments/{id}/topology` |
| React Flow topology diagram | **Shipped** — `TopologyCanvas` + ELK, focus, filter, collapse |
| Environment topology page | **Shipped** — env-topology SP1–SP3 |
| GitHub repo link on System detail | **Shipped** — the field exists and renders |
| Neo4j sync consumer | **Obsolete** — Neo4j removed 2026-07-30 |

`phase-6.md` should be corrected as part of this work; leaving it is how the next person
plans against a roadmap that is two-thirds wrong.

What genuinely remains is four independent sub-projects: **environment comparison** (this
spec), **drift detection**, **GitHub App/OAuth + repository scanning**, and **env-topology
SP4** — the group-by-system/host toggle, whose machinery is complete and whose `setGroupBy`
is currently dead code, leaving only the control to wire.

Comparison was chosen first because it needs no credentials, no external integration and no
new infrastructure, and it answers a question the existing data already supports.

## What it is for

Two things, and the design serves both without building two features:

- **Triage** — "it works in SIT but not UAT, what's different?" Neither side is authoritative.
- **Fidelity** — "is UAT a faithful copy of Production?" One side is nominated as the
  reference and gaps read as risk.

The API is **symmetric** and knows nothing about references. Nominating a reference is
presentation: it relabels `*_only` as "missing from" / "extra vs" reference, and surfaces
*mocked in the non-reference where the reference is real* as the fidelity risk. The same
response serves both framings, so there is one thing to test and one thing to cache.

## Dimensions compared

Four, all backed by existing tables. No new tables, no migration.

1. **Presence** — systems (`environment_system`) and subsystems (`environment_subsystem`).
2. **Mocked vs real** — `environment_subsystem.is_mocked`.
3. **Deployed version** — current version per subsystem.
4. **Host shape** — how each subsystem is deployed.

### Host shape is the one that needs a definition

Host *names* differ between environments by design (`sit-app-01` vs `uat-app-01`), so
comparing identity would mark every subsystem as different and make the diff useless.

`host_shape` is instead a **sorted list of `{component_type, role, count}`**, built from
`environment_subsystem_host` joined to `infrastructure_component.component_type`, with
`role` from the junction. `2 × app-server (primary)` therefore compares equal across
environments regardless of hostnames, while a missing standby, a different replica count,
or a different class of host all show up.

Sorting is what makes equality a plain structural comparison rather than a set intersection.

### Rules that keep the diff quiet

- `mock_notes` differing is **not** a difference — free text would make every row differ.
  It is displayed, not compared.
- A version absent on **both** sides is **not** a difference. Absent on one side is.
- Version comparison is on the *current* version per subsystem. `version_service` already
  dedups with a `ROW_NUMBER()` window under `current_only` — reuse it rather than
  reimplementing the dedup.

## API

`GET /api/v1/environments/compare?left={id}&right={id}`

**Declared before `/{env_id}`.** Otherwise FastAPI matches `compare` against the int path
parameter and returns 422. The same ordering trap as `/releases/calendar`.

- 404 if either environment is missing or outside the caller's tenant.
- 422 if `left == right`.

```
left/right:  { id, name, status }
systems:     [ { system_id, name, presence } ]
subsystems:  [ { subsystem_id, name, system_id, system_name,
                 presence,
                 left:  { is_mocked, mock_notes, version, host_shape } | null,
                 right: { … } | null,
                 differences: [ "presence" | "mocked" | "version" | "host_shape" ] } ]
summary:     { compared, differing, by_kind: { presence, mocked, version, host_shape } }
```

`presence` is one of `both`, `left_only`, `right_only`, on both systems and subsystems.

`version` is the version **label** (a string) or `null`. `host_shape` is the sorted list
described above, and `[]` when no hosts are recorded — empty on both sides is not a
difference, empty on one side is.

**When `presence != both`, `differences` is exactly `["presence"]`** and nothing else. The
absent side has no version, no mocked flag and no host shape, so comparing them would report
a missing subsystem as *also* a version and host difference, inflating every count in
`summary.by_kind`. A subsystem present on one side is one difference, not four.

`summary.compared` counts **subsystems** in the union of the two environments;
`summary.differing` counts those with a non-empty `differences`. `by_kind.presence` likewise
counts subsystems — system-level presence is reported in `systems` and summarised separately
in the UI, not folded into these counts.

**`differences` is computed server-side, deliberately.** The UI has a "differences only"
filter and a summary count. Deriving those separately is how a filter and its own footer
come to disagree — which happened three times in the pagination programme. One source,
computed once, and the summary is built from the same arrays the rows carry.

**Ordering**: differing rows first, then system name, then subsystem name, with
`subsystem_id` as a tiebreaker. Deterministic across both engines even though nothing here
is paged.

**Not paged, deliberately.** The result is bounded by the union of two environments' own
subsystems — dozens, not thousands. If that ever stops being true, the diff must be computed
**before** windowing; windowing first would diff a page rather than the environments, which
is the mistake `/releases/calendar` made by filtering after the query.

## Frontend

Route `/environments/compare`, under Environment Definition.

URL carries the whole view — `?left=2&right=3&reference=left&diff_only=1` — so a comparison
is shareable and survives a refresh. `useServerGrid` is *not* used: nothing here pages or
sorts server-side, and the hook's machinery would be dead weight.

**Pickers use `useAllEnvironments()` and surface its `truncated` flag.** That hook exists
because a picker reading a paged slice silently offers a subset, and it now coalesces
in-flight requests — which matters here, where two pickers mount in the same commit and
would otherwise issue two identical GETs.

**Layout**: pickers + swap + reference selector (None / Left / Right) + differences-only
toggle; a summary strip counting differences by kind, each count clickable to filter; then
the body grouped by system, one row per subsystem, left and right side by side, with a chip
per difference kind.

**A grouped MUI `Table`, not `DataGrid`.** Two-sided cells under system group headers is not
something DataGrid expresses well, and the standing guidance is that DataGrid is recommended
rather than mandatory. This also avoids the `disableColumnFilter` trap that shipped a filter
contradicting its own footer twice during the pagination programme.

**The equal case says so** — "These environments match on all four dimensions" — rather than
rendering an empty table. Everything renders by name: environments, systems, subsystems,
component types. Never `#id`.

## Testing

Backend, dual-engine, every test verified by breaking what it covers:

- **Same host shape, different hostnames → not a difference.** The most important test here:
  it is the entire justification for `host_shape`, and the one that fails if anyone
  simplifies it back to comparing host identity.
- Different count, different role, different component type → each a difference.
- Version differing / matching / present on one side only / **absent on both (not a
  difference)**.
- `is_mocked` differing is a difference; `mock_notes` differing alone is not.
- Presence at both system and subsystem level.
- **A subsystem present on one side only reports exactly `["presence"]`** — not presence
  plus version plus mocked plus host_shape. This is the assertion that keeps
  `summary.by_kind` honest, and the natural implementation (compare every dimension, then
  add presence) gets it wrong.
- **`summary` counts agree with the per-row `differences` arrays**, asserted directly.
- Ordering deterministic, differing first.
- 404 unknown environment, 404 cross-tenant, 422 same environment on both sides.

Frontend:

- URL round-trip for all four parameters.
- Swap actually swaps, and the URL follows.
- The differences-only filter agrees with the summary count.
- **Changing the reference relabels without refetching** — proving it is presentational.
- Equal environments show the match message rather than an empty table.
- Picker truncation is surfaced.

## Out of scope

- **Stored/materialised comparison history** — persisting runs so fidelity drift can be
  trended ("UAT has diverged from Production over six weeks"). Real value for the fidelity
  use case, but it needs a schema, a retention policy and a refresh story, and nothing yet
  asks for history. **Recorded as the natural follow-on** to this sub-project.
- Drift detection, GitHub scanning, env-topology SP4 — the other three Phase 6 sub-projects,
  each getting its own spec.
- Comparing more than two environments at once.
- Environment-level attributes beyond composition (operating hours, custom fields, status
  history). Composition is what explains "works here, not there"; the rest can be added
  as dimensions later without changing the response shape.
