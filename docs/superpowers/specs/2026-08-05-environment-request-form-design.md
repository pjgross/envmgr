# Environment Request Form + Welcome Pack — design

**Status**: designed, not implemented. Phase 7, sub-project **B3b**.

## Where this sits in Phase 7

B3 in `docs/phases/phase-7.md` reads "Environment Request Form + auto-generated Welcome Pack".
Brainstorming it split B3 in two, because the request is consumed by **operations teams, one per
platform**, and neither teams nor the environment→team association existed:

- **B3a — shipped 2026-08-05** (`b72684d7`). A generic `UserGroup` with membership, an
  `operations_group_id` on `Environment`, and the admin and environment UI for both.
  [Spec](2026-08-04-user-groups-design.md).
- **B3b — this spec.** The request form, its routing to the operating team, its approval
  lifecycle, and the Welcome Pack.

B3a's spec fixed a line that this spec inherits and now spends: *"B3b introduces the first
behaviour that reads membership."* That behaviour is defined here, and it is exactly one thing —
who may transition a request. Nothing else in the application starts consulting group membership.

## What the code actually looks like today

Checked against the code, not the roadmap.

- **None of the Welcome Pack's content exists.** §2.12 specifies "URLs, credentials, VPN,
  support/SLA, data profile, known limitations, expiry, decommission steps". `Environment` holds
  name, description, `tier_id`, `owner_user_id`, `expires_at`, status, `operations_group_id`,
  `custom_fields`. There is no table anywhere for access URLs, VPN details, support contacts,
  SLAs, known limitations or decommission steps. **Data profile is Phase 10** (Test Data
  Management) and is not built.
- **There is no email or notification infrastructure.** No SMTP, no provider client, nothing.
  The pack is an in-app artefact the requester opens.
- **There is still no per-environment access control.** Roles (`Admin`, `Release Manager`,
  `Test Manager`, `Developer`, `Viewer`) are tenant-wide. This was true before B3a and remains
  true: an access request cannot *grant* anything technically.
- `ChangeRequest` is the closest existing workflow entity — a `status` VARCHAR driven by a
  `lifecycle_template`, with role-gated transitions and per-state field permissions.
  `ENTITY_FIELD_SPECS` registers three entity types: `booking`, `change_request`, `release`.
- `create_tenant` already calls six `seed_*_for_tenant` functions.

## Scope

**In scope**

1. Six handover fields on `Environment`, authored by the team that operates it.
2. An `environment_request` entity with two modes, on the existing lifecycle-template machinery.
3. Routing and transition authorization keyed on the target environment's operations group.
4. Fulfilment of a new-environment request creating the `Environment`.
5. A Welcome Pack rendered live from the environment.
6. The UI for all of it.

**Out of scope — and stated so it is not rediscovered**

- **Credentials.** §2.12 lists them; they are excluded deliberately. This application has one
  secret store (`tenant_secret` + `SECRETS_ENCRYPTION_KEY`), built for a single OAuth token, and
  losing that key already makes every stored credential unrecoverable. Generating documents that
  contain environment passwords is a materially different risk, and it is unnecessary:
  `connection_notes` can say *where* credentials come from — a vault path, a team to ask —
  without this application becoming the place passwords live.
- **Data profile** — Phase 10.
- **Delivery.** No email or notification infrastructure exists. The pack is opened in-app.
- **Per-environment access control.** An access request records and authorises a handover; it
  grants nothing technically. It is a paperwork and audit trail, which is useful and is not
  security. Anyone reading this later should not assume the request flow is a control.
- **Scoping handover-field edits to the operating team.** That would be a *second*
  membership-reading behaviour; this sub-project introduces exactly one. Natural follow-on for B5.
  **Know the consequence before accepting it:** `PATCH /environments/{id}` is gated on
  `require_tenant_admin()`, so in B3b the six handover fields can only be written by a tenant
  Admin — not by the operating team, which is precisely the group that knows the access URL, the
  VPN route and the support contact. In a tenant with several platforms this makes the Admin a
  bottleneck for knowledge they do not have, and the likely failure mode is packs that stay empty.
  It is accepted here to keep this sub-project to one authorization change, and it is the first
  thing to revisit: a narrow `PATCH /environments/{id}/handover` gated on
  ops-group-or-Admin would close it without touching any other environment field.

## Data model

```
environment_request                        environment  (+6 handover columns)
  id, tenant_id                              access_url          VARCHAR(500) NULL
  kind          'access'|'new_environment'   connection_notes    TEXT NULL
  status        VARCHAR (lifecycle-driven)   support_contact     VARCHAR(255) NULL
  lifecycle_id  FK lifecycle_template.id     sla_notes           TEXT NULL
  requested_by  FK user.id                   known_limitations   TEXT NULL
  justification TEXT                         decommission_notes  TEXT NULL
  needed_by     TIMESTAMP NULL
  environment_id         FK environment.id  NULL   -- required when kind='access'
  proposed_name          VARCHAR(200) NULL         -- required when kind='new_environment'
  tier_id                FK environment_tier.id NULL
  expires_at             TIMESTAMP NULL
  operations_group_id    FK user_group.id NULL     -- set by the approving Admin
  created_environment_id FK environment.id NULL    -- set on fulfil
  custom_fields JSON
  deleted_at    TIMESTAMP NULL
```

### Decisions

**Handover fields live on `Environment`, not on the request.** A requester cannot know the access
URL of an environment that does not exist yet; the team that builds it fills these in afterwards.
A newly created environment therefore starts with them empty, which is correct rather than a gap —
an inactive environment awaiting build has nothing to hand over. They are also not on a side
table: they are one-to-one with the environment and always read with it.

**One table with a `kind` discriminator, not two tables.** The two modes share the requester,
justification, lifecycle, routing and pack; they differ in four fields. `ChangeRequest` already
models optional targets this way. Mode-dependent requirements are enforced **in the service**,
where a violation produces a message naming the missing field, rather than by nullability the
database cannot explain.

**`created_environment_id` is the audit link.** It answers "where did this environment come
from?" — the question the register exists to answer, and the one a manual-creation flow loses.

**Soft delete** on the request (entities soft-delete here); no junction tables are added.

## Lifecycle

`environment_request` becomes a fourth entity type in `ENTITY_FIELD_SPECS`:

```python
"environment_request": {
    "valid":     {"kind", "justification", "needed_by", "environment_id",
                  "proposed_name", "tier_id", "expires_at", "operations_group_id"},
    "mandatory": {"kind", "justification"},
}
```

The seeded default template is deliberately plain — `draft → submitted → approved → fulfilled`,
with `rejected` and `cancelled` as terminals. A tenant wanting a second review step edits it in
the existing admin UI, which is the entire reason for reusing this machinery instead of a fixed
status enum. Seeding follows B1's tier defaults exactly: a
`seed_environment_request_defaults_for_tenant` called from `create_tenant`, plus a migration
seeding existing tenants.

## Authorization

This is the one behaviour in the application that reads group membership. It lives in a single
service function, `environment_request_service.assert_may_transition`, called by the transition
endpoint and nothing else.

```
role  = the transition's allowed_roles, from the template, as today
group = actor ∈ target environment's operations_group
        (for kind='new_environment' there is no environment, so this clause cannot apply)

may_transition = role AND (group OR actor.role == 'Admin')
```

- **Reads stay open to any tenant member.** Only transitions are gated. This matches what B3a
  shipped for groups themselves and keeps "which team operates this?" answerable by everyone,
  which was B3a's stated premise.
- **Admin bypasses the group check but not the role check.** A request can never become
  permanently unactionable because a team was emptied or misconfigured — but an Admin still
  cannot make a transition the template does not grant their role. The template stays meaningful.
- **New-environment requests route to Admins by construction**, since the group clause cannot
  apply. The approving Admin sets `operations_group_id`, and that becomes the created
  environment's operating team.

**B3a's promise, honoured at submission rather than at action.** B3a's spec said B3b would refuse
to route a request for an environment with no operating team. It does: `draft → submitted` fails
for an access request whose target environment has a null `operations_group_id`, with a message
naming the environment and telling the requester to ask an admin to assign one. Refusing at
submission beats letting it through — a request only an Admin can see is a request that sits
unactioned with nobody knowing why. Admin bypass covers the different case of a group that exists
but is empty.

## API

```
GET    /environment-requests                    any member   bounded + sortable
POST   /environment-requests                    any member   creates a draft
GET    /environment-requests/{id}               any member
PATCH  /environment-requests/{id}               requester or Admin, draft only
POST   /environment-requests/{id}/transition    role + group gated
GET    /environment-requests/{id}/welcome-pack  any member; 409 unless fulfilled
```

**`?actionable=true` is the filter that carries the feature** — "requests my team must action".
**In SQL, never Python**: this endpoint is bounded, and a Python-side filter would window the page
before filtering and return quietly wrong results — the failure `docs/pagination.md` documents at
length. Alongside it: `?mine=true`, `?status=`, `?kind=`, `?environment_id=`.

Its definition is exact, because "actionable" is ambiguous for an Admin, who can action almost
anything:

```
actionable(request, actor) =
      request.status is non-terminal
  AND NOT request.requested_by == actor        -- you do not action your own
  AND (
        request.kind = 'access'
        AND EXISTS (user_group_member
                    WHERE group_id = target_environment.operations_group_id
                      AND user_id  = actor.id)
        --- or ---
        request.kind = 'new_environment' AND actor.role = 'Admin'
      )
```

Note what this deliberately does **not** include: an Admin's group bypass. An Admin sees
new-environment requests as actionable, and access requests only for teams they are actually in.
Folding the bypass in would make the filter return the whole tenant for every Admin, which is the
one user for whom a "my queue" list would then be useless. The bypass exists so a transition is
never *impossible*; it is not a claim about whose queue a request belongs in. An Admin unblocking
a stuck request finds it through the unfiltered list.

Excluding your own requests keeps the queue an inbox rather than a mirror — an ops-team member who
raises a request against their own platform should not see it as work assigned to themselves.
They can still action it from the unfiltered list, since the authorization rule is separate from
this filter.

Standard bounded-endpoint contract: `pagination()`, a primary-key tiebreaker, `X-Total-Count`.
A `sorting()` whitelist **only if the grid sorts server-side** — B3a shipped a `sortWhitelists.json`
entry for a client-side grid, where it was dead weight and its "422s on first click" comment was
false. Decide this against the built grid, not in advance.

### Errors

| Case | Response |
|---|---|
| Cross-tenant environment, tier, group or request id | **404**, never 403 |
| `kind='access'` without `environment_id` | 422 naming the field |
| `kind='new_environment'` without name, tier or expiry | 422 naming the fields |
| Submitting an access request whose environment has no operations group | 409 naming the environment |
| A transition the actor's role does not allow | 403 |
| A transition for a group the actor is not in | 403 |
| Welcome pack requested before fulfilment | 409 |

## The Welcome Pack

A read model, not a stored document. Rendered live so that a changed VPN endpoint or support
contact updates every pack at once; a frozen copy confidently stating stale connection details is
worse than no document.

```
GET /environment-requests/{id}/welcome-pack
  environment:  name, tier, status, owner, expires_at
  access:       access_url, connection_notes, support_contact
  support:      sla_notes, operations group + its members
  caveats:      known_limitations
  offboarding:  decommission_notes
  context:      requester, justification, fulfilled_at
```

It resolves its environment as `environment_id or created_environment_id`, so both modes produce a
pack with no special case at the call site.

**Two behaviours it must get right**, both lessons already paid for in this codebase:

- A field the operating team has not filled in renders as **"Not provided"**, never as a blank or
  an omitted section. An empty "How to connect" heading reads as "there is nothing to do" — the
  same class of defect as the drift work's absent-versus-checked-and-empty confusion.
- The operations-group member list travels **with the response**, resolved server-side. Resolving
  it in the browser against `/tenant/users/lite` — which is capped — is the `.find()`-into-a-capped
  -collection failure the pagination sweep documented, where a miss renders as `—` and loses
  information no banner can recover.

## Frontend

A new **Environment Requests** entry under Environment Management.

- **List** — `useServerGrid`, with filter chips *All* / *Mine* / *For my team* (the `actionable`
  filter). Columns: kind, target environment or proposed name, requester, status, needed by.
- **Request form** — a mode toggle driving which fields appear. Access mode asks for the
  environment and a justification; new-environment mode asks for a proposed name, tier and expiry.
  Mode-dependent validation mirrors the service's.
- **Detail** — the request, the transitions **this actor may actually make** (not every transition
  rendered disabled), and the Welcome Pack inline once fulfilled.
- **Handover section** on Environment detail for the six new fields, following the Governance
  section's existing edit pattern.

Redux thunks reject with `rejectWithValue(formatApiError(err, ...))` and components read
`result.payload` — the 409s and 403s here carry the entire explanation, and
`miniSerializeError` discards `response.data.detail`.

## Fulfilment

Fulfilling a new-environment request is a **single transaction** that creates the `Environment`
from the request's fields with `status = INACTIVE` and `operations_group_id` set to the group the
approving Admin chose, sets `created_environment_id`, and transitions the request.

`INACTIVE`, not `ACTIVE`: the register must not claim an environment is available before anyone
has built it. That drift between the register and reality is what this product exists to prevent.
An admin flips it active when the infrastructure exists.

Fulfilling an **access** request transitions the request and nothing else. There is nothing to
create and nothing to grant.

## Migration

One `create_table`, six `add_column`s on `environment`, and a seed of the default lifecycle
template for existing tenants. Additive and reversible; every new column is nullable, so there is
no backfill.

Write the DDL by hand — `init_db()` calls `create_all`, so `--autogenerate` produces an empty
migration. **Check the migration against its models column by column**: types, timezone-awareness,
defaults, and index names. `tests/test_migration_schema_drift.py` compares only column *name
sets*, so a passing run is not evidence they agree — four real drifts passed it during B3a,
including naive-versus-timezone-aware timestamps that would have reached production.

## Testing

Both engines; CI gates on SQLite and PostgreSQL.

- **The authorization matrix is the most important surface in B3b, and must be tested in both
  directions.** B3a shipped an authz split with no backend test at all: flipping its reads to
  admin-only left 83 tests green, and opening its writes left 16 green. Here the matrix is
  role × group × kind × Admin-bypass. Each cell needs a test that fails when the rule is inverted,
  not merely one that passes today.
- **`?actionable=true` needs a differential test** — the SQL result compared against an
  independently computed expected set, not "returns some rows". A subtly wrong filter returns a
  plausible list.
- **Fulfilment is a multi-write transaction.** Assert all three writes land together, and that a
  failure rolls back all of them rather than leaving an orphan environment.
- **Tenant isolation on every new FK write path** — `environment_id`, `tier_id`,
  `operations_group_id`, `created_environment_id` — on both create and update. A 2026-07-16 audit
  found four IDOR-class gaps of exactly this kind, and B3a's review found a fifth that existed on
  the update path only.
- **Impersonation.** Under master-admin impersonation `current_user.id` and `active_tenant_id`
  belong to different tenants. The group-membership check must resolve against the active tenant.
- Bounded-endpoint conformance rows for the list endpoint.
- Frontend tests reject with an **AxiosError shape** — a plain `Error` carrying the final text
  passes against broken code.

## Sizing

Larger than B3a: roughly nine or ten implementation tasks against B3a's seven. It remains one
coherent sub-project and one spec, but the plan is worth executing in two passes — backend, then
frontend — rather than straight through.

## Open questions

None. Every fork raised during brainstorming was decided: structured handover fields over free
text or custom fields; lifecycle templates over a fixed enum; role AND group with an Admin bypass;
new-environment requests routed to Admins; fulfilment creating an inactive environment; and a
live-rendered pack over a stored snapshot.
