# Pagination Sub-project B — Restructure, Then Bound

> Date: 2026-07-30 | Status: approved, not yet implemented
> Sub-project **B** of the pagination programme. Branches off `feature/pagination-sweep` (sub-project A, PR #36), which supplies the primitive.
> Predecessor spec: [2026-07-30-pagination-sweep-design.md](2026-07-30-pagination-sweep-design.md)

## Problem

Sub-project A bounded 22 list endpoints and left a documented remainder: endpoints
whose services **filter or merge rows after the query has run**. A `LIMIT` on those
would window the pre-filter set, so `?limit=50` could return 3 rows while hundreds
matched — results that are quietly wrong rather than merely large. A deliberately
declined to bound them.

B restructures each of those queries so the filtering happens in SQL, then bounds them.

## What makes B different from A, and how that changes the work

A was mechanical and backward compatible by construction: add a parameter, set a
header, append a tiebreaker. Its risk was *omission* — a missed caller, a missing
tiebreaker — and its tests asserted **shape**.

B changes what rows come back. Its risk is *divergence*: SQL that returns a subtly
different set than the Python it replaces. Shape tests cannot catch that. So the
central deliverable of every task in B is a **differential test**: build fixture data
that exercises the edge cases, run the old Python predicate and the new SQL query over
the same rows, and assert the two agree exactly. Where the old code is being deleted,
the test embeds the old predicate as a local reference implementation.

A second consequence: A could not break a client, because bare arrays stayed bare
arrays. Two endpoints in B **do** need response-contract changes, called out below.

## Endpoints in scope

| # | Endpoint | Why it was blocked | Restructure |
|---|---|---|---|
| 1 | `GET /releases/{id}/raid` | `rag` and `overdue` filtered in Python | severity-domain `IN` clause + SQL predicates |
| 2 | `GET /systems/{id}/dependencies` | two queries concatenated | single `OR` query |
| 3 | `GET /subsystems/{id}/dependencies` | two queries concatenated | single `OR` query |
| 4 | `GET /environments/{id}/versions` | `current_only` deduped in Python | `ROW_NUMBER()` window |
| 5 | `GET /releases/{id}/dependency-alerts` | filtered in Python, plus an N+1 | join + `IS DISTINCT FROM` |
| 6 | `GET /releases/{id}/membership` | merges two queries, returns a dict | bound the `history` list |

---

## 1. RAID — `GET /releases/{release_id}/raid`

`raid_service.list_items` runs its query, then applies two Python filters:

```python
if rag is not None and config is not None:
    items = [i for i in items if globals()["rag"](severity(i.probability, i.impact), cfg) == rag]
if overdue:
    items = [i for i in items if i.review_date and i.review_date < now
             and i.status not in ("closed", "promoted", "met")]
```

`overdue` is trivially SQL. `rag` is not, and the obvious translation is wrong.

### Why `OR`-of-`BETWEEN` would be a bug

`rag()` returns the label of the **first** band in list order whose `[min, max]`
contains the severity. `rag_bands` is a `JSON` column typed `list[dict[str, Any]]`
([`app/api/v1/schemas/raid.py:90`](../../../backend/app/api/v1/schemas/raid.py)) with
**no validation** — no overlap check, no ordering guarantee, no key schema. A tenant can
store overlapping bands today.

Translating the requested label into an `OR` of its bands' ranges would therefore
include items that an *earlier* band with a different label already claimed. For the
default non-overlapping config (`1–5 green`, `6–14 amber`, `15–25 red`) the two agree;
for an overlapping config they diverge silently.

### The translation that is correct by construction

Severity is `probability * impact`, and both factors are bounded by the tenant's
configured scales, so the severity domain is small — 25 values by default. Enumerate it,
evaluate the **existing `rag()` function** on each value, and emit an `IN` clause:

```python
def _severity_values_for_rag(cfg: dict, wanted: str) -> list[int]:
    """Severity scores that map to `wanted`, per the tenant's own bands.

    Evaluating the real rag() over the whole domain rather than translating band
    ranges into SQL keeps first-match semantics — including for overlapping bands,
    which nothing validates against.
    """
    p = len(cfg.get("probability_scale") or [])
    i = len(cfg.get("impact_scale") or [])
    return [s for s in range(1, p * i + 1) if rag(s, cfg) == wanted]
```

then `stmt.where((RaidItem.probability * RaidItem.impact).in_(values))`.

This reuses the production `rag()` unchanged, so the two cannot drift. `NULL`
propagation preserves the old behaviour for free: if either factor is unset the product
is `NULL`, `NULL IN (...)` is `NULL`, the row is excluded — exactly what
`severity() → None → rag() → None != wanted` did.

If `values` is empty the filter must become `false()`, not be skipped — an unknown rag
label matched nothing before and must match nothing now.

`overdue` becomes:

```python
stmt = stmt.where(
    RaidItem.review_date.isnot(None),
    RaidItem.review_date < now,
    RaidItem.status.notin_(("closed", "promoted", "met")),
)
```

### Ordering

Currently `.order_by(RaidItem.item_type, RaidItem.seq)`. Neither is unique on its own
and the pair is not guaranteed unique either, so `RaidItem.id` is appended.

### Caller note

`raid_service.summary` calls `list_items` with no `rag`/`overdue` and aggregates the
whole release. It must keep receiving every row — `page=None`.

---

## 2 & 3. Dependencies — `GET /systems/{id}/dependencies`, `GET /subsystems/{id}/dependencies`

Both services run two queries and the endpoint concatenates them:

```python
outgoing, incoming = await dependency_service.list_system_dependencies(...)
```

### It is an `OR`, not a `UNION ALL`

The predecessor spec assumed these needed `UNION ALL`. They do not. The two queries are
identical but for `from_*_id == X` versus `to_*_id == X`, so one query with an `OR`
returns the same rows:

```python
select(SystemDependency).where(
    SystemDependency.tenant_id == tenant_id,
    or_(SystemDependency.from_system_id == system_id,
        SystemDependency.to_system_id == system_id),
)
```

A row could only be duplicated by this if it matched both sides — a self-dependency —
and both services reject those explicitly (*"A system cannot depend on itself"*,
[`dependency_service.py:80`](../../../backend/app/services/dependency_service.py); the
subsystem equivalent at `:275`). The row sets are provably identical.

### Preserving output order

Today the response is grouped: all outgoing (by id), then all incoming (by id). A plain
`ORDER BY id` would interleave them — a visible change for any client that relies on the
grouping. A `CASE` reproduces the current order exactly *and* is total:

```python
.order_by(case((SystemDependency.to_system_id == system_id, 1), else_=0),
          SystemDependency.id)
```

### Deriving direction

`is_incoming` is currently hardcoded per loop. It is derivable per row, which is what
the component endpoint already does
(`is_incoming=dep.to_subsystem_id == subsystem_id`,
[`app/api/v1/dependencies.py:43`](../../../backend/app/api/v1/dependencies.py)). The
system endpoint adopts the same form.

---

## 4. Versions — `GET /environments/{env_id}/versions`

With `current_only=True`, `version_service.list_versions` fetches every version row and
keeps the latest per subsystem in Python. In SQL that is a window function:

```python
ranked = (
    select(EnvironmentSubSystemVersion,
           func.row_number().over(
               partition_by=EnvironmentSubSystemVersion.subsystem_id,
               order_by=(EnvironmentSubSystemVersion.installed_at.desc(),
                         EnvironmentSubSystemVersion.id.desc()),
           ).label("rn"))
    .where(...)
    .subquery()
)
```
then select where `rn == 1`.

`ROW_NUMBER() OVER (PARTITION BY ...)` is verified working on this repo's SQLite
(3.50.4) and on PostgreSQL, so no dialect gate is needed.

`installed_at` is not unique, so `id DESC` is the tiebreaker *inside* the partition —
this matters, because it decides which row wins when two versions share a timestamp. The
Python version resolved that by whichever row the outer `ORDER BY` happened to return
first, which was itself undefined. The new behaviour is deterministic; the differential
test must be written knowing the old one was not, so it must not assert equality on the
tied case — only that exactly one row per subsystem is returned.

Final ordering is `subsystem_id` (matching today's `sorted(seen.values(), ...)`), then
`id` for totality.

---

## 5. Dependency alerts — `GET /releases/{release_id}/dependency-alerts`

`release_dependency_service.get_dependency_alerts` fetches every dependency, then per
dependency issues **another query** for its target release, then `continue`s past any
whose release is missing or whose `target_date` is unchanged.

Both the filter and the N+1 dissolve into one join:

```python
select(ReleaseDependency, Release)
    .join(Release, and_(Release.id == ReleaseDependency.depends_on_release_id,
                        Release.tenant_id == tenant_id,
                        Release.deleted_at.is_(None)))
    .where(ReleaseDependency.release_id == release_id,
           ReleaseDependency.tenant_id == tenant_id,
           Release.target_date.is_distinct_from(
               ReleaseDependency.last_dependency_target_date))
    .order_by(ReleaseDependency.id)
```

The inner join reproduces `if dep_release is None: continue`; `is_distinct_from`
reproduces `if current == prior: continue` including both-`NULL`, which the old code
also skipped. SQLAlchemy renders it `IS DISTINCT FROM` on PostgreSQL and `IS NOT` on
SQLite — both verified available here.

The remaining `diff_days` computation stays in Python: it derives a field per surviving
row and drops nothing, so it is enrichment and safe to window.

This is a multi-column select, so it uses `fetch_page_rows`.

---

## 6. Membership view — `GET /releases/{project_release_id}/membership`

The only endpoint in the programme whose response is not an array. It returns
`{"current": …, "history": [...]}`, built from two queries.

`current` is a single record and needs no bounding. `history` is the growing list, so
**`history` is bounded and `X-Total-Count` reports its total.** The response stays a
dict; the header describes `history`, and the doc says so explicitly, because a header
whose subject is ambiguous is worse than none.

### A behaviour that must be preserved, not fixed

`list_history_for_project` returns **every** membership for the project, including the
accepted one, and the endpoint then prepends `current` — so an accepted membership
currently appears both as `current` and inside `history`. That looks like a bug. It is
out of scope: changing it is a client-visible semantic change unrelated to pagination,
and bundling it here would make the diff hard to review and the differential test
meaningless. The restructure preserves it, and it is recorded as a follow-up.

`get_current_membership_for_project` stays a separate query — it is a single-row lookup,
not a list.

---

## Testing

**Differential tests are the core deliverable**, one per restructured endpoint. Each
seeds fixture data covering the edge cases, computes the expected set with the old
Python predicate (embedded in the test as a reference implementation), and asserts the
new SQL query returns exactly that. Edge cases each test must cover:

| Endpoint | Edge cases |
|---|---|
| RAID | overlapping bands; `NULL` probability or impact; unknown rag label; band boundary values; `overdue` with `NULL` review_date and each excluded status |
| dependencies | outgoing-only, incoming-only, both; output grouping order preserved |
| versions | two versions sharing `installed_at`; single-version subsystem; `current_only` false vs true |
| dependency-alerts | dependency whose release is soft-deleted; both dates `NULL`; one `NULL`; equal dates; changed dates |
| membership | accepted membership appearing in both `current` and `history` |

Plus, per endpoint: a conformance check that the bounded endpoint returns a bare array
(except membership), sets `X-Total-Count`, and 422s past its cap. Parent-id-nested
endpoints get targeted tests rather than `BOUNDED_ENDPOINTS` rows, because the
conformance sweep runs against an empty tenant and these 404 without a real parent.

**Cadence** — measured in A and carried forward: the full suite is ~6 min on SQLite and
~14 min on PostgreSQL. Per task, run targeted tests on SQLite. Run the full dual-engine
suite at two checkpoints: after the RAID task, and at the end. The window function and
`is_distinct_from` are dialect-sensitive, so **their tasks additionally run their own
targeted tests on PostgreSQL** rather than waiting for a checkpoint.

## Lessons carried forward from sub-project A

These are process requirements, not suggestions — each cost real time in A.

1. **Read the model before writing a fixture.** A's plan guessed at model columns four
   times and was wrong four times, every one a non-nullable column or FK. Every fixture
   in B's plan is written against a model that has been read.
2. **Sweep callers on every changed signature** across `app/`, `tests/` **and**
   `scripts/`, including service-to-service calls. This was A's most common near-miss.
3. **Do not run the full suite per task.** Targeted runs are seconds; the full suite is
   ~20 minutes across both engines.
4. **Do not background test runs** — use a generous foreground timeout. A 14-minute run
   is expected, not hung.
5. **`request.getfixturevalue` is unusable** on async fixtures under this repo's pinned
   pytest-asyncio 1.4.0. Pass fixtures as normal parameters.
6. **Never fabricate a foreign key id** — SQLite now enforces FKs and ~40 tests once
   passed while inserting broken rows. Use `tests/factories.py`.
7. **Documentation must be exhaustive, with the count and the command to re-derive it.**
   A's docs implied completeness three times before achieving it.
8. **Ordering must be total** — every bounded query ends in a unique key. In A this was
   shown to matter empirically: with a tiebreaker removed, pagination broke
   deterministically on PostgreSQL across repeated runs.

## Risk

The failure mode is a SQL predicate that disagrees with the Python it replaced, on data
no test covers. The differential tests are the control, and their value depends entirely
on the edge cases enumerated above being seeded — a differential test over rows that all
take the same branch proves nothing. Reviewers should check the fixtures, not just the
assertions.

Secondary risk: `GET /releases/{id}/membership` changes shape for clients that read
`history` expecting it complete. The default cap is 500; any project with more
memberships than that would previously have received all of them.

## Documentation

`docs/pagination.md` moves these six from "blocked on a query restructure" into the
bounded table, records that the blocked group is now empty, notes the membership
header's subject, and keeps its endpoint-count line and re-derivation command accurate.
`CLAUDE.md`'s counts are updated to match.

Recorded as follow-ups, not done here: the duplicated accepted membership; and
`/releases/calendar` and `/timeline`, which still filter after a hardcoded `limit=500`.
