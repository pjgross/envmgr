# User groups + environment operations group — design

**Status**: designed, not implemented. Phase 7, sub-project **B3a**.

## Where this sits in Phase 7

B3 in `docs/phases/phase-7.md` reads "Environment Request Form + auto-generated Welcome Pack".
Brainstorming it surfaced a requirement the roadmap line does not carry: the request is consumed
by **operations teams, one per platform**, who need to see the requests they are responsible for
actioning. That means environments must know which team operates them, and teams must be a thing
the system can hold. Neither exists today.

So B3 is split:

- **B3a — this spec.** A generic `UserGroup` with membership, an `operations_group_id` on
  `Environment`, and the admin UI for both. No request form, no routing, no Welcome Pack.
- **B3b — its own spec.** The Environment Request Form, routed to the operating team, its
  approval flow, and the Welcome Pack generated at handoff.

B3a ships no user-visible workflow. It is admin screens and a field; the value arrives with B3b.
That is a deliberate trade for a reviewable increment, and it should not come as a surprise when
the first PR merges and nothing new appears outside Administration.

### Why a generic group rather than an "operations team"

Phase 7 **A1** is `Project` entity **+ members** — also a container of users. Building a
purpose-named `OperationsTeam` here would leave this codebase with two unrelated membership
models and a real question for users: which one do I add this person to? `UserGroup` is
deliberately generic so A1 can point `Project` at the same primitive rather than inventing its
own. Making A1 actually do that is A1's job, not a change in this spec.

## What the code actually looks like today

Checked against the code, not the roadmap — `phase-6.md` was two-thirds wrong and cost a
correction pass, so this is the first step of any phase work here.

- **There is no group or team concept anywhere.** `release_membership` is the closest name and is
  unrelated: it records releases admitted into enterprise releases, not users in containers.
- **`BookingRequest` is not this.** It requests *use* of existing environments in a window. B3's
  request form is a different concept and must not be folded into it.
- **There is no per-environment access control.** Roles (`Admin`, `Release Manager`,
  `Test Manager`, `Developer`, `Viewer`) are tenant-wide, and nothing scopes a user to an
  environment. An "access to environment X" request therefore cannot *grant* anything technically
  — in B3b it will be a workflow record and a Welcome Pack handoff, which is a paperwork and
  audit trail, not enforcement. This is worth stating plainly so nobody later assumes the request
  flow is a security control.
- `Environment` carries `tier_id`, `owner_user_id` and `expires_at` from B1, with
  `?governance_gap=true` reporting a missing owner.
- Lifecycle templates exist for `booking`, `change_request` and `release`. **Not** `environment`.
  B3a does not add one.

## Scope

**In scope**

1. `user_group` and `user_group_member` tables, service, and CRUD API.
2. `environment.operations_group_id`, nullable, with read/write/filter support.
3. Admin UI: a User Groups screen with membership management; an Operations Group control on the
   environment create dialog and detail form; an Operations Group column and filter on the
   environment list.

**Out of scope — and inherited by B3b's spec as a fixed line**

- **Group membership grants no permissions.** Every authorization rule stays role-based. B3b
  introduces the first behaviour that reads membership (which requests an ops-team member sees).
  Keeping a second authorization axis out of the sub-project that introduces the data model is
  deliberate: this repo treats tenant isolation as a security-clearance requirement, and an authz
  change deserves its own scrutiny rather than riding along with a schema addition.
- No nested groups. No role within a group (no lead/member distinction).
- No generic polymorphic assignment table.
- The request form, its routing, approval and the Welcome Pack.
- A1 pointing `Project` at `UserGroup`.

## Data model

```
user_group                          user_group_member
  id            PK                    id            PK
  tenant_id     FK -> tenant.id       tenant_id     FK -> tenant.id
  name          VARCHAR(200) NOT NULL group_id      FK -> user_group.id
  description   TEXT      NULL        user_id       FK -> user.id
  deleted_at    TIMESTAMP NULL        created_at / updated_at (from Base)
  created_at / updated_at             UNIQUE(group_id, user_id)

environment
  operations_group_id  FK -> user_group.id  NULL  + index
```

### Decisions

**Soft delete on the group, hard delete on membership.** This repo's convention is that entities
soft-delete and junction rows hard-delete, and both halves matter here. Removing someone from a
team is routine and should not accumulate tombstones. A deleted group, by contrast, is still
referenced by `environment.operations_group_id` and by B3b's historical requests, so it must
survive as a row.

**Name is unique per tenant, enforced in the service rather than by a database constraint.** A
plain `UNIQUE(tenant_id, name)` collides with soft delete: delete "Platform Ops", recreate it,
and the constraint fires against the tombstone. The usual fix is a partial unique index
(`WHERE deleted_at IS NULL`), but this repo's own pitfall list records that dialect-gated DDL of
that kind is **inert on SQLite**, so the guard would exist only on the PostgreSQL leg while the
SQLite leg passed regardless. Service-level validation is honest about where the rule lives. The
uniqueness check is case-insensitive, matching how B1 folded tenant tier names.

**Soft-deleting a group does not clear the environments pointing at it.** The FK stays valid and
`EnvironmentRead` renders the name with a "(deleted)" marker — the same treatment B1 gave a
retired tier and a deactivated owner, and for the same reason: blanking the field makes a
populated control render empty while form state still holds the id, which MUI reports as an
out-of-range warning. `DELETE` returns 409 listing the environments still referencing the group,
so an admin sees the blast radius before confirming.

**`operations_group_id` is nullable everywhere** — not required on create, never blocking a
patch. Existing environments keep a null rather than a fabricated group, and
`?governance_gap=true` extends to report it. The constraint lands in B3b instead, which refuses
to *route* a request for an environment with no operating team, with a message naming the
environment. That puts the requirement where it actually matters rather than blocking unrelated
edits, and avoids the problem B1 hit where the spreadsheet import had to invent an owner for
every imported row.

**No role within a group.** Routing in B3b is "is this user in the group". A4's escalation with a
named owner and a response window may need one; that is the point to add it, with a use case in
hand.

## API

```
GET    /tenant/groups                      any member    bounded + sortable
POST   /tenant/groups                      Admin
GET    /tenant/groups/{id}                 any member    group only + member_count
PATCH  /tenant/groups/{id}                 Admin
DELETE /tenant/groups/{id}                 Admin         soft delete, 409 if referenced
GET    /tenant/groups/{id}/members         any member    bounded
POST   /tenant/groups/{id}/members         Admin         {user_id}
DELETE /tenant/groups/{id}/members/{uid}   Admin
```

**`GET /tenant/groups/{id}` does not embed the member list.** It returns the group plus a
`member_count`, and members come from the bounded sub-resource. Embedding them would put an
unbounded nested collection inside a detail response — the pattern this codebase has now found
and fixed repeatedly, most recently in `GET /releases/{id}/membership`, whose `history` list had
to be bounded separately after the fact. A group with 400 members is unusual but not absurd, and
the detail page pages through them anyway.

**Read for any tenant member, write for Admin** — the same split `/tenant/users/lite` uses. B3b
needs every user to be able to see which team operates an environment; that is not admin-only
information.

**There is deliberately no `/tenant/groups/lite`.** The pagination programme established that a
picker fed by a capped list loses entities invisibly — a `.find()` miss renders as `—`, which is
information lost rather than hidden. A tenant has a handful of operating teams, so
`GET /tenant/groups` at the shared 500/1000 cap *is* the picker source with nothing to truncate.
A second lite variant would recreate the problem for no benefit.

Both list endpoints take `pagination()` with a primary-key tiebreaker and emit `X-Total-Count`.
The groups list takes `sorting()` whitelisting `name` and `created_at`, with the matching entry
in `frontend/src/constants/sortWhitelists.json` — `test_sort_whitelist_contract.py` enforces
agreement between the two.

**Membership is add-one / remove-one, not replace-the-set.** A `PUT` of the whole member list
lets two admins editing the same team silently clobber each other, and gives the endpoint no way
to distinguish an intentional removal from a stale payload.

### Environment changes

- `EnvironmentCreate` / `EnvironmentUpdate` gain `operations_group_id`, typed `int | null` rather
  than optional. B1 established why: the backend keys on `model_fields_set`, so an omitted key
  means "leave alone" and only an explicit null can clear the field.
- **`EnvironmentRead` gains both `operations_group_id` and `operations_group_name`** — the name
  travels with the row, exactly as `ReleaseSystemRead` carries `system_name` and as RAID rows
  gained `owner_username`. Resolving it client-side against the groups collection is the failure
  mode the pagination sweep documented.
- `?governance_gap=true` extends to cover a missing operations group.
- A new `?operations_group_id=` filter lists one team's estate.

### Errors

| Case | Response |
|---|---|
| Group id belonging to another tenant | **404**, not 403 — a 403 confirms the row exists |
| Duplicate name within the tenant | 409, naming the conflicting group |
| Delete with environments referencing it | 409, naming **up to 10** environments plus a count of the rest — the message is for a human, and a group operating 200 environments must not emit a 200-name error string |
| Adding a user from another tenant | 404 |
| Unknown `sort_by` | 422 — never a silent fallback |

## Frontend

A **User Groups** entry in `AdminLayout`'s nav at `/tenant/groups`, next to User Management.

- **Groups list** — `useServerGrid` against `/tenant/groups`; columns Name / Description /
  Members / Environments. The two counts are computed from batch queries keyed on the page's row
  ids, so they get `sortable: false`: they are not backed by a single column and cannot be
  whitelisted. This matches the documented trade the twelve existing computed columns make.
- **Group detail** — the member list, read from the bounded `/tenant/groups/{id}/members` rather
  than from an embedded array, plus an add-member picker fed by `/tenant/users/lite` (bounded
  1000/5000) and a per-row remove.
- **Environment form** — an Operations Group select on both the `EnvironmentList` create dialog
  and the `EnvironmentDetail` governance form, following the tier and owner controls exactly,
  **including keeping a soft-deleted group selectable with a "(deleted)" label** when it is the
  environment's current value.
- **Environment list** — an Operations Group column and filter. Custom-field columns there are
  already namespaced `cf_`, so a tenant field keyed `operations_group` cannot collide.

Two things built in from the first commit rather than retrofitted, both because the codebase has
already paid for them:

- **`userGroupSlice` uses `rejectWithValue(formatApiError(err))` from the start.** The delete path
  is the one that matters: a 409 saying which environments still reference the group is the entire
  value of that response, and Redux Toolkit's default `miniSerializeError` discards
  `response.data.detail` and leaves the user reading "Request failed with status code 409".
- **The delete confirmation names the blocking environments**, not merely that something blocks.

## Migration

One manual revision (`alembic revision -m "usergroups"`; DDL written by hand, since `init_db`
calls `create_all` and autogenerate therefore sees nothing): two `create_table` calls, plus
`add_column` and an index for `environment.operations_group_id`.

**No backfill and no data migration** — everything added is nullable or empty, so the change is
additive and reversible.

When exercising the downgrade, use a scratch database, not the dev one. `alembic downgrade -1`
steps back from the *current* head rather than from the new revision; doing that on dev
previously dropped `tenant_secret` and destroyed a stored GitHub token.

## Testing

Run on both engines — CI gates on SQLite and PostgreSQL, and several classes of bug here are
invisible on one of them.

- **Tenant isolation, including the FK-write direction.** Not only "tenant B cannot read tenant
  A's group", but "tenant B cannot set `operations_group_id` to tenant A's group, and cannot add
  tenant A's user to its own group". That IDOR-class write gap is what the 2026-07-16 audit found
  four instances of, and this change adds three new FK write paths.
- **Impersonation.** Under master-admin impersonation `current_user.id` and `active_tenant_id`
  belong to different tenants — a mismatch that has already broken an owner validation and killed
  an entire spreadsheet upload. Member-add validates the user against `active_tenant_id`, with a
  test covering it.
- **Pagination conformance rows** for both new list endpoints in `test_pagination.py`'s tables,
  plus the sort-whitelist contract entry.
- Delete-with-references returns 409 naming the environments; duplicate name returns 409;
  a soft-deleted group still renders its name on the environments referencing it.
- **Frontend panel tests reject with an `AxiosError` *shape*** — generic text on `.message`, the
  real reason only at `response.data.detail`. A plain `Error` carrying the final text passes
  against broken code, because that shape already has the right string where the buggy read looks.
- Every FK comes from `tests/factories.py`. Never a fabricated `group_id=1`.

## Open questions

None. Every fork raised during brainstorming was decided: generic `UserGroup` over a purpose-built
operations team; plain FK over a polymorphic assignment table; no authorization effect; nullable
and reportable rather than required; two sub-projects rather than one.
