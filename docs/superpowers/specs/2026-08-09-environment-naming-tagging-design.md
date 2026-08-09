# Phase 7 B2 — Naming & tagging conventions, and untagged quarantine

> Status: designed 2026-08-09. Implements [requirements.md §2.12](../../requirements.md)'s
> naming bullet: *"Naming & tagging conventions: enforced naming pattern; mandatory tags (owner,
> cost centre, tier, expiry); quarantine/terminate untagged resources after a grace period"*.
> Gated on B1 (governance fields), which is shipped.

## The one-sentence version

A tenant declares what an environment's **name** must look like and which **attributes** it must
carry; every environment is then judged against that policy, and one that has been failing it for
longer than a grace period reads as **quarantined** — a label and a filter, nothing more.

## What B2 does not do, and why that is the design

**B2 ADVISES; IT NEVER BLOCKS A BOOKING.** A quarantined environment can still be booked,
transitioned, deployed to and reported on exactly as before. This is the same promise A3 makes
about usage-agreement warnings and A4 about contention, and the guard is the same shape: a named
test, `test_quarantine_changes_no_booking_behaviour`, descended from A1's
`test_an_agreement_changes_no_booking_behaviour`. **If it ever fails, B2 has started acting.**

**There is exactly one thing B2 refuses, and it is not quarantine**: saving a *changed* name that
does not match the pattern is a 422. That is the "enforced naming pattern" half of the
requirement. Everything else — missing attributes, existing bad names, quarantine itself — is
reporting.

Also explicitly out of scope:

- **Terminating anything.** §2.12 says "quarantine/**terminate** untagged resources". EnvManager
  is a register, not a cloud control plane: it has no credentials to destroy a resource with and
  no way to know whether the row in front of it still corresponds to anything running. Recorded
  as a **deviation on record**, below.
- **A `QUARANTINED` environment status.** Quarantine is derived on read. B1 made the same call
  about `reserved_now` for the same reason — an environment that is quarantined is still active,
  and a stored status needs invalidating from directions nothing watches.
- **A second per-environment metadata system.** Tenant custom fields already give environments
  arbitrary required attributes. B2 defines a *policy over what already exists*; it ships no
  `environment_tag` table. §2.16's future "cloud tag inventory" reconciliation may want one — that
  is that phase's call to make, with a real integration in hand.
- **Any change to `?governance_gap=`.** See the overlap note below.
- **Notifications.** The Environments grid is the surface. No email, no digest.
- **Naming rules for anything but environments.** §2.12 is the environment-lifecycle section.
  Systems, releases and bookings are untouched.

## Decisions taken during brainstorming

| Question | Decision |
| --- | --- |
| What is a "tag"? | A **policy over attributes that already exist** — B1's columns and existing custom-field keys. No new tag entity. |
| What does quarantine do? | **Advisory only.** A flag, a filter and a banner. No booking path changes; no exemption entity, because nothing needs exempting from a label. |
| Naming enforcement point | **Refuse only a changed name.** A full-form save re-sending an existing bad name is accepted. |
| Pattern language | **Regex.** Rejected a segment template (safer, could cross-check `{tier}` against the real tier) as too inflexible for real estates. |
| Where the regex runs | **One Python evaluator, verdict stored** on `environment.name_compliant`. |
| Grace clock | `max(policy.effective_from, environment.created_at)`. Nothing new stored, nothing to invalidate. |

## Why the verdict is stored — the one place this design breaks a house rule

Every filter on a paged endpoint must run **in SQL**; a Python-side filter windows the page before
the filter and returns quietly wrong results ([docs/pagination.md](../../pagination.md)). But **no
regex is portable across both engines**: PostgreSQL has `~`, SQLite has no `REGEXP` without a
registered callback.

Three options, and why the stored verdict wins:

- **Dialect regex in SQL** would put *three* regex engines behind one rule — Python's `re` at save
  time, PostgreSQL's POSIX ARE in the list query, and Python-via-callback on SQLite. Those engines
  disagree on real patterns, so a name refused at save could report compliant in the list. That is
  the "two mechanisms enforcing one outcome, so one test cannot guard both" failure A2 produced
  three times. It is also unindexable.
- **Filtering in Python after the query** is the pattern docs/pagination.md exists to forbid.
- **A stored verdict** makes Python's `re` the only regex engine in the system, and the filter an
  ordinary indexable column comparison.

The cost is a derived value that can go stale, so its invalidation surface is enumerated
exhaustively below and tested directly. **The tag half needs none of this** — a missing owner,
expiry or operations group is a plain SQL predicate and stays computed.

## Data model

### `environment_naming_policy`

One row per tenant (`tenant_id` FK, `unique=True`), no `deleted_at` — shaped like `RaidConfig`,
this codebase's existing per-tenant config table.

| column | type | notes |
| --- | --- | --- |
| `tenant_id` | FK, unique, indexed | |
| `is_enabled` | bool, not null, default false | The off switch. Deleting the row is not offered; it would lose the pattern. |
| `name_pattern` | `String(500)`, nullable | Null means "no naming rule, attributes only". |
| `name_pattern_example` | `String(200)`, nullable | A worked example, shown in the admin UI **and in the 422**. Refused at save if its own pattern rejects it — otherwise the error message teaches a name that will also be refused. |
| `required_attributes` | JSON list, not null, default `[]` | Vocabulary: `owner`, `expiry`, `operations_group`, and `cf:<field_key>`. |
| `grace_days` | int, not null, default 14, `ge=0` | |
| `effective_from` | timestamptz, not null | Bumped to now whenever `name_pattern` or `required_attributes` changes, **in either direction** — see below. |

`effective_from` is deliberately **not** bumped by an edit to `grace_days`, `is_enabled` or the
example: those do not change what is being asked of an environment. It *is* bumped when a
requirement is relaxed as well as when one is added, because "stricter" is not a decidable
property of a regex change and granting fresh grace for a relaxation is harmless.

### `environment.name_compliant`

Nullable boolean. **Null means "no pattern applies"** — no policy row, policy disabled, or
`name_pattern` null. It does not mean "unknown" and it does not mean "failing"; every clause and
every cell must treat null as compliant.

### Three things deliberately absent

- **`tier` is not in the vocabulary.** `environment.tier_id` is already `nullable=False`, so a
  policy requiring tier would be a check that can never fail — a permanently-green row that reads
  as governance. §2.12 lists tier as a mandatory tag; B1 made it structurally mandatory instead,
  which is stronger.
- **No `non_compliant_since`.** Grace runs from `max(policy.effective_from, created_at)`. The
  consequence, accepted: an environment that breaks compliance *later* — its owner is deleted — is
  quarantined at once with no fresh grace. The alternative is a second stored derived value whose
  invalidation surface reaches far outside any environment write (deleting a user, editing a
  custom-field definition).
- **No `QUARANTINED` status**, as above.

## Two overlaps, named rather than papered over

**1. `?governance_gap=` stays exactly as it is** — missing owner **or** missing operations group,
B1's fixed pair. The policy's vocabulary can name those same two attributes, so a tenant can
produce two filters that agree with each other. That is accepted. `governance_gap` already changed
meaning once (B3a widened it to include the operations group), on first deploy it matched every
environment in the estate, and it looked exactly like a bug; changing it a second time to mean
"whatever this tenant's policy says" would make a filter's meaning tenant-dependent. The
distinction to document: **`governance_gap` is the fixed built-in pair; `compliance_gap` is the
tenant's own policy.**

**2. Custom-field `required` and policy `required_attributes` bite differently, and both stay.**
`required` on a `CustomFieldDefinition` refuses a *write* (422 from `validate_custom_fields`); the
policy only feeds the *verdict*. This is the point rather than an accident: a tenant can declare
cost centre mandatory for reporting without freezing every existing environment's next save. The
admin panel says so in as many words.

## Two verdicts, defined once

Everything downstream derives from these two, and they are not the same thing:

- **`compliance_gap`** — the name fails the pattern **OR** any policy-required attribute is
  missing. **No grace applies**: an environment is in gap the moment the policy says so.
- **`quarantined`** — in gap **AND** grace has fully elapsed. Quarantine is a strict subset of gap.

When a tenant has no policy row, or the policy is disabled, **nothing is in gap and nothing is
quarantined**: `?compliance_gap=false` and `?quarantined=false` return the whole estate, and
`true` returns nothing. `noncompliance_clause(None)` and `quarantine_clause(None, now)` say so
rather than being skipped by their callers, so no caller can forget.

## The evaluator

A new `app/services/environment_compliance_service.py` owns **every regex decision in the
codebase**.

```
load_policy(db, tenant_id)              -> Policy | None
name_matches(pattern, name)             -> bool          # the ONE re.fullmatch call site
assert_name_allowed(policy, submitted, stored)           # 422 only on a CHANGED name
recompute(env, policy)                                   # sets env.name_compliant
recompute_tenant(db, tenant_id, policy)                  # bounded batch, on policy write
noncompliance_clause(policy)            -> SQL boolean
quarantine_clause(policy, now)          -> SQL boolean | None
gaps_for_environments(rows, policy)     -> dict[int, list[str]]   # once per RESPONSE
```

`gaps_for_environments` takes the **whole page** and returns a message list per environment id.
There is deliberately no per-row public helper: A3 shipped `describe_gap` as a single-booking
cross-check and had to write "no production caller" in its docstring to stop a 50-row page costing
~150 queries. Here the inputs are already on the selected rows, so the batch form costs nothing
extra and the per-row form would only invite the mistake.

`re.fullmatch`, not `re.search`: a pattern anchors by default, because a tenant writing `dev-.*`
and having `xxdev-1` accepted is the likelier error. Compiled patterns are cached by pattern
string.

### The stored verdict's whole invalidation surface

1. `environment_service.create_environment` — evaluate before insert.
2. `environment_service.update_environment` — only when `name` is in `model_fields_set` **and**
   differs from the stored value.
3. `environment_request_service` fulfilment — B3b's **second** `Environment(...)` construction
   site.
4. A policy write (content, enable, disable) — `recompute_tenant`.
5. Nothing else — and in particular **not** the migration, which needs no backfill (see below).

There are exactly two construction sites for an `Environment` row, and the codebase already
anticipated this shape: `assert_name_available` is shared between them with a comment saying it
exists so the two checks cannot drift apart. The compliance check follows it.

### Fulfilment must never 422 on the naming rule

An approved environment request whose fulfilment is refused is an **unrecoverable state** — the
exact class B3b produced twice. So the pattern is checked when the request is **submitted**, and
fulfilment only ever *records* the verdict, creating a non-compliant environment if that is what
the approved request says. This rule gets its own named test.

### ReDoS

The pattern is tenant-admin-supplied and runs in the server process, so one catastrophic pattern
pins a worker for **every** tenant, and Python's `re` has no timeout. Mitigation at **policy save
time**, not per match:

1. cap the pattern at 500 characters;
2. compile it — 422 on `re.error`;
3. run it against the example and a 200-character adversarial probe inside
   `asyncio.wait_for(asyncio.to_thread(...))`, and refuse the pattern if it does not finish.

This reliably catches the accidental `(a+)+$` and is honest about what it is: a footgun guard, not
a security boundary against a determined admin, who can still write a pattern that is slow but
finishes. **Accepted risk**, with the upgrade path recorded — the `regex` package's per-match
`timeout=`, which is a new dependency and needs a
[dependency-audit](../../dependency-audit.md) entry.

The same guard protects the preview endpoint, which evaluates a not-yet-saved pattern.

### Quarantine collapses to almost nothing in SQL

`effective_from` and `grace_days` come from a single policy row, so they are Python scalars, not
columns:

```python
cutoff = expiry_boundary(now) - timedelta(days=policy.grace_days)
if policy.effective_from > cutoff:
    return None                    # the whole estate is still in grace; no clause at all
return and_(noncompliance_clause(policy), Environment.created_at <= cutoff)
```

Day-granular via A4's `expiry_boundary` (the start of the current UTC day), for the reason A4
recorded at length: at instant precision an environment created at 15:00 loses most of its last
grace day, and — worse — the filter then hides the rows closest to their deadline. **A deadline is
a day.**

## API

### Policy

- `GET /tenant/environment-naming-policy` — readable by **any tenant member**. The reason an
  environment is flagged has to be legible to the person who has to fix it; this is B3a's rule
  (reads open, writes Admin), deliberately unlike `/tenant/users`.
- `PUT /tenant/environment-naming-policy` — Admin. An upsert on a one-row-per-tenant table, like
  `RaidConfig`. No `DELETE`.
- `POST /tenant/environment-naming-policy/preview` — Admin. Optional `pattern` /
  `required_attributes` overrides. With no overrides it describes the policy in force; with them
  it answers the question an admin actually has *before* saving — **who does this hit?** — returning
  counts by gap kind plus a sample of non-conforming names. Unbounded by design, like the other
  rollup endpoints, and listed as such in docs/pagination.md.

Both write schemas carry `extra="forbid"` and bounded types. `POST /projects` silently discarded
`priority_rank` for the want of exactly that, and `POST /tenant/lifecycle-templates` still drops
`required_fields` today.

### `GET /environments`

Two new filters, both applied **in SQL, before the window**, so `X-Total-Count` describes the
filtered set:

- `?compliance_gap=true|false`
- `?quarantined=true|false`

Both spell "no selection" as an **omitted key**. An empty `?compliance_gap=` is a **422**, not an
ignored param, so nothing may send one; the UI's value for no-selection is **`any`, never `all`**,
because `buildParams`' own sentinel is `'all'` and a vocabulary containing it builds byte-identical
params for two different states — the grid then never refetches. `false` is the **exact
complement**: compliant environments **plus** every environment no policy covers, so true and false
partition the estate rather than leaving a policy-less tenant's rows invisible to both.

### Response fields on `EnvironmentResponse`

| field | notes |
| --- | --- |
| `name_compliant: bool \| null` | The stored column. **Sortable** — it is one column. |
| `quarantined: bool` | Derived from that column plus `created_at` and the policy. **Permanently `sortable: false`** — the fourteenth member of docs/pagination.md's unsortable set. |
| `compliance_gaps: list[str]` | Rendered messages, resolved **once per response** from columns the page already selected — never once per row. A3's `gap_warnings_for_bookings` is the shape, and its docstring's warning (~150 queries for a 50-row page through the per-row helper) is the thing being avoided. |

## UI

**No new page.** Advisory-only means the worklist is the existing Environments grid with a filter
chip beside B1's "Governance gap". A separate `/quarantine` route would be a second place to look
at the same rows.

- **`EnvironmentNamingPolicyPanel`**, beside `EnvironmentTiersPanel`: enable toggle, pattern,
  example, `grace_days`, and a multi-select for required attributes whose options are the fixed
  three plus the tenant's `environment` custom-field definitions. Mutating thunks use
  `rejectWithValue(formatApiError(err))` and the panel reads `result.payload` — RTK's default
  serializer drops `response.data.detail`, so without it the user sees "Request failed with status
  code 422" instead of the reason.
- **The scratch "test a name" box is evaluated server-side**, through the preview endpoint. Running
  the pattern in the browser would evaluate it with **JavaScript's** regex engine — the
  two-engines-disagreeing failure this design rejected, smuggled back in through the front door.
  The admin would be testing against an engine that never judges anything.
- **Environments grid**: a Compliance chip column plus the two filter chips. Custom-field columns
  stay `cf_<key>`-namespaced — a static `compliance` column colliding with a tenant custom field
  of the same key would silently hide the real column through a persisted visibility entry, and no
  fixture defines a colliding custom field, so no test can catch it.
- **Environment detail**: a banner naming each gap, and either the date grace ends or the date
  quarantine began, beside the existing governance panel.
- **The name field's helper text carries the pattern and its example** on create and rename, so the
  422 is the second time the user sees the rule rather than the first.

**Expect B3a's first-deploy optics.** The moment a tenant enables a policy, most of the estate
reads non-compliant. The grace period is the answer — nothing quarantines for `grace_days` — and
the preview endpoint exists so the admin sees the number *before* enabling. This goes in the admin
guide, as B3a's did.

## Testing

The house rule from A4: **a rule the code explains at length reads as a rule that is guarded**, and
six of seven mutation survivors on A4 were exactly those sentences. Each rule below gets a named
test that fails when the rule is removed.

**The guard on the whole design**

- `test_quarantine_changes_no_booking_behaviour`.
- `describe('B2 advises; it never blocks')` on the frontend — asserted against a fixture where the
  control *could* have rendered. A3's reviewer gated `TransitionButtons` on the gap and watched all
  50 page tests pass, because the fixture returned no allowed transitions and nothing on the page
  could detect the gating.

**The stored verdict's integrity** — option A's one real liability, so it gets the sharpest test:
drive an environment through **every** write path (create, rename, unchanged-name full-form save,
request fulfilment, policy change) and assert the stored `name_compliant` equals a freshly computed
verdict each time.

**Named tests for the rules that would otherwise rot**

- a full-form save re-sending an unchanged bad name is accepted; changing it to a different bad
  name is 422
- fulfilling an approved request never 422s on the naming rule
- `name_compliant IS NULL` counts as compliant, and `true`/`false` partition the estate with no row
  invisible to both
- nothing is quarantined while the policy is younger than `grace_days`
- A4's day-granularity case: created 15:00 on day 0, `grace_days=1`, **not** quarantined at 09:00
  on day 1
- a pattern whose own example fails it is refused
- `(a+)+$` is refused by the probe
- `effective_from` is bumped by a pattern change and **not** by a `grace_days` change

**Both engines, and one part is SQLite-blind.** The `cf:<key>` predicate compiles to `->>` on
PostgreSQL and `json_extract` on SQLite, and it is the only part of this design with **no
precedent in the codebase**. It gets a test on both legs *first*, before anything is built on it.
Note also that `tests/test_migration_schema_drift.py` compares only column **name sets** — it will
pass a hand-written migration whose `name_compliant` has the wrong type or nullability.

**A browser pass is load-bearing, not a formality.** jsdom could not render A3's DataGrid gap
column at all (a scratch render gave 1 row, 3 cells, 0 icons), and six defects across the
pagination programme were found only by opening the page with a fully green suite. The compliance
chip column and both filter chips get opened in a browser.

## Migration

Revision `envnamingpolicy`, additive: one table, one nullable column, **and no backfill at all**.
No tenant has a policy at migration time, so `name_compliant` is correctly null for every existing
row — the column's null-means-no-pattern-applies semantics are what make the backfill unnecessary
rather than merely deferred. Rows get their verdict from `recompute_tenant` the moment a policy is
first saved. Written by hand with `op.create_table` / `op.add_column`, never `--autogenerate`.

## Risks carried into implementation

1. **ReDoS is mitigated, not eliminated** — see above. Accepted, with a recorded upgrade path.
2. **The `cf:` vocabulary may not survive the portability spike.** If `custom_fields[key]` does not
   compile cleanly on both engines, the fallback is to ship the vocabulary as real columns only and
   defer custom-field keys — which would leave *cost centre*, the one attribute of §2.12's four
   that B1 did not already cover, uncoverable. Worth knowing on day one rather than in week two,
   which is why it is the first task.
3. **A stored derived value is a standing liability.** Mitigated by the enumerated invalidation
   surface and the every-write-path test, but any future code that writes `Environment.name`
   without going through `environment_service` will silently produce a lying verdict. The two
   construction sites are named above; a third would need the same treatment.

## Deviation on record

§2.12 asks to "quarantine/**terminate** untagged resources after a grace period". B2 quarantines
as a **label only** and terminates nothing. The register has neither the credentials to destroy a
resource nor any way to know the row still corresponds to something running. Automated teardown
belongs with **B5** (decommissioning workflow), if it belongs anywhere.
