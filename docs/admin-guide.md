# EnvManager Admin Guide

## About this guide

This guide is for **Master Admins** standing up new tenants and **Tenant Admins** configuring and operating EnvManager day-to-day. It covers tenant provisioning, user and role management, modelling your platform (systems, subsystems, environments, infrastructure), configuring change kinds and gates, release templates, API keys and webhooks, tenant settings, and import/export. End-user workflows — booking environments, raising change requests, driving releases, reading builds and deployments — live in [`user-guide.md`](user-guide.md). The guide matches the post-Phase-4 product state.

## Table of contents

1. [Introduction](#1-introduction)
2. [Provisioning a new tenant](#2-provisioning-a-new-tenant-master-admin-only)
3. [Onboarding your tenant](#3-onboarding-your-tenant)
4. [Managing users and roles](#4-managing-users-and-roles)
5. [Modelling your platform: systems and subsystems](#5-modelling-your-platform-systems-and-subsystems)
6. [Modelling environments](#6-modelling-environments)
7. [Modelling infrastructure (hosts)](#7-modelling-infrastructure-hosts)
8. [Configuring change kinds and gates](#8-configuring-change-kinds-and-gates)
9. [Release templates](#9-release-templates)
10. [API keys and webhooks](#10-api-keys-and-webhooks)
11. [Tenant settings](#11-tenant-settings)
12. [Import/export](#12-importexport)
13. [Appendix: role permission matrix](#13-appendix-role-permission-matrix)

## 1. Introduction

EnvManager is a multi-tenant test-environment management platform. It maintains an inventory of systems, subsystems, and the environments they run in. It tracks who has booked which environment and when. It records change requests against environments and the gates they must pass. It coordinates releases that group changes for promotion. It ingests CI/CD build and deployment events so each environment shows what is currently deployed.

This guide is for two audiences. **Master Admins** provision new tenants — that one-time task is covered in chapter 2 only. **Tenant Admins** configure and operate a tenant day-to-day, and chapters 3 onward are written for them. End users — anyone booking environments, raising changes, or reading deployment status — should read [`user-guide.md`](user-guide.md) instead.

### The role model

Roles are tenant-scoped: each user has exactly one role within a tenant, and Admin is the senior tenant role. The Master Admin flag is separate from the role and grants cross-tenant access for provisioning and support.

| Role | Typical responsibility |
|------|------------------------|
| Master Admin | Cross-tenant operator who provisions tenants and seeds the first Tenant Admin. |
| Admin | Tenant owner — manages users, models the platform, and configures tenant settings. |
| Release Manager | Plans releases, drives release execution, and signs off gates. |
| Test Manager | Books environments for test campaigns and manages test-related changes. |
| Developer | Raises change requests and reads build and deployment status. |
| Viewer | Read-only access to inventory, bookings, changes, and deployments. |

See ch. 13 (Appendix: role permission matrix) for the full route × role × {read, write} matrix.

### Related documentation

- [`user-guide.md`](user-guide.md) — for end users in an already-provisioned tenant.
- [`../CLAUDE.md`](../CLAUDE.md) — for engineers working on EnvManager itself.
- [`prod architecture.md`](prod%20architecture.md) — for the production architecture.
- The Swagger API reference at `http://localhost:8000/docs` — authoritative for API contracts.

## 2. Provisioning a new tenant *(Master Admin only)*

### Master Admin scope

A Master Admin is a cross-tenant operator. The role exists to stand up new tenants, seed each tenant's first Admin, and step in for support — nothing more. It is not a senior version of *Admin*: a tenant Admin owns one tenant; a Master Admin operates *across* tenants. Master Admin status is a flag (`is_master_admin`) on the user, not a separate role; the user still carries an ordinary tenant role for their own home tenant. Master Admins live in the dedicated `system` tenant. The seeded password below is a development default and **must be rotated before any production use** — see ch. 4 for password reset.

### Logging in as the master admin

The seeded credentials, created by `backend/scripts/seed_master_admin.py`, are:

- **Tenant slug**: `system`
- **Username**: `masteradmin`
- **Password**: `masteradmin123`

Open the standard login page, enter the tenant slug `system` along with the username and password, and submit. After logging in, change the password immediately via the user menu — the seeded value is public knowledge and is unsuitable for any environment beyond local development.

### Walkthrough: creating a new tenant

1. Navigate to `/admin/tenants`. The route is gated to Master Admins; tenant Admins do not see it.
2. Click *New Tenant* in the page header.
3. Fill the *Create Tenant* dialog:
   - *Name* — the human-readable tenant name (e.g. `Acme Corp`).
   - *Slug* — the URL-friendly identifier the helper text describes as "URL-friendly identifier (e.g. acme-corp)". Use lowercase letters, digits, and hyphens; the slug becomes part of every login.
4. Click *Create*. The new tenant appears in the tenant table with *Status* `Active`.

### Walkthrough: creating the first Tenant Admin

1. From `/admin/tenants`, click the tenant's name in the *Name* column to open `/admin/tenants/:tenantId`.
2. In the *Users* section, click *Create User* and fill the dialog:
   - *Username*
   - *Email*
   - *Password*
   - *Role* — choose *Admin* (the selector also offers *Viewer*, *Developer*, *Test Manager*, *Release Manager*).
   - *Master Admin (cross-tenant access)* checkbox — leave **unchecked** for an ordinary tenant Admin.
3. The first user must have role *Admin*. Only *Admin* can manage other users in that tenant, configure entity types, gates, change kinds, and tenant settings — without one, the tenant cannot be onboarded.
4. Click *Create*. The new user appears in the user table with *Status* `Active`. They can now log in using the tenant slug plus their credentials, and chapter 3 onward applies to them.

### Walkthrough: signing in as a tenant

The *Sign In As* action lives on each row of the `/admin/tenants` table. Clicking it issues an impersonation token: your session adopts the target tenant's `active_tenant_id`, so every page renders exactly as that tenant's Admin would see it. Impersonation tokens last **60 minutes** and have no refresh — they are the most privileged credential in the system, so they expire on their own rather than being renewed. A long support session will need re-issuing. Use it for support, smoke-testing a freshly provisioned tenant, or troubleshooting a reported issue. While impersonating, a sticky warning banner reads "Viewing as *<tenant name>*. Exit to return to your account." Click *Exit* in that banner to drop the impersonation token and return to your master-admin context.

### Walkthrough: disabling a tenant

The *Disable* action also lives on each row of the `/admin/tenants` table, beside *Sign In As*, and only appears while the tenant is *Active*. Clicking it asks for confirmation ("Disable this tenant? All users will lose access.") and then sets the tenant inactive: every user in that tenant is locked out at login, but no data is deleted. To re-enable a disabled tenant, use the `PATCH /api/v1/admin/tenants/{tenant_id}` endpoint to set `is_active=true`; a UI re-enable control is not yet available. You cannot disable your own tenant.

### Provisioning flow at a glance

```
masteradmin login (system tenant)
        │
        ▼
  /admin/tenants ── New Tenant ──▶ tenant created
        │
        ▼
/admin/tenants/:id ── New User (role=Admin) ──▶ first Tenant Admin
        │
        ▼
   Sign in as tenant ──▶ tenant Admin starts ch. 3 onward
```

From here, the tenant Admin takes over — see [chapter 3](#3-onboarding-your-tenant).

## 3. Onboarding your tenant

### First login as Admin

Once your Master Admin has seeded you as the first *Admin*, open the login page and enter three things: your **tenant slug** (e.g. `acme-corp`), your **username**, and the **password** the Master Admin set. Submit. The app drops you on `/dashboard` — every authenticated session lands there. Sessions renew silently in the background for up to 14 days; signing out ends the session on the server, not just in your browser. Five wrong passwords in 15 minutes locks that username out for the rest of the window. Change your password immediately via the user menu (top-right avatar); the seeded password was chosen by someone who is not you.

### The mental model

Before you click anywhere, it helps to know how the domain hangs together. *Systems* are the products you ship; each contains one or more *Subsystems* (deployable units — services, apps, jobs). *Environments* are logical instances of a system (`dev`, `staging`, `prod-eu`) that you reserve, change, and release into. *Bookings* reserve an environment for a window of time, *Change Requests* record a planned change against one, and *Releases* group changes for promotion. *Builds* are produced per Subsystem by your CI; when CI deploys a build into an environment, EnvManager records that as a *Deployment*.

```
┌─ Systems ──── Subsystems ──── Builds ───┐
│                  │                       │
│                  └─ run as ─┐            │
│                              ▼           │
└─ depend on ─▶ Environments ──┴─ Deployments
                   │
                   ├─ reserved by ──▶ Bookings
                   ├─ changed by ───▶ Change Requests
                   └─ delivered to ─▶ Releases
```

### Dashboard tour

The dashboard is a four-card summary above a welcome panel. The cards are static counters today — they are not clickable shortcuts; use the left navigation to drill in.

- *Environments* — *Total environments* visible to your tenant. Use ch. 6 to populate this.
- *Bookings* — *Active bookings* across the tenant. Filled in once your team starts reserving environments (`user-guide.md` ch. 5).
- *Changes* — *Pending changes* awaiting approval or implementation (`user-guide.md` ch. 7).
- *Releases* — *Active releases* currently in flight (`user-guide.md` ch. 8).

> **Not yet available:** the *Bookings*, *Changes*, and *Releases* cards are wired to placeholder zeros in the current build; only *Environments* reflects live data. Treat the dashboard as a landing page, not a metrics view.

### The left navigation

The sidebar is the same for every authenticated user. *Catalogue*, *Bookings*, *Releases* and *Insights* are collapsible groups; Admins and master admins also see *Administration*, which switches the sidebar into its own admin-mode menu (see below).

| Group → entry | Route | What's there | Covered in |
|---|---|---|---|
| *Dashboard* | `/dashboard` | Landing page. | this chapter |
| *Catalogue → Systems* | `/systems` | System and subsystem catalogue. | ch. 5 |
| *Catalogue → Environments* | `/environments` | Environment inventory and detail. | ch. 6 |
| *Catalogue → Hosts* | `/infrastructure/hosts` | Infrastructure host inventory. | ch. 7 |
| *Catalogue → Compare environments* | `/environments/compare` | Side-by-side diff of two environments. | `user-guide.md` ch. 4 |
| *Catalogue → Import* | `/import` | Bulk Excel import. | ch. 12 |
| *Bookings → Calendar* | `/bookings/calendar` | Calendar view of reservations. | `user-guide.md` ch. 5 |
| *Bookings → List* | `/bookings/list` | Tabular view of reservations. | `user-guide.md` ch. 5 |
| *Bookings → Environment requests* | `/environment-requests` | Request access to an environment, or a new one; approve, reject and fulfil requests for teams you operate. | `user-guide.md` ch. 6; ch. 6 below (routing, handover, deploy note) |
| *Bookings → Change requests* | `/change-requests` | Change-request inbox. | `user-guide.md` ch. 7 |
| *Bookings → Projects* | `/projects` | Projects, their teams, priority rank and usage agreements. | ch. 4 |
| *Bookings → Environment groups* | `/environment-groups` | Named sets of environments bookable as one unit. | ch. 6 |
| *Bookings → Contentions* | `/contentions` | Contention escalations worklist. | ch. 4 |
| *Bookings → Decommissions* | `/decommissions` | Decommission worklist. | ch. 6 |
| *Releases → List* | `/releases` | Release inventory. | `user-guide.md` ch. 8 |
| *Releases → Calendar / Timeline / Scope windows / Analytics* | `/releases/…` | The other release views. | `user-guide.md` ch. 8 |
| *Releases → Builds* | `/builds` | CI build feed per subsystem. | `user-guide.md` ch. 9 |
| *Releases → Deployments* | `/deployments` | Deployment feed per environment. | `user-guide.md` ch. 9 |
| *Releases → Incidents* | `/incidents` | Incident register. | not detailed in this guide |
| *Releases → PIR actions* | `/pir-actions` | Post-implementation-review action worklist. | `user-guide.md` ch. 8 |
| *Insights → DORA metrics* | `/insights/dora` | DORA four-key dashboard. | not detailed in this guide |
| *Insights → Environment health* | `/insights/health` | Health dashboard. | not detailed in this guide |
| *Administration* (Admin / master admin) | `/admin` | Admin mode: a hub page and its own sidebar — Organisation, Environments, Bookings, Releases, Delivery, Integrations, Platform. Click *Back to EnvManager* to leave. | ch. 3–12 |

### Suggested setup order

Empty tenants are not useful. Work through these in order — each step unblocks the next, and most depend on the model you build in steps 2 and 3.

1. Create users for your team — see [ch. 4](#4-managing-users-and-roles).
2. Model your systems and subsystems — see [ch. 5](#5-modelling-your-platform-systems-and-subsystems).
3. Model your environments — see [ch. 6](#6-modelling-environments).
4. Optional: model hosts — see [ch. 7](#7-modelling-infrastructure-hosts).
5. Configure change kinds and release gates — see [ch. 8](#8-configuring-change-kinds-and-gates).
6. Optional: build release templates — see [ch. 9](#9-release-templates).
7. Issue API keys for CI — see [ch. 10](#10-api-keys-and-webhooks).

## 4. Managing users and roles

### Concept

Roles are tenant-scoped: every user has exactly one role within a tenant, and Admin is the senior tenant role. Only an Admin can manage other users — create them, change their role, deactivate or reactivate them. The Master Admin flag is separate from the role enum and is set only by an existing Master Admin (see [ch. 2](#2-provisioning-a-new-tenant-master-admin-only)). All five tenant roles — *Admin*, *Release Manager*, *Test Manager*, *Developer*, *Viewer* — share one enum, so switching a user's role is a one-click change.

### What each role can do

Use the table below to orient assignments. *Admin* is the only role that can manage users or tenant configuration; the other four are scoped to operational duties.

| Role | Can do | Cannot do |
|------|--------|-----------|
| Admin | Manage users; model systems, environments, hosts; configure change kinds, gates, settings, API keys. | Operate outside their tenant. |
| Release Manager | Plan releases, drive execution, sign off gates, manage release templates. | Manage users or tenant configuration. |
| Test Manager | Book environments for tests, raise and progress test-related changes. | Manage users, gates, or templates. |
| Developer | Raise change requests, read builds and deployments, view bookings. | Approve gates or edit tenant configuration. |
| Viewer | Read inventory, bookings, change requests, releases, deployments. | Make any write. |

See [ch. 13 (Appendix: role permission matrix)](#13-appendix-role-permission-matrix) for the full matrix.

### Walkthrough: creating a user

1. Navigate to `/admin/users`.
2. Click *New User* in the page header.
3. Fill the *Create User* dialog:
   - *Username*
   - *Email*
   - *Password* — initial value; the user can change it after first login.
   - *Role* — one of *Viewer* (default), *Developer*, *Test Manager*, *Release Manager*, *Admin*.
4. Click *Create*. The new user appears in the user table with *Status* `Active`.

The role drop-down does **not** include *Master Admin*. Tenant Admins cannot elevate a user to Master Admin from this page; only an existing Master Admin can grant the cross-tenant flag, via `/admin/tenants/:tenantId` (see [ch. 2](#2-provisioning-a-new-tenant-master-admin-only)).

### Walkthrough: editing a user

The user table has five columns: *Username*, *Email*, *Role*, *Status*, *Actions*. To rename a user or correct their email, click *Edit* on their row; the *Edit User* dialog opens with *Username* and *Email* fields only. Make changes and click *Save*. To change the user's role, do **not** use the *Edit User* dialog — change it directly in the per-row *Role* drop-down. The change saves immediately. The drop-down is disabled for inactive users.

### Walkthrough: deactivating and reactivating

To revoke access without losing history, click *Deactivate* on the user's row and confirm. The user is locked out at login but their bookings, change requests, comments, and audit trail are preserved. While inactive, their *Status* chip reads `Inactive` and the per-row *Role* drop-down is disabled. To restore access, click *Reactivate* — the action button toggles to *Reactivate* whenever a user is inactive.

### User Groups

A *User Group* organises users into a team that an environment can name as its operations group — see [ch. 6](#6-modelling-environments). Manage them at `/admin/user-groups`.

- **Reading the list, a group's detail, and its member list is open to any tenant member** — every user needs to be able to see which team operates a given environment, and the environment form needs the group list as a picker source. Creating, editing or deleting a group, and adding or removing a member, are Admin-only; a non-admin sees the same list and detail pages with the write controls (*New Group*, *Edit*, *Delete*, *Add*, *Remove*) hidden.
- The list shows *Name*, *Description*, *Members*, and *Environments* — the last two are live counts, not columns you set directly. Click a group's *Environments* count to jump to `/environments` filtered to that group.
- Click a row to open its detail page, where an Admin adds and removes members by username.
- A group that is still assigned as any environment's operations group cannot be deleted — the 409 response names the environments blocking it (and how many more, past the first ten). Reassign or clear those first.
- Deleting an unreferenced group soft-deletes it: its name keeps rendering (labelled "(deleted)") on any environment that still names it as the value already stored there, but it drops out of the picker for a *new* assignment.

**What membership buys, beyond being named on an environment.** Group membership on its own grants no permission — every authorization rule in the app is still role-based — with exactly two exceptions, both introduced by the Environment Requests feature (see [ch. 6 §Environment Requests, routing and the Welcome Pack](#environment-requests-routing-and-the-welcome-pack)):

1. **Approving, rejecting and fulfilling access requests** against an environment your group operates. A member of the operating team (or an Admin) can move a *submitted* access request to *approved* or *rejected*, and an *approved* one to *fulfilled*; nobody else can, and an Admin can always step in if a team is emptied or misconfigured.
2. **Authoring that environment's Handover content** — the six fields (*Access URL*, *How to connect*, *Support contact*, *SLA notes*, *Known limitations*, *Offboarding notes*) a fulfilled requester reads back in their Welcome Pack — via a dedicated *Handover* panel on the environment detail page, editable by the operating team as well as by Admins.

Nothing else changes: a group is still not a scope for booking, change requests, or any other write in the app.

### Projects

A *Project* is the multi-project-coordination unit introduced in Phase 7 sub-project A1: a named
initiative with an optional team, linked from bookings (as an optional *Project* field, distinct
from the existing free-text *Purpose*) and from releases (as an optional *Owning project*), and
recorded — **warned on, never enforced** — against the environments it uses. Manage them at
`/projects`. (Since Phase 7 sub-project A3 a booking outside those records is *flagged*;
nothing is refused. See *Usage agreements are a record, not a rule* below.)

- **Reading the list and a project's detail is open to any tenant member** — every booking and
  release form needs the picker, and everyone needs to be able to see which project a booking or
  release belongs to. Creating, editing or deleting a project, and adding or removing a usage
  agreement, are Admin-only; a non-admin sees the same list and detail pages with the write
  controls hidden.
- The list shows *Name*, *Code*, *Team*, *Environments* and *Status* — *Team* and *Environments*
  are read from the row the API returned, not resolved against a separately-fetched collection,
  and *Environments* is a live count of the distinct environments that project has a usage
  agreement for. Click a project's *Environments* count to jump to that project's own detail
  page, where the same agreements appear in full — `/environments` has no filter for this, so
  linking there would show the whole unfiltered estate rather than this project's environments.
- **What a team buys a project.** The *Team* field points at an existing `UserGroup` — the same
  primitive an environment names as its operations group (see above) — rather than a second,
  project-specific membership model. Exactly as with an operations group, **membership grants no
  permission**: every authorization rule in the app stays role-based. A project's team exists so
  the app can answer "who is on this project", nothing more; it does not scope who can book
  against the project or edit it. Only Admins can change a project's team, the same as every
  other write on this screen.
- **Deleting a project is always allowed**, unlike deleting a User Group. A group operates a
  handful of environments and 409s while any of them still names it; a project can accumulate
  every booking and release it was ever linked to, so the same check would make every project
  permanently undeletable the moment someone booked against it. Deleting soft-deletes it instead:
  existing bookings and releases keep rendering its name, marked *Archived*, and it simply drops
  out of the *Project*/*Owning project* pickers for new selections. Use *Status* → *Archived*
  (`is_active = false`) for the common case of retiring a project without losing its records.

**Usage agreements are a record, not a rule.** From a project's detail page an Admin can add a
*usage agreement* — this project may use environment E, optionally within a window (*Starts*/
*Ends*), with a note — and the same agreements appear read-only on that environment's own detail
page, under *Projects using this environment*. Overlapping windows for the same
project/environment pair are allowed (two periods of intended use aren't a contradiction); only
an exact duplicate — same project, same environment, same window — is refused.

**They now produce a warning — and nothing more.** Since Phase 7 sub-project A3, a booking whose
request names a project that has no live agreement covering that environment for those dates is
flagged. **Nothing is blocked.** The booking is still created, it still transitions, every button
still works, and no approval step depends on it. A gap is a governance finding, not a gate. (The
earlier wording on this page — "enforcement, if the product ever adds it, is separate, later
work" — described A1 and is now out of date in one direction only: there is a warning, there is
still no refusal.)

Where the gaps show up:

- **On the booking itself** (`/bookings/:id`) — a warning panel naming the project and the
  environment, and either "has no usage agreement for" or "falls outside its agreed window for",
  with the window quoted. Anyone in the tenant can *acknowledge* it, with an optional note; who
  did so and when is then shown on the page and survives a reload.
- **In the bookings list** (`/bookings/list`) — an *Agreement* column (a warning icon; greyed
  once acknowledged) and a *Usage agreement* filter with *All bookings* / *In gap* / *No gap*.
  The filter runs on the server, so it narrows the whole result set, not the page on screen.
  *No gap* deliberately also sweeps in bookings that name **no** project at all: nothing assessed
  them, so calling them "covered" would be a claim about a check that never ran.
- **At the moment of creation** — the new-booking dialog raises one warning per environment in
  gap, and creates the booking anyway.
- **On the project's own detail page** — beside the agreements table, a count of that project's
  bookings currently in gap, linking straight to the filtered list. It counts every booking of
  that project regardless of lifecycle status (drafts and closed ones included), because the check
  looks at the project, the environment and the dates and never at the status — the linked list
  shows exactly the same set. If the count could not be loaded it says *unavailable* rather than
  showing zero.

**Acknowledging is not resolving.** An acknowledged gap is still a gap: it still appears under *In
gap*, and the icon stays (greyed). The one thing that clears the warning is **recording the
missing agreement here** — do that and the warning disappears on its own, with no other action and
nothing to re-run, because the check is recomputed on every read rather than stored. Acknowledging
records only that somebody looked at it and accepted it.

Two consequences worth knowing before they surprise you. A window is compared as an **instant**,
not a calendar day: an agreement recorded as ending *30 Jun* does not cover a booking that ends at
17:00 on 30 June, even though the warning renders the bound as "30 Jun 2026". And **soft-deleting
an environment does not delete the agreements pointing at it** (deleting a *project* does cascade
to them), so those agreements stop counting as live — bookings covered only by one will start
showing a gap.

**Why a gap message may name a project you cannot find.** A deleted project keeps rendering its
name on every booking and release that still references it, so **two projects can share a name —
one live, one deleted** — and a warning may name the deleted one while its live namesake's page
shows the very agreement that appears to be missing. If a gap looks wrong that way, open the
booking and check its *Project* field: the picker labels an archived value *(archived)*, and
*Edit request* on the booking's page can point it at the live project instead, after which the
warning re-evaluates on the next read.

### Contention priority

A project's detail page carries a *Contention Priority* section holding one number: the
**priority rank**. It is used when two projects' bookings collide on the same environment, and it
answers exactly one question — *whose booking ought to give way?* Set it by typing a whole number
and clicking *Save rank* (Admin only; everyone else sees the current value read-only).

**Lower wins. Rank 1 is the highest priority**, rank 2 gives way to rank 1, and so on. There is no
upper bound and no requirement that ranks be unique or contiguous — they are compared, not
counted. Zero and negative numbers are refused, because a caller entering one has almost certainly
guessed the direction backwards, and a silently accepted wrong guess would decide every contention
backwards with nothing to notice it.

**Nothing is ever blocked, moved or rescheduled because of a rank.** No booking is refused, no
transition is gated, no button is disabled, and nothing runs on a schedule. The rank produces a
*verdict* — a line of advice shown beside the clash on the booking's *Conflicts* panel — and a
human still decides and still acts. An admin typing a priority into a governance screen may
reasonably expect otherwise, which is why the page says so above the field.

**Unranked is normal, and it is not a loss.** No project has a rank until someone sets one: the
column shipped nullable with no backfill, so on first deploy every project is unranked. A booking
whose project is unranked is not "lowest priority" — **a ranked project does not beat an unranked
one**. The verdict says *"at least one project has no priority rank"*, meaning **priority does not
separate these two**, and stops there rather than inventing a winner. That is deliberate: treating
unranked as lowest would have declared the entire existing estate the loser on the day the feature
shipped.

There are four possible outcomes and **three of them have no winner**, each with its own wording.
Five messages, not four, because "no project" splits in two — the difference matters on screen:

| What the verdict says | What it means |
| --- | --- |
| *"<Project A> outranks <Project B>"* | Both projects are ranked and the ranks differ. This is the only verdict that names a winner. |
| *"at least one booking is not linked to a project"* | One or both bookings have no *Project* set. There is nothing to compare. |
| *"at least one booking's project is archived or belongs to another tenant"* | The booking names a project that cannot be resolved here. The project's **name** may still render beside this message — deleted projects keep rendering their name on rows that reference them — so this is the case to check when the two appear to contradict each other. |
| *"at least one project has no priority rank"* | Both projects resolve, but at least one is unranked. |
| *"both projects have the same priority rank"* | Both are ranked, and equally. |

Changing a rank takes effect on the next page load. The verdict is recomputed on every read and
stored nowhere, so there is no cache to clear and nothing to re-run — and equally, no record of
what the verdict *was* yesterday.

A rank can be set when you create a project or by editing one later. The *New Project* dialog has
no rank field, so a project created through the UI starts unranked and you set the rank by editing
it; the API accepts `priority_rank` on creation as well. Clearing the box and saving unranks a
project again.

For what happens when someone is formally asked to decide a contention, see the user guide's
*Contention escalations* — the worklist is readable by any tenant member, and answering is limited
to the named owner or an Admin.

### Password resets

> **Not yet available:** there is no tenant-admin password-reset flow on `/admin/users`. If a user has lost their password, ask your Master Admin to call `POST /api/v1/admin/tenants/{tenant_id}/users/{user_id}/reset-password` with a fresh `new_password`, then share the new value out of band.

Master-admin elevation lives in [ch. 2](#2-provisioning-a-new-tenant-master-admin-only).

## 5. Modelling your platform: systems and subsystems

### Concept

A **System** is a product or app at the business level — *Payments*, *Identity*, *Search*. A **Subsystem** is one deployable unit of that product — *payments-api*, *payments-web*, *payments-worker*. One System contains many Subsystems.

```
System "Payments"
  ├── Subsystem: payments-api
  ├── Subsystem: payments-web
  └── Subsystem: payments-worker
```

Modelling both layers is what makes EnvManager useful: business-level rollups (the *Payments* release, the *Payments* DORA scores) live on the System, while deployable-unit tracking (which build of *payments-api* is in *staging*) lives on the Subsystem. Get the split right at the start of onboarding — re-parenting subsystems later is fiddly.

### Walkthrough: creating a system

1. Navigate to `/systems`. The page is titled *System Catalog*.
2. Click *New System* in the page header.
3. Fill the *New System* dialog:
   - *Name* — required, e.g. `Payments`.
   - *Description* — free text, multi-line.
   - *GitHub Repository URL* — optional, e.g. `https://github.com/org/payments`. Surfaces as a *GitHub* chip on the catalog row.
   - Any tenant-defined custom fields appear under the standard fields. Custom fields for the *system* entity are configured under tenant settings (see [ch. 11](#11-tenant-settings)).
4. Click *Create*. The system appears in the catalog. Click its row to open `/systems/:id`.

There is no slug field — the system is referenced by its numeric id in the URL.

### Walkthrough: adding subsystems

Subsystems live on the system detail page, not in the global navigation. From `/systems/:id`, switch to the *SubSystems* tab and click *Add SubSystem*. The *Add SubSystem* dialog asks for:

- *Name* — required, e.g. `payments-api`.
- *Description* — free text.
- *Component Type* — one of *Web Service*, *API Gateway*, *Database*, *Cache*, *Message Queue*, *Worker*, *Frontend*, *Other*. Drives the colour and label of the topology node.
- *Technology* — free text, e.g. `FastAPI`, `PostgreSQL 15`.
- Tenant-defined custom fields for the *subsystem* entity, if any.

Each subsystem belongs to exactly one system; the parent is fixed by the page you are on.

Two import shortcuts also live on this tab — *Import Docker Compose* and *Import Terraform* — for bulk-loading subsystems from an existing repo. They are covered in [ch. 12](#12-importexport).

### System dependencies vs component dependencies

EnvManager models dependencies at both layers, on two separate tabs of the system detail page.

- **System dependency** — *Dependencies* tab. A link from this **system** to another system: *Payments depends on Identity*. Click *Add Dependency*, pick a *Target System*, choose a *Dependency Type* (*API Call*, *Database*, *Message Queue*, *Event*, *File*, *Other*) and a *Direction* (*One-way* or *Two-way*). The table shows incoming and outgoing edges side by side.
- **Component dependency** — *Component Deps* tab. A link from one **subsystem** to another, possibly in a different system: *payments-api depends on identity-api*. *Add Component Dependency* asks for *From SubSystem* (constrained to this system's subsystems), *To SubSystem* (any subsystem in the tenant), *Type*, and *Direction*. Editing a component dependency lets you record *Protocol*, *Port*, and individual API *Endpoints* (HTTP method + path + description).

Rule of thumb: declare a system dependency once you know two products talk to each other; add component dependencies as you learn which specific services carry that traffic. System dependencies drive impact rollups; component dependencies drive the topology diagram.

### Reading the topology view

The *Topology* tab on the system detail page renders a graph using React Flow. Each subsystem is a rectangular node, outlined and chip-coloured by component type — *Web Service* green, *API Gateway* teal, *Database* blue, *Cache* amber, *Message Queue* purple, *Worker* orange, *Frontend* indigo, *Other* grey. Subsystems of the current system are grouped inside a labelled box; subsystems of any system referenced by a component dependency appear as a second group alongside.

Edges are component dependencies. The arrow points from dependent to dependency (`from → to`); two-way dependencies have arrowheads on both ends. The edge label is the dependency type (or its custom label, if set). Click an edge to open a detail pane with the protocol, port, and endpoint list; click again to deselect. Pan and zoom controls plus a minimap are provided. Nodes are not draggable.

> **Not yet available:** clicking a subsystem node does not navigate or open a detail pane — only edge clicks are wired up.

### Tips

- Keep the System/Subsystem split honest: one System per shippable product. Resist the urge to model an internal library as its own System.
- Each Subsystem should map 1:1 to a CI build target — *payments-api* corresponds to one build pipeline. This pairing matters for the deployment webhook (see [ch. 10](#10-api-keys-and-webhooks)).

> **Not yet available:** DORA metrics dashboards (deployment frequency, lead time, change failure rate, mean time to restore) are planned for Phase 5+. EnvManager currently captures the underlying events (Builds, Deployments, Change Requests) so the data is there when the dashboards land.

> **Not yet available:** GitHub-driven infrastructure discovery enrichment (auto-detecting subsystems, dependencies, IaC links from a repo) beyond the manual *GitHub Repository URL* field on a System is deferred. The current `/api/v1/import/terraform` and `/api/v1/import/docker-compose` endpoints (see [ch. 12](#12-importexport)) populate subsystems and component dependencies but stop short of full enrichment.

## 6. Modelling environments

### Concept

An *Environment* is a logical instance of one or more systems — *UAT-1*, *PROD-EU*, *perf-staging*. It has a name, a free-text *type* (e.g. *staging*, *uat*, *dev*, *prod*), a status, and optional custom fields. Systems are attached to it after creation.

An *Environment Instance* is the deployed copy of a specific subsystem inside that environment, optionally pinned to one or more hosts. Instances live behind the *Components* tab of an environment.

```
Environment "UAT-1"
  ├── instance: payments-api  (subsystem) on host-7
  ├── instance: payments-web  (subsystem) on host-8
  └── instance: identity-api  (subsystem) on host-9   ← belongs to a different system
```

*Environment* is what humans book, change, and release into. *Instances* are what builds deploy to and what the topology graph draws.

### Status lifecycle

Every environment has one of four statuses:

- **active** — bookable, deployable, the normal state.
- **maintenance** — temporarily not bookable; use this for scheduled patching or restores.
- **inactive** — stood down but not retired; useful for cold-spare environments.
- **decommissioned** — retired. Hide from default views.

Transitions are unconstrained — you can move between any two statuses by editing the environment. *Decommissioned* is reversible; bring an environment back simply by editing the status.

**This direct edit still works, and it is now the informal path.** Since Phase 7 B5, the audited way to retire an environment is the *Decommission* panel described below — it warns the owner, gates the actual `status` write on signed attestations, and leaves a record of who did what and when. Editing *Status* to *decommissioned* by hand on this form skips all of that: no warning, no checklist, no record beyond the environment's own updated timestamp. Reserve the manual edit for correcting a mistake (e.g. an environment decommissioned outside the register, before B5 existed) rather than for retiring an environment going forward.

```
   ┌──────────────┐
   │              ▼
active ◄──► maintenance
   ▲              │
   │              ▼
inactive ◄──► decommissioned
```

### Walkthrough: creating an environment

1. Navigate to `/environments` and click *New Environment*.
2. Fill in the form:
   - **Name** (required) — e.g. *UAT-1*. Unique within the tenant.
   - **Description** — optional free text.
   - **Tier** (required) — a tenant-configurable vocabulary, not free text. Configure the list under *Administration → Environments → Tiers*; each tier carries a name and a colour, and drives filtering and the topology/grid chip colouring.
   - **Owner** (required) — a named user responsible for the environment. Shown on the list and detail pages; missing an owner *or* an operations group is a reportable governance gap (`?governance_gap=true`).
   - **Operations Group** (optional) — the team responsible for this environment day-to-day, picked from *Administration → Organisation → User groups* (see [ch. 4](#4-managing-users-and-roles)). Shown on the list and detail pages; leaving it unset counts toward the same governance gap as a missing owner.
   - **Expires** (optional) — the date this environment is expected to retire. Leave blank for "no expiry planned" — that is a legitimate state, not a missing value, and does not count as a governance gap. Use the *expiring within N days* filter on the list page to find environments approaching their expiry.
   - **Status** — defaults to *active*.
   - **Custom Fields** — any tenant-defined fields for the *environment* entity (configured in *Administration → Environments → Custom fields*; see [ch. 11](#11-tenant-settings)).
3. Click *Create*. The environment is created with no systems attached.
4. Open the new row to land on the detail page, then move to the *Systems* tab to attach systems.

> **Note (first deploy after operations groups shipped):** `operations_group_id` is
> nullable with no backfill — by design, since there is no automatic way to guess
> which team should own an existing environment. That means `?governance_gap=true`
> matches **every** existing environment until someone assigns groups, so the
> *Governance gap* chip will flag the whole estate on day one. That is correct
> behaviour, not a bug: work through the list assigning operations groups (and
> owners, for any row still missing one) to bring the gap count down.

### Walkthrough: adding environment instances

Instances are managed on the *Components* tab. As soon as you attach a system on the *Systems* tab, that system's subsystems appear as candidate instances. For each instance you can:

- Toggle **Real / Mock** — click the chip. Mocked instances are excluded from version recording and shown as dashed nodes on the topology graph. Add *Mock Notes* inline when mocked.
- Set the **Component Type** — opens a dialog to pick a tenant-defined type (database, cache, web service, etc.).
- Attach **Hosts** via *Manage…* — opens a dialog where you add one or more hosts and tag each with an optional *role* string (e.g. *primary*, *replica*). A subsystem can span multiple hosts (replicas, multi-AZ).
- Record a **Version** via *Record Version* — captures *Subsystem*, *Build ID*, *Version Label*, *Installed At*.

Hosts are optional. Purely-logical environments work without them — see [ch. 7](#7-modelling-infrastructure-hosts) for when you actually need to model hosts.

### Walkthrough: environment dependencies

EnvManager does **not** model environment-to-environment dependencies directly. Dependencies are declared once at the *system* and *subsystem* level (see [ch. 5](#5-modelling-your-platform-systems-and-subsystems)), and EnvManager checks them per-environment.

On the *Overview* tab, click *Verify Environment*. Each system dependency is reported as *satisfied* (target system attached), *mocked* (covered by a mocked subsystem), or *missing*. Component dependencies are checked the same way. Run this before each booking — if a dependency is *missing*, attach the required system on the *Systems* tab.

### Walkthrough: decommissioning through the workflow

Since Phase 7 B5, retiring an environment goes through a **Decommission** panel on the environment's *Overview* tab rather than a bare status edit — a warning period, an optional one-time extension, a signed checklist, then teardown.

**Who can do what.** Starting a decommission, deciding an extension, signing attestations, tearing down and cancelling are all done by the environment's **operations group** (see [ch. 4 §User Groups](#user-groups)) or an Admin / master admin. **Requesting** an extension is different: it is the environment's **named owner**, or an Admin — the person defending their environment against an early teardown is deliberately not required to be on the team decommissioning it. Where an environment has **no** operations group, or the group is empty, every team action falls back to **Admin-only** — the same degradation B3b uses for handover edits, so a permission that would otherwise resolve to nobody does not stall the workflow.

1. Open the environment and scroll to the **Decommission** panel below Handover. If there is no active decommission, click **Start decommission**.
2. Give a **Reason** (required — this becomes the audit record) and, optionally, a **Teardown date**. Leave it blank to use the tenant's default notice period (below); if you set one yourself it must be **on or after** that default — an initiator cannot shorten the notice a policy promises.
3. The environment is now **Warned**, and the panel shows the scheduled teardown date to anyone who opens it. **Bookings that finish before that date are still accepted; a booking (or a date edit) that would run past it is refused**, on every booking path including recurring bookings and per-environment date edits — there is no separate step to police this, it falls straight out of the date.
4. If the owner needs more time, they click **Request extension**, gives a reason and a new date, and the panel moves to **Extension requested**. A team member or Admin clicks **Grant extension** (moves the teardown date to the requested one and reopens what is bookable — no other action needed) or **Refuse extension** (the original date stands). **Only one extension is allowed per decommission.** If more time is genuinely needed after that, **cancel and start again** — see below; the cancelled record is kept, so nothing about the first attempt is lost.
5. Work through the **Checklist** — the tenant's decommission steps (below). Each **Required** step needs a signature (a reference — a snapshot id, a ticket, a runbook link — and optional notes) before teardown is allowed; **Optional** steps do not gate it. Signing is permanent: there is no un-sign, and a mistaken signature is corrected by cancelling the decommission rather than editing the attestation.
6. Once every active required step is signed, click **Tear down**. This is the one step that changes anything outside the decommission's own record: it sets the environment's *Status* to **decommissioned** and records who did it and when. Trying to tear down early is refused with a message **naming exactly which steps are still missing**.
7. **Nothing is cancelled or moved for you.** Bookings still on the calendar at teardown are listed under *Bookings not touched by teardown* rather than being altered — clear or transition them yourself first if that matters for this environment (*Schedule* tab, or `/bookings`).

**Cancelling** is available at any point up to teardown, to a team member or Admin, and needs a reason. It is the only way to correct a decommission started in error or with the wrong checklist — there is no edit path.

**What EnvManager does not do.** It holds no cloud credentials and has no way to actually take a backup or tear down a resource — that is why teardown is gated on a **human** attesting they did those things, not on the register doing them. And there is no "Available" status to return an environment to at teardown: it becomes *decommissioned*, and the calendar and any remaining bookings are left for a person to deal with.

The status change is still **reversible** the same way it always was — editing *Status* back to *active* — and the environment is only soft-deleted when you click *Delete* on the list page. Use *decommissioned* to hide an environment from working views without losing history; use *Delete* (which sets `deleted_at`) only when you're sure the audit trail no longer needs to surface it.

### Reading the environment topology

The *Topology* tab on the environment detail page renders a force-directed graph (built on React Flow). Each *system* is a labelled group box; subsystems sit inside their parent system. Solid-bordered nodes are real instances, dashed-grey nodes are mocked. Subsystems pulled in by an outside dependency appear in a separate group labelled *— not in environment*. Edges are component dependencies; arrows show direction (two-way edges have arrowheads on both ends).

You can pan, zoom, and use the minimap. **Click an edge** to open a side panel with the dependency's type, label, protocol/port, and any documented endpoints. Nodes are not draggable — the layout is computed automatically.

### Environment Requests, routing and the Welcome Pack

Any tenant member can raise an *Environment Request* at `/environment-requests` — either **Access**, against an existing environment, or **New environment**, proposing one that doesn't exist yet. Both modes share one status lifecycle, seeded per tenant as *Standard Request*:

```
        ┌───────┐
        │ draft │  ◄──── (Return for Revision)
        └───┬───┘                       ▲
            │ Submit                    │
            ▼                           │
      ┌────────────┐                    │
      │ submitted  │ ───────────────────┘
      └─┬───────┬──┘
Approve │       │ Reject                 Cancel is also available
        ▼       ▼                        from draft and submitted —
   ┌─────────┐ ┌──────────┐              the requester can withdraw
   │approved │ │ rejected │  (terminal)  their own request either way.
   └────┬────┘ └──────────┘
        │ Mark Fulfilled      Reject (from approved too — see below)
        ▼
   ┌───────────┐
   │ fulfilled │  (terminal)
   └───────────┘
```

**Routing.** Who may move a request into *approved*, *rejected* or *fulfilled* depends on its kind:

- An **access** request routes to the target environment's **operating group** — a member of that group, or an Admin, can act on it. Submitting an access request against an environment with **no** operating group is refused outright (a 409 naming the environment); there is nobody to route it to, and a request only an Admin can see is worse than a clear error telling the requester to ask an Admin to assign one first.
- A **new-environment** request has no target environment yet, so it always routes to an **Admin** — there is no group to check. The approving Admin is also the one who picks the *operations group* the environment will have once it exists, in a picker on the request's detail page.

Submitting a request and cancelling your own draft or submitted request need only your ordinary tenant role — every role can raise and withdraw their own request, including a Viewer, who is exactly the person most likely to need access. Only the three approval-side moves check group membership.

**Fulfilment creates the environment INACTIVE, not active.** Approving a new-environment request and clicking *Mark Fulfilled* creates the `Environment` row — with the requested name, tier, expiry and operating group already set — but its status starts **inactive**. The register must not claim an environment is available before anyone has actually built it; once the real infrastructure exists, an Admin edits the environment and flips its status to *active* the same way as any other environment (see [ch. 6 §Status lifecycle](#status-lifecycle)). An **access** request's fulfilment does nothing to the environment at all — there's nothing to create.

**Handover vs Governance — the same page, two different write rules, on purpose.** An environment's detail page carries both a *Governance* section (tier, owner, expiry, operations group — Admin-only, see [ch. 6 §Walkthrough: creating an environment](#walkthrough-creating-an-environment)) and a *Handover* section (the six fields listed under [ch. 4 §User Groups](#user-groups)), editable by the operating team as well as Admins. A member of the operating team who isn't an Admin therefore sees Governance read-only and Handover editable on the same screen. That's deliberate, not a bug: the write is narrow by construction — the Handover endpoint accepts only those six keys and nothing else, so a team member can never reach tier, owner, status or which group operates the environment through it, however permissive the check on that one endpoint is. Without this split, only Admins could author connection details, VPN routes and support contacts for every environment in the tenant — content that actually lives with the operating team, not with Admins — and the Welcome Pack would stay empty in practice. The page labels the Handover section to make the asymmetry read as intentional.

**The Welcome Pack** appears on a fulfilled request's detail page: environment summary, how to connect, support (including the operating team and its member list), known limitations, and offboarding notes. It is rendered **live** from the environment's current Handover fields on every view, not a document captured at fulfilment time — so a VPN endpoint the operating team updates next month shows up the next time anyone opens the pack. A field nobody has filled in reads **"Not provided"**, not a blank section; the pack always shows every heading, because an empty "How to connect" section reads as "there is nothing to do" rather than "nobody has documented this yet".

**How far the lifecycle is editable.** *Standard Request* is deliberately plain — the diagram above — and a tenant can extend it like any other lifecycle template, from *Administration → Environments → Request lifecycle* (`/admin/environment-requests/lifecycle`): add a second review step, add states, rewire which roles may make which transition. The one constraint is that a template must still define states named exactly `submitted`, `approved`, `rejected` and `fulfilled`, plus exactly one initial state (any name) — the service's own routing, fulfilment and Welcome-Pack logic key on those four names, so renaming one doesn't shrink the feature, it silently breaks it (a state the service no longer recognises as an approval target skips the group-membership check entirely, or a request reaches a status the template has no way out of). Saving a template that drops one of the four is refused with a 422 naming which is missing.

> **Deploy note.** Migration `envrequests` seeds *Standard Request* into every existing tenant as
> part of `alembic upgrade head`. If that revision was ever applied to a database *before* this
> seeding step existed — which happened on the dev box, because the seed block was appended to
> the migration after `alembic upgrade head` had already run it once — `alembic_version` reads
> `envrequests` and the seed never runs, and no tenant on that database gets a template. The
> symptom is every `POST /environment-requests` answering 400 *"This tenant has no
> environment-request lifecycle configured"*. Check for it, and if found, run
> `seed_environment_request_defaults_for_tenant` by hand for each affected tenant rather than
> re-running the migration (which alembic will refuse, having already recorded it as applied). A
> clean deploy that has never seen an intermediate version of this migration completes the seed
> once and needs no follow-up.

### Environment Groups

An *Environment Group* is a named set of environments that gets booked, and transitions, as one unit — e.g. a *"Payments squad"* group covering that team's UAT, perf and staging environments together, so booking the group books all three in one request instead of three separate ones.

**Concept.** A group is just a name, an optional description, an active/archived flag, and a set of member environments. It carries no schedule, no owner and no tier of its own — those still belong to each member environment individually. Booking a group **expands it to one booking per current member** at the moment the request is created; the group is a convenience for creating and transitioning those bookings together, not a fourth thing alongside environments and instances in the inventory model.

**Walkthrough: creating a group and adding members.**

1. Navigate to `/environment-groups` and click *+ New Group* (Admin only — any tenant member can view the list and open a group, matching the read/write split on User Groups and Projects).
2. Fill in **Name** (required, unique within the tenant) and an optional **Description**. Click *Create*.
3. Open the new row. On the group's detail page, pick an environment from the **Environment** selector and click *Add* to add it as a member. Repeat for each environment the group should cover.
4. The grid's **Environments** column shows the live member count.

**Membership is frozen at booking time.** The group detail page states this directly, and it is worth restating here because it is easy to assume otherwise: **changing a group's membership never affects any booking already made through it.** Adding an environment to a group does not retroactively add it to bookings already raised against that group; removing one does not cancel or touch a booking already made. Each booking created from a group carries its own fixed list of member environments as of the moment it was booked — the group referenced on that booking is a record of where it came from, not a live link the booking keeps re-reading. If a group's environments and a specific booking's environments need to look the same, that only happens because nothing has changed the group since that booking was raised — not because the booking tracks the group going forward. See `user-guide.md` ch. 5 §Booking a group of environments for what this means from the booking side.

**Deleting a group** removes its membership records but leaves the history of any booking already made through it untouched — deleting a group is not a way to undo or clean up past bookings.

**Sorting and filtering.** The grid is client-side (loads the tenant's groups once, sorts and filters in the browser) — the same convention as `/admin/user-groups` and `/projects`, appropriate at the scale a tenant's own group list actually reaches. **Name** and **Created** are the only server-backed sortable columns if this grid is ever converted to a server-paged one; **Environments** (the member count) can never be, because it is computed from live membership rather than stored on the group row.

### Naming and tagging policy

A *naming and tagging policy* declares what an environment's **name** must look like and which
**attributes** every environment must carry. It lives at *Administration → Environments →
Naming policy*, one policy per tenant.

**What it does and does not do.** Exactly one thing is refused: saving a **changed** name that does
not match the pattern is rejected with a 422 quoting your worked example. Everything else —
missing attributes, names that were already non-conforming before the policy existed, quarantine
itself — is **reporting**. A quarantined environment can still be booked, transitioned, deployed
to and reported on. Nothing anywhere terminates or locks a resource: EnvManager is a register, not
a cloud control plane, so "quarantine" here means a label and a filter.

**The fields.**

- **Policy enabled** — the off switch. Disabling it stops every judgement without losing the
  pattern.
- **Name pattern** — a regular expression the *whole* name must match. Leave it blank for
  "attributes only, no naming rule". It is evaluated on the server, by one evaluator; the admin
  form never runs it in your browser, because two regex engines disagree on real patterns and a
  name refused at save would then report compliant on the list.
- **Example name** — a worked example, shown in the UI **and quoted in the 422**. A save is
  refused if your own pattern rejects your own example, since otherwise the error message teaches
  a name that will also be refused.
- **Required attributes** — any of *Owner*, *Expiry date*, *Operations group*, plus one entry per
  environment custom field. Note **Tier is deliberately absent**: an environment's tier is already
  structurally mandatory, so requiring it would be a check that can never fail.
- **Grace period (days)** — how long an environment may fail the policy before it reads as
  *quarantined*. Counted from whichever is later: the policy's effective date, or the
  environment's creation date. **Both clocks round in the environment's favour**, to whole UTC
  days: an environment created at 15:00 keeps the rest of that day, and so does a policy saved
  at 15:00. So **a grace period of 0 does not quarantine anything the day you set it** — it
  bites at the next UTC midnight. That is deliberate, and it is the same day-granular rule the
  contention deadlines use; setting 0 and seeing nothing change is not a bug.

**Preview before you enable.** The *Preview* button answers "what would this rule do" for the
pattern and attributes **currently in the form**, not the ones last saved: how many of your
environments would be in gap, how many would read as quarantined immediately, and a sample of
names. Use it before switching a policy on.

> **Expect most of your estate to be flagged on day one.** A policy is judged against
> environments that already exist, and nothing is backfilled or grandfathered. Enabling a pattern
> that your older environments were never named for will put most of them in gap immediately —
> that is correct, and it is what the grace period is for. Preview first so the number is not a
> surprise, and set a grace period long enough for the work the list implies.

**Two things that look like one thing.** The Environments list now carries two similar-sounding
chips, and they mean different things:

- **Governance gap** — B1's fixed pair: no owner **or** no operations group. Not configurable.
- **Policy gap** — fails *your* policy: the name pattern, or any attribute you listed.

They overlap by design. A policy that requires *Owner* will flag rows the *Governance gap* chip
also flags. Neither is derived from the other, and turning one off does not affect the other.

**Listing an attribute reports; marking a custom field required refuses.** These are two different
mechanisms and it is worth being deliberate about which you want. Listing `cf:cost_centre` here
means "report environments that lack it". Marking that field **required** in *Custom Fields* means
"refuse a save without it". Use the first to measure an estate you do not control yet, the second
once you do.

**When the effective date resets.** Changing the pattern or the attribute list bumps the policy's
effective date, which restarts the grace period for every environment. Changing the grace period,
the example, or the enabled switch does **not** — those do not change what is being asked. Note
the reset happens when a requirement is *relaxed* as well as tightened: whether a regex change is
stricter is not a decidable question, and granting fresh grace for a relaxation is harmless.

**One consequence to be aware of.** Grace runs from the policy date or the environment's creation,
whichever is later — there is no per-environment "failing since" record. So an environment that
*starts* failing later (its owner is deactivated, say) is quarantined at once, with no fresh grace.
The alternative would need a second stored value invalidated by things far outside any
environment edit, such as deleting a user.

### Idle detection and the decommissioning workflow

*Administration → Environments → Lifecycle & decommissioning* is where a tenant
configures the two halves of Phase 7 B5: whether — and how eagerly — an unused environment is
flagged as idle, and the checklist a decommission is gated on. Reading this tab needs only
tenant membership; saving it needs Admin.

**Idle detection is off by default, and there is a reason to leave it that way until you mean to
turn it on.** Flip the *Idle detection enabled* switch and every environment already quiet longer
than the threshold below is flagged **immediately, across the whole estate** — not just ones
booked from now on. That is correct, and it will look exactly like a bug the first time you see
it: B2's *Governance gap* chip did the identical thing on first deploy, for the identical reason —
nothing is backfilled or phased in, the rule is simply applied to everything that already exists.
Turn it on when you are ready to see (and work through) that number, not before.

**What counts as activity.** An environment reads idle only once it has gone longer than the
threshold with **no deployment and no booking whose window overlaps that period** — overlap, not
start, so a long booking taken well before the threshold still counts as claiming the environment
throughout. **Health monitoring heartbeats do not count.** A monitored environment that nobody is
actually using is exactly the ghost this feature exists to surface; if heartbeats counted as
activity, no monitored environment could ever be found idle, however unused it is.

**The fields.**

- **Idle detection enabled** — the off switch described above.
- **Idle threshold (days)** — how long an environment may go without a deployment or an
  overlapping booking before it reads as idle. Applies tenant-wide unless a tier overrides it (see
  below). An environment younger than this many days is never idle, whatever its activity —
  otherwise every new environment would be born a ghost.
- **Decommission notice period (days)** — the default gap between starting a decommission and its
  scheduled teardown date, used whenever the person starting one does not pick a later date
  themselves. An initiator may push the teardown date out; they may never pull it in ahead of this
  notice.

**A tier can override the idle threshold.** On the *Tiers* editor (*Administration → Environments
→ Tiers*), each tier has its own **Idle threshold override (days)**, left blank by
default to inherit the tenant's number above. A Dev sandbox quiet for 30 days is a ghost worth
flagging; a DR or Training environment quiet for 90 is behaving exactly as intended, and a single
tenant-wide number necessarily mislabels one of them. Clear the override field to go back to
inheriting the tenant default.

**Idle is a flag, not a status.** It shows up as a column and an *Idle* filter chip on the
Environments list; there is no `idle` status and an idle environment is still fully active,
bookable and deployable — nothing about it changes on its own.

**The Decommission Checklist** is the tenant's vocabulary of attestation steps — the things a
human must confirm were actually done (a final backup, DNS removal, licence release, whatever your
process requires) before a teardown is allowed to proceed. Every tenant starts seeded with two
required steps, *Final backup taken* and *Infrastructure torn down*, both required. For each step
you set:

- **Label** and **Description** — shown to whoever is signing it.
- **Key** — a stable identifier. Signed attestations reference this even after the step's label
  changes or the step itself is retired, so an old signature keeps reading correctly.
- **Display order** — where it sits in the checklist.
- **Required** — a teardown is refused, and told exactly which required steps are still
  unsigned, until every **active** required step has a signature. An optional step is shown but
  never blocks anything.
- **Active** — retiring a step (the *Delete* action, which soft-deletes it) stops it gating any
  *future* decommission immediately. It does **not** remove or invalidate attestations already
  signed against it — the signature stands as part of that decommission's record.

See [ch. 6 §Walkthrough: decommissioning through the workflow](#walkthrough-decommissioning-through-the-workflow)
for how the checklist and the idle flag are actually used, and *Bookings →
Decommissions* (`/decommissions`) for the worklist of every decommission across the tenant, live
and finished alike.

## 7. Modelling infrastructure (hosts)

### Concept

Hosts (called *infrastructure components* in the data model) are the physical or virtual machines, clusters, and managed services that environment instances run on. They are **optional**. Purely-logical environments — where you only care about which subsystems are deployed — work fine without any hosts modelled. You'd model hosts when you want to ask cross-cutting questions like *"what's running on this server?"* or *"if `host-7` is decommissioned, which environments break?"*. Hosts live at `/infrastructure/hosts` on the *Hosts & Infrastructure* page.

### When to model hosts

Bother modelling hosts when:

- You consolidate multiple subsystems on one host and need impact analysis if it goes down.
- You're tracking IaC-managed infra and want a unified inventory across tenants and teams.
- You audit compliance per-host — patch level, region, provider, ownership.

Skip it when your team runs everything on managed cloud services (Lambda, Cloud Run, RDS-only stacks) where the underlying host is invisible and you have no operational reason to track it. You can always come back and add hosts later — the link from instance to host is a junction record, not a foreign key on the instance.

### Walkthrough: creating a host

1. Navigate to `/infrastructure/hosts`.
2. Click *New Host*.
3. Fill the form:
   - *Name* — required, unique within the tenant (e.g. `host-prod-web-01`).
   - *Description* — free text.
   - *Type* — *Server*, *Container Runtime*, *Kubernetes Cluster*, *Managed Database*, *Load Balancer*, *Network*, *CDN*, *Queue*, *Cache*, or *Other*.
   - *Provider* — short slug, e.g. `aws`, `gcp`, `orbstack`, `on_premise`.
   - *Region* — e.g. `eu-west-1`.
   - *Location* — physical hint, e.g. `macmini.lan` or rack ID.
   - *Source* — see below; defaults to *manual*.
   - *External ID* — optional handle for future IaC matching (Terraform resource address, ARN, etc.).
4. Click *Create*. The host now shows up in the grid and is selectable from the *Hosts* dialog on any environment instance.

### Sources

The *Source* field records where a host record originated:

- *manual* — you typed it into the form. This is the only path that is fully wired up today.
- *terraform* — reserved for hosts populated by a Terraform state-file parser.
- *docker_compose* — reserved for hosts populated by a Docker Compose parser.

> **Not yet available:** the Terraform and Docker Compose importers (`POST /api/v1/import/terraform`, `POST /api/v1/import/docker-compose`) currently create *subsystems* and *component dependencies* — they do **not** create infrastructure-component (host) rows. Picking *terraform* or *docker_compose* in the form today is purely a label so you can record provenance manually; no automatic discovery exists yet. Treat these values as forward-compatible metadata until the importers are extended.

### Linking a host to an environment instance

Hosts get attached to instances on the *Components* tab of an environment — see [ch. 6 §Walkthrough: adding environment instances](#walkthrough-adding-environment-instances). Click *Manage…* under *Hosts* on any instance to open the dialog, pick one or more hosts, and tag each with an optional *role* string (e.g. *primary*, *replica*).

## 8. Configuring change kinds and gates

### Concept

A **change kind** is a tenant-configurable category of work that flows through a release — `story`, `defect`, `task`, `spike`, plus anything you add yourself. Kinds drive which scope items show up on a release's *Scope* tab, and whether a particular kind *counts as a scope change* for the rolled-up scope-churn metric. They also discriminate custom-field definitions, so you can attach (say) a `severity` field that only appears on items of kind `defect`.

A **gate** is a checkpoint on a single release — *UAT sign-off*, *Security review*, *CAB approval*. Each gate carries a required `due_date` (an absolute timestamp, not a relative offset) and a list of *criteria*. **Gates do not block release transitions** — see the note at the end of the next section — but the `due_date` renders as a status-coloured diamond on the release timeline, and since Phase 9 sub-project C2 a gate can also carry a tenant-configured *type*, structured *evidence*, and a *waiver* in place of an informal override; see *Gate Types* below.

### Walkthrough: managing change kinds

The change-kind admin UI lives at `/admin/releases/scope-change-rules` — page component `TenantScopeChangeRules`. Every new tenant is seeded with four kinds:

| Kind | Counts as scope change |
|------|------------------------|
| `story` | yes |
| `defect` | no |
| `task` | no |
| `spike` | no |

To add a kind:

1. Navigate to `/admin/releases/scope-change-rules`.
2. In the *Add a new change kind* panel, type a slug into the *Kind* field. Allowed: lowercase letters, digits, `_` and `-`, up to 20 characters. Examples: `chore`, `epic`, `migration`.
3. Click *Add*. The new kind appears in the rules table with *Counts as scope change* off.
4. Toggle the switch on if items of this kind should contribute to the rolled-up scope-change metric.
5. Click *Save* to persist all pending changes in one batch.

> **Not yet available:** the UI has no rename, archive, or delete control — once a kind exists, the only switch you can flip is *Counts as scope change*. To remove or relabel a kind today, edit `scope_change_kind_rule` directly; the admin API at `PUT /api/v1/tenant/scope-change-rules` only upserts. A full CRUD page is on the backlog.

### Walkthrough: configuring gates

There is **no tenant-level gate library**. Gates exist in two places only:

- **On a release template** — the template's `gates` JSON array carries a skeleton that is materialised into real gate rows when a release is created from the template. Edit the skeleton from the *Release Templates* admin page — see ch. 9.
- **On a release** — the *Plan* tab on any release has a *Gates* section. Click *Add Gate*, fill *Name* (e.g. *UAT Sign-off*) and *Due date* (a calendar picker — required, stored as an absolute UTC timestamp), then *Create*. Each gate can carry one or more *criteria*, each assignable to a user and toggleable as *open* or *done*.

Gate dates render on the release Gantt as coloured diamonds — slate pending, green passed, red failed, amber overridden — so missed milestones jump out. **A release is never blocked by gate state**: `lifecycle_service` does not reference `release_gate` at all, and a release can be transitioned, including to a terminal status, with every gate still pending and every criterion still open. Gates and their overdue badges are read entirely as a checklist for humans, not as a backend precondition — see user guide ch. 8 for the same statement from the release-detail side, and *What C2 established* in [phase-9.md](phases/phase-9.md) for the guarding test.

### Gate Types

*Administration → Releases → Gate types* (`/admin/releases/gate-types`, Admin only) is where your tenant declares the **vocabulary** a gate can be typed against — a `functional` gate reads differently from a `security` one, and each type declares what a failure *should* mean and what evidence is expected. Every tenant is seeded with the eight standard types from [requirements.md §2.11](../requirements.md): *Functional*, *NFR / Performance*, *Integration*, *Security*, *License*, *Accessibility*, *Business*, and *Ops Readiness*. You can edit any of them, deactivate ones you don't use, and add tenant-specific types alongside them — a tenant-added type shows no *Standard category*, since that column is only populated for the eight seeded types.

Each type has:

- **Verdict behaviour** — `Blocks (advisory)`, `Warns`, or `Accept with exception`. This is a **label for the readiness verdict only** — see *What `failure_behaviour` does, and does not do* below.
- **Expected evidence** — a free-form list of evidence *kind* names (e.g. *Test execution report*, *Defect summary*). These are offered as suggestions in the *Add Evidence* dialog's *Kind* field, not a closed list — evidence of an unlisted kind is still accepted, it simply satisfies no expectation and the readiness verdict will list it as missing.
- **Requires a deployment link** — whether evidence of this type is expected to name the deployment it vouches for. Also a hint, not an enforced rule: the *Add Evidence* dialog shows an explanatory note when this is on and no deployment has been picked, but the save proceeds regardless.
- **Display order** and **Status** (*Active*/*Inactive*) — an inactive type is hidden from the type picker on gates and templates but still renders correctly on any gate already using it; deactivating a type does not retype the gates that used it.

Name uniqueness (per tenant) is enforced by the service, not a database constraint — same as `environment_tier` and `user_group`.

**Assigning a type to a gate** happens on the gate itself: the *Type* select inline on each row of a release's *Gates & Test Phases* tab. The *Release Templates* admin page (ch. 9) also has a *Gate Type* field on each gate skeleton, so a release created from a typed template starts typed too — this is how the SIT → UAT → Pre-Prod → Production strictness ladder from §2.11 is meant to be expressed: a "UAT Sign-off" type that expects more evidence kinds than a "SIT Sign-off" type, materialised onto the right phase by the template at instantiation (the gate also records which phase it was matched to, via `test_phase_id`, though nothing reads that column back today). There is no second policy engine matching (type, tier) pairs; strictness is only ever what the type itself declares.

#### What `failure_behaviour` does, and does not do

**It does not block anything, ever.** No `failure_behaviour` value — not even `Blocks (advisory)` — refuses a release transition, a deployment, or a booking. What it controls is a single thing: whether a pending gate of that type appears as a **blocker** or a **warning** in the readiness verdict (the banner on the release page, and the `release-ready` webhook response described in ch. 10). `Blocks (advisory)` produces a blocker entry in that response; `Warns` and `Accept with exception` both produce a warning entry, and today there is no behavioural difference between the two — the distinction is for the reader (and for a future consumer, such as a connected pipeline, that might treat them differently). A gate with no type set at all is always a warning, never a blocker — every existing gate in every tenant is untyped until someone assigns it a type, and treating "nobody has said" as "block" would turn on a wall of blockers nobody configured on the day this shipped.

The readiness verdict is advisory end to end. It exists so a **connected deployment pipeline can choose to act on it** — refuse a promotion, post a warning to a chat channel, whatever your pipeline is built to do — not so that EnvManager enforces anything itself. See ch. 10, *Preflight: release-ready*.

#### Seeding gate types: normally automatic

The migration that introduced gate types (`gatetypes`) backfills the eight standard types for every tenant that exists at migration time — this happened automatically for `demo` and `system` on this deployment — and `tenant_service.create_tenant` seeds every tenant created afterwards. **In the ordinary case there is no deploy step to run.**

The one case that still needs `seed_gate_type_defaults_for_tenant` run by hand is **a tenant restored from a backup taken before the migration**. The seeder is idempotent, so running it against an already-seeded tenant is harmless.

A tenant with no seeded types is worth recognising, because there is no error — just an empty vocabulary: the *Gate Types* tab shows an empty table and the type selector on every gate offers nothing but *Untyped*, so the feature reads as **broken** rather than unconfigured. Check this first if a tenant reports "gate types don't work."

### Post-implementation reviews: the two migrations

The PIR findings work ships **two** Alembic revisions, and the second is the only destructive
migration in it.

- **`pirfindings`** is additive: three new tables (`pir_finding`, `pir_action`,
  `pir_finding_incident`), no change to any existing table, no backfill. There is no deploy step.
- **`pirbackfill`** moves each PIR's free text into those tables and **then drops five columns**
  from `pir`: `incident_id`, `root_cause`, `what_went_well`, `what_went_wrong` and `action_plan`.

**What the backfill does with existing reviews.** `what_went_well` becomes a went-well finding
titled *What went well (migrated)*, with the original text as its detail. `what_went_wrong`,
`root_cause` and `action_plan` become a single went-wrong finding — *What went wrong (migrated)* —
carrying the root cause, with the action plan as its first action. A PIR that had only an
`incident_id` gets a went-wrong finding titled *Incident (migrated)* so the citation has something
to hang from. Titles are **fixed strings, never a truncation of the body**: `pir_finding.title` is
500 characters and the old text was unbounded, so slicing it in would have silently lost the tail of
a long review. The body always goes to `detail`, which has no cap.

Three things it deliberately skips: a PIR that only ever had a summary migrates to nothing; a column
holding only whitespace counts as empty (a blank finding is worse than no finding — someone has to
read it to discover it says nothing); and a soft-deleted PIR is not migrated at all, because a
withdrawn review is not evidence.

**The downgrade re-adds the five columns as nullable and DOES NOT reconstruct the text.** The
findings, actions and citations survive a downgrade; the original free text does not come back. If
you need to be able to return to the old shape with its data, take a backup before upgrading — the
downgrade is a schema reversal, not a data one.

**Nothing else to run.** No seeding, no per-tenant step, no standing deploy task — unlike
`envrequests` (ch. 6) or `gatetypes` above.

### Rollback Policy

*Administration → Releases → Rollback policy* (`/admin/releases/rollback-policy`, Admin only) is where your tenant decides whether a missing rollback plan, an unagreed one, or a missing/stale rollback rehearsal is a **warning** or a **blocker** in a release's readiness verdict — the same verdict *Gate Types* above feeds, so a connected pipeline reading `GET /api/v1/webhooks/release-ready` sees rollback gaps and gate gaps in one response (ch. 10). The panel's own copy states the scope of the two toggles plainly, and it is worth repeating here because it is easy to over-read: **this is advisory configuration only**. Neither setting stops a deployment, a release transition, or a rollback itself — a rollback can always be recorded (see the release detail page's *Rollback* tab → *Rollback History*) whether or not a plan exists at all, and nothing on this panel is enforced by this product.

Two toggles, **both off by default**:

- **Require a rollback plan.** On: a changing (or config-only) component with no *agreed* rollback plan becomes a **blocker** instead of a warning. Off: it's a warning only, same as today.
- **Require a current rehearsal.** On: a changing (or config-only) component whose system has no *current, passed* rehearsal — missing, stale, or its most recent attempt failed — becomes a **blocker** instead of a warning. Off: warning only.
- **Rehearsal validity period (days).** How long a passed rehearsal counts as current before it goes stale. Applies regardless of whether the toggle above is on — it decides the wording (*current* vs *stale*) either way, only the on/off toggle decides whether staleness escalates to a blocker.

One reversibility finding is **never** affected by either toggle: a component whose plan is marked *irreversible* always renders as a warning ("cannot be rolled back — roll forward only"), whatever the policy says. A component that genuinely cannot be rolled back is a fact about the component, not a governance gap a tenant can turn into a hard stop by flipping a switch.

**No deploy step is required.** The policy row is created lazily, with both flags off, the first time any endpoint reads or writes it for a tenant — the same lazy-seed pattern `environment_tier` and B2's naming policy use. A tenant that has never opened this tab still gets correct (off/off) behaviour from every read of the readiness verdict.

A worked example, verified end to end on this deployment: with both flags off, a release with an irreversible, unagreed plan and no rehearsal read as **3 advisory** findings — none of them blockers, and `ok: true`. Turning *Require a rollback plan* on and re-checking the same release moved only the *unagreed plan* finding into a **1 in the verdict** (blocker) section; the irreversible-reversibility and missing-rehearsal findings stayed advisory, and `ok` became `false` — but the release itself remained fully transitionable, bookable and deployable throughout, exactly as the panel's copy promises.

### Tips

Keep the change-kind list short — three to six is plenty. Use kind-scoped custom fields rather than free-text fields for any value you'll later filter or report on. Pre-define gates on release templates so each new release starts with the same readiness checklist, and override only when a release genuinely deviates.

### Booking types: protection levels and duration presets

*Administration → Bookings → Booking types* (`/admin/bookings/types`, Admin only) is where each booking type gets its lifecycle template — and, since Phase 7 B4, two more settings that every booking of that type inherits.

**Protection** — *Preemptible* or *Protected*. Every new booking request of this type starts at the type's level; an **Admin or Release Manager** can change it on an individual booking, and nobody else can (they see it, read-only, on the form and submit it unchanged).

> A protected reservation is **advice, not a lock**. Anyone can still book over it. What "protected" changes is who is named the winner when two bookings clash and project priority cannot separate them.

Precedence is worth being precise about, because it is the opposite way round from what most people assume: **project priority rank decides first**. Protection is consulted only in the cases where rank could not decide — the two projects have the same rank, one or both are unranked, or a booking has no resolvable project at all. A protected booking therefore does **not** outrank a higher-priority project's booking. Set ranks in *Bookings → Projects* (see *Contention priority* above); protection is the tie-breaker underneath them.

> If every booking type is set to Protected, the level stops discriminating and contention verdicts return to naming no winner — exactly as they did before protection levels existed. There is no quota on protected bookings; the role gate is the whole control.

**Default duration (minutes)** — optional. When set, choosing this booking type on the booking form fills in the end date: `240` for a half day, `20160` for a fortnight-long sprint, and so on. It never overwrites an end date the user has already typed. Whole days are added as *calendar* days, so a 14-day preset from 09:00 lands on 09:00 even across a daylight-saving change. Leave it blank for no preset — and note that once a preset is set, blanking the field again leaves the existing value in place; set a new positive number to change it.

Both settings apply to bookings made **from now on**. Existing bookings keep the level they were created with; changing a type's default never rewrites history.

### RAID Settings

*Administration → Releases → RAID settings* (`/admin/releases/raid`, Admin only) controls how your tenant scores the **Risks** and **Issues** in every release's RAID log (user guide ch. 8 — RAID log). Each tenant gets a default 5×5 configuration on creation; edit it to match your organisation's risk framework.

There are three things to configure:

- **Probability scale** and **Impact scale** — the ordered levels (1 = lowest). For each level you set a *label* (e.g. *Rare*, *Severe*) and a *colour*. These labels appear on the axes of the probability × impact heat-map.
- **RAG bands** — the severity ranges that map a score to red / amber / green. Severity is `probability × impact` (1–25 for a 5×5 grid). Each band has a *min*, *max*, and *colour*. The defaults are green `1–5`, amber `6–14`, red `15–25`. Keep the ranges contiguous and non-overlapping so every possible severity falls in exactly one band.

The **Live preview** on the right redraws the heat-map as you edit, colouring each cell by the band its severity falls into — so you can see the effect before saving. Click *Save changes* to persist (`PUT /api/v1/tenant/raid-config`).

Changing the scales or bands re-derives the RAG on existing risks and issues the next time they're read — it does **not** rewrite their stored probability/impact. Widening a band (or recolouring it) is safe to do at any time; the ref-codes and severities of existing items are unaffected.

## 9. Release templates

### Concept

A *release template* is a reusable skeleton for releases. It bundles a release type, an ordered list of phases, and a set of gates attached to those phases (or to the release as a whole). When your team always ships the same shape of release — a monthly product release, a hotfix, a quarterly platform upgrade — a template gives you consistency, faster setup, and a stable audit trail. Without templates every release is hand-built; with templates the structure is codified once and reused.

### Walkthrough: creating a template

1. Sign in as a tenant admin and navigate to *Administration → Releases → Templates* (`/admin/releases/templates`).
2. Click *New Template* to open the form at `/admin/releases/templates/new`.
3. Fill in the *Metadata* panel:
   - *Name* (required, up to 200 chars).
   - *Release Type* — one of `project`, `hotfix`, `patch`, `major`, `minor`. This becomes the type on every release built from the template.
   - *Description* (multi-line).
4. In the *Phases* panel, add one row per phase. Each phase has *Phase Name* (required), *Default Duration (days)* (used to back-compute phase dates from the release's target date — the last phase ends on the target date), and *Activities* (a comma-separated list of free-text labels). Use the up/down arrows to reorder; phase order is renumbered on save.
5. In the *Gates* panel, add one row per gate. Each gate skeleton holds *Gate Name*, *Attach to Phase* (a phase name from the list above, or "Release-level (no phase)"), *Acceptance Criteria* (free text), and *Gate Type* (§8's gate-type vocabulary — pick an active type, or leave it untyped). At instantiation each gate becomes a *ReleaseGate* with status `pending`; the acceptance-criteria text, if present, seeds a single criterion titled *Acceptance criteria*, and the chosen gate type carries across so the gate reads with the same failure behaviour and expected evidence it would have if typed by hand.
6. Click *Save*.

### Walkthrough: editing and deleting

To edit a template, open *Administration → Releases → Templates* and click the edit (pencil) icon on the row, or visit `/admin/releases/templates/:id` directly. The form is the same as create; saving bumps the template's internal version counter.

**Editing a template does *not* affect releases already created from it.** Each release gets its own copies of the *TestPhase* and *ReleaseGate* rows at instantiation — the template is a snapshot, not a live reference. Adjust the in-flight release directly if its gates or phases need to change.

To delete a template, click the red trash icon and confirm. Deletion is refused with a *409 Conflict* if any active release still references the template — release that work first.

### When templates help (and when they don't)

Templates earn their keep when releases follow a predictable cadence: a monthly product release with a fixed test/staging/prod phase shape, a regulated change pipeline where the same gates must always be evidenced, or multi-team coordination where everyone reaches for the same checklist. They are less useful for one-off hotfixes that don't follow your standard shape — for those, start from a blank release and add only the phases and gates that apply.

## 10. API keys and webhooks

### Concept

API keys are tenant-scoped, scope-restricted credentials that let external systems — typically your CI/CD pipelines — write to EnvManager. A key belongs to one tenant, carries one or more named scopes, and is presented in the `X-Api-Key` header. Keys are stored as a SHA-256 hash; the plaintext is shown **once**, on the screen that follows creation. EnvManager has no way to recover a lost plaintext — if you lose it, revoke and re-issue.

The only write endpoint covered by API keys is the deployment webhook, which registers a build, a deployment, and (on first call) an auto-generated change request in one round trip. The corresponding read views are described in user guide ch. 9. Two further endpoints are read-only advisory queries a pipeline can call before or after that write: the deployment scope's *can-deploy* preflight, and the release scope's *release-ready* gate check (see *Available scopes* below) — neither refuses anything; both hand back a structured verdict for the caller to act on.

### Walkthrough: creating an API key

API keys are managed by **Tenant Admins** at `/admin/api-keys` (*Administration → Integrations → API keys*).

1. Navigate to `/admin/api-keys`.
2. Click *New key* (top right).
3. Fill the *New API key* dialog:
   - *Name* — required, max 120 chars; pick something that identifies the consumer (for example `gitlab-ci-deploy`).
   - *Scopes* — at least one must be selected. Two are on offer: *CI/CD deployment webhook* (`webhooks:deployment`) and *Release gate readiness webhook* (`webhooks:release`). Grant only what a consumer needs — a deployment key is deliberately unable to read release-readiness detail (gate waiver reasons and approver names, evidence URLs, and — since Phase 9 C4 — rollback plan/rehearsal gaps and the reversibility rollup) unless it also carries `webhooks:release`.
   - *Expires at (optional)* — calendar field; leave blank for a non-expiring key.
4. Click *Create*. The dialog closes and the *API key created* dialog opens with a one-time read-only field containing the plaintext. Use the copy icon to drop it into your CI secrets store **now**.
5. Click *I've copied it*. The plaintext is gone — only its hash, plus the metadata you entered, remain on the *API keys* page.

> **Warning** If you dismiss the reveal screen without copying the key, your only recourse is to revoke the row and issue a new key. There is no "show key again" path.

### Walkthrough: revoking a key

On the *API keys* table, click the red trash icon in the *Actions* column and confirm. Revocation soft-deletes the row immediately: any subsequent request that presents the revoked key fails with `401 Unauthorized`, and the row disappears from the list. Revocation is permanent — re-issuing means creating a new key.

### Available scopes

Each handler declares the scope it requires; a key passes auth only if its scope set includes that scope and the key has not expired or been revoked.

| Scope | What it grants | Example use |
|-------|----------------|-------------|
| `webhooks:deployment` | `POST /api/v1/webhooks/deployment` — register a build and deployment, auto-create a `code_deployment` change request on first call. **Also** `GET /api/v1/webhooks/can-deploy` — preflight gate (see *Preflight: can-deploy* below). | GitLab/Jenkins/GitHub Actions: step that fires before deploying (preflight) and step that fires after a successful deploy (ingest). |
| `webhooks:release` | `GET /api/v1/webhooks/release-ready` — release readiness: typed gates *and*, since Phase 9 C4, rollback governance, in one response (see *Preflight: release-ready* below). Deliberately **not** granted by `webhooks:deployment`: reusing that scope would silently widen what every existing deployment key can read to include release-readiness detail (waiver reasons, approver names, evidence URLs, rollback plan/rehearsal gaps and the reversibility rollup). | A release pipeline step that asks "is this release ready?" before promoting a build, independent of any single environment's deploy preflight. |

Future phases will extend this list.

### Worked example: deployment webhook

**Endpoint** `POST /api/v1/webhooks/deployment`
**Required scope** `webhooks:deployment`
**Auth header** `X-Api-Key: <plaintext key>`

Each call carries a top-level deployment record plus a nested `build` block. Slugs (`system_slug`, `subsystem_slug`, `environment_slug`) are resolved against your tenant; mistyped slugs return `400 Bad Request`.

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/deployment \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $YOUR_KEY" \
  -d '{
    "event_id": "8b1f3c8e-2a17-4cf6-9b3d-4e9a55c1a201",
    "system_slug": "checkout",
    "subsystem_slug": "checkout-api",
    "environment_slug": "checkout-staging",
    "status": "success",
    "deployed_at": "2026-04-25T14:32:10Z",
    "deployer_name": "gitlab-ci",
    "build": {
      "git_sha": "f3a9c1d8b2e470c5a91e7a2e6b4d8f0c12a3b4d5",
      "git_branch": "main",
      "build_number": "1287",
      "commit_timestamp": "2026-04-25T14:18:02Z",
      "build_started_at": "2026-04-25T14:20:11Z",
      "build_finished_at": "2026-04-25T14:31:42Z",
      "jira_tickets": ["CHK-4421", "CHK-4438"],
      "pipeline_steps": [
        {
          "name": "deploy",
          "status": "success",
          "started_at": "2026-04-25T14:30:05Z",
          "finished_at": "2026-04-25T14:31:42Z"
        }
      ],
      "custom_fields": { "artifact_url": "https://artifacts/checkout-api/1287.tgz" }
    },
    "deployment_custom_fields": { "k8s_namespace": "checkout-staging" }
  }'
```

**Required build fields:** `git_sha`, `build_number`, `commit_timestamp`. **Optional build fields:** `git_branch`, `build_started_at`, `build_finished_at`, `jira_tickets`, `pipeline_steps`, `custom_fields`. Optional top-level fields: `release_id` (link to an existing release), `change_request_id` (skip auto-CR creation and link to one you already raised), `deployer_name`, `deployment_custom_fields`.

> **Why `build_number` is required:** it is part of the build's identity tuple (see *Idempotency* below), so it determines whether two webhook calls with the same `git_sha` represent the same build (one Build row, one artefact deployed twice) or distinct builds (two Build rows — same code, two pipeline runs). Send a stable monotonic value from your CI: GitLab `CI_PIPELINE_ID`, GitHub Actions `${{ github.run_id }}`, Jenkins `${BUILD_NUMBER}`. The same value also gives you a direct lookup back to the build logs in your CI system.

#### Idempotency

- **Builds** upsert on the tuple `(tenant_id, subsystem_id, git_sha, build_number)`. A replay with the same tuple updates the existing row — `pipeline_steps`, `jira_tickets`, `custom_fields`, `git_branch`, and the `build_started_at` / `build_finished_at` timestamps are **replaced wholesale** from the new payload, so always send the canonical view.
- **Deployments** dedupe on the tuple `(tenant_id, event_id)`. Re-sending the same `event_id` with the same `status` is a no-op (the response carries `replayed: true`). Re-sending the same `event_id` with a *new* status (e.g. `started` → `success`) is allowed only along the legal transition graph; an illegal transition returns `409 Conflict`.

Always generate a fresh UUID for `event_id` per logical deployment event, and reuse it on retries.

#### What the webhook creates on first call

When EnvManager has not seen the `event_id` before, a single call writes:

1. A **Build** row (or updates the matching one).
2. A **Deployment** row, linked to the build and the resolved environment.
3. An auto-generated `code_deployment` **Change Request** titled `Deploy <sha8> → <env-slug>`, raised by the API-key owner.

The auto CR is a placeholder so every deployment is auditable. To register the change manually first, send the existing `change_request_id` in the payload to skip auto-create; you can also swap the linked CR after the fact from the *Deployments* page (see user guide ch. 9).

> **Not yet available:** Jira ticket sync (resolving ticket IDs to live Jira issues, surfacing status / assignees inline) is a Phase 3 Sub-3 deferred item. The webhook stores `jira_tickets` as plain strings today; the Build detail renders them as deep links if a Jira base URL is configured on the system, but no two-way sync exists.

### Preflight: can-deploy

CI pipelines should call this **before** running their deploy stage to find out whether the target environment is currently reservable. It catches three things the post-deploy webhook can only record after the damage is done:

1. The environment is in *maintenance*, *inactive*, or *decommissioned* — block the deploy.
2. Another project holds an **exclusive booking** that covers right now — block the deploy unless the caller can prove they own the booking.
3. A change request with `has_outage = true` covers right now (and matches the target subsystem, if the CR is subsystem-scoped) — block the deploy.

It also surfaces non-blocking *warnings* (a non-exclusive booking is in progress; another deployment to the same env+subsystem is still in `pending` / `in_progress` state) so the CI log carries the context.

**Endpoint** `GET /api/v1/webhooks/can-deploy`
**Required scope** `webhooks:deployment`
**Auth header** `X-Api-Key: <plaintext key>`

Query parameters:

| Param | Required | Notes |
|-------|----------|-------|
| `environment_slug` | yes | Resolved against the tenant. `404` if unknown. |
| `subsystem_slug` | yes | Resolved against the tenant. `404` if unknown. |
| `release_id` | no | Claim token: "I'm deploying this release." Unlocks any exclusive booking whose `release_id` matches. |
| `booking_id` | no | Direct claim. Strongest unlock — proves the caller is the booking owner. |

> A `change_request_id` claim token was removed (2026-07-16): the booking model has no booking ↔ CR link, so it never unlocked anything. If CR-based claims are wanted later, add the FK first, then re-introduce the token and its response semantics.

```bash
curl "http://localhost:8000/api/v1/webhooks/can-deploy?\
environment_slug=uat-1&\
subsystem_slug=payments-api&\
release_id=42" \
  -H "X-Api-Key: $YOUR_KEY"
```

Response (clean — go ahead):

```json
{
  "ok": true,
  "environment_slug": "uat-1",
  "subsystem_slug": "payments-api",
  "checked_at": "2026-04-25T16:42:00Z",
  "blockers": [],
  "warnings": [],
  "claim_matched": null
}
```

Response (blocked by another team's exclusive booking):

```json
{
  "ok": false,
  "environment_slug": "uat-1",
  "subsystem_slug": "payments-api",
  "checked_at": "2026-04-25T16:42:00Z",
  "blockers": [
    {
      "type": "exclusive_booking",
      "ref_kind": "booking",
      "ref_id": 47,
      "title": "Q2 regression — checkout team",
      "until": "2026-04-26T18:00:00Z"
    }
  ],
  "warnings": [],
  "claim_matched": null
}
```

Response (allowed because the caller's `release_id` matches the booking):

```json
{
  "ok": true,
  "environment_slug": "uat-1",
  "subsystem_slug": "payments-api",
  "checked_at": "2026-04-25T16:42:00Z",
  "blockers": [],
  "warnings": [
    {
      "type": "deployment_in_progress",
      "ref_kind": "deployment",
      "ref_id": 199,
      "since": "2026-04-25T16:40:11Z"
    }
  ],
  "claim_matched": {"booking_id": 47, "matched_via": "release_id", "claim_value": 42}
}
```

`ok` is the only field a CI pipeline strictly needs to read; treat `false` as "do not deploy". The rest is for the log line a human will read when something gets blocked. HTTP status is `200` for any successful evaluation — the body carries the verdict; only auth (`401` / `403`) and slug-lookup (`404`) failures use HTTP status codes for signalling.

> **Advisory only.** Between the preflight call and the actual `POST /webhooks/deployment` there is a race window in which state can change (someone takes an exclusive booking, an outage CR is filed). The preflight is a fast read, not a lock. Plan for a small percentage of races where the post-deploy webhook records a violation that the preflight didn't anticipate. A short-lived deploy-reservation token is on the roadmap if races become a real problem.

#### What CI should pass

The minimum two are the slugs. If your pipeline knows what release or what booking it's deploying for — and it usually does, because release management is the reason the booking exists — pass those tokens too. The tokens are how you tell EnvManager "I'm the project that booked this environment." Without them, an exclusive booking on the env will block every CI call uniformly.

- **Release-managed deploy:** pass `release_id`. The booking on the target env that's tied to that release is auto-unlocked.
- **Direct claim:** pass `booking_id` if the CI job has been issued the booking's id (e.g. via a CI variable populated when the booking was approved). This is the strongest unlock and the right pattern when `release_id` doesn't apply.
- **Neither known:** the call still works, but exclusive bookings are unconditional blockers.

### Preflight: release-ready

A separate advisory query from *can-deploy* above: this asks "is this release ready — gates, and since Phase 9 C4, rollback governance — rather than "is this specific environment reservable right now?" A pipeline that promotes a build through a release can call it before doing so.

The same evaluator backs a UI element too — the release detail page's readiness banner calls `GET /api/v1/releases/{release_id}/readiness` (JWT-authenticated), which runs the identical rule set. **The two can never disagree**: both call the same `release_readiness_service.evaluate` function (renamed from `gate_readiness_service` when C4 folded rollback findings into it, rather than shipping a second endpoint); only the auth layer and the source of the tenant id (the caller's active tenant vs. the API key's own tenant) differ. Confirmed on this deployment: the same release read identical blocker/warning wording and the same `reversibility` value from both routes.

Since C4, `blockers`/`warnings` can also contain rollback findings — `rollback_plan_missing`, `rollback_plan_unagreed`, `rollback_irreversible`, `rollback_lossy`, `rehearsal_missing`, `rehearsal_stale` — each `ref_kind: "system"` rather than `"gate"`, with `gate_name`/`gate_type` both `null` (a rollback finding names a system, not a gate; the `detail` text always names the component by name). A top-level `reversibility` field — `"reversible"` / `"lossy"` / `"irreversible"` / `null` if there are no rollback plans on the release at all — reports the worst reversibility across the release's plans, independent of `ok`/`blockers`/`warnings`.

**Endpoint** `GET /api/v1/webhooks/release-ready`
**Required scope** `webhooks:release`
**Auth header** `X-Api-Key: <plaintext key>`

Query parameters:

| Param | Required | Notes |
|-------|----------|-------|
| `release_id` | yes | Resolved against the tenant the API key belongs to. `404` if unknown or in a different tenant. |

```bash
curl "http://localhost:8000/api/v1/webhooks/release-ready?release_id=42" \
  -H "X-Api-Key: $YOUR_KEY"
```

Response (a real capture from this deployment — a rollback plan exists but hasn't been agreed, one gate is untyped, and the component's plan is irreversible with no rehearsal recorded):

```json
{
  "ok": false,
  "release_id": 5,
  "checked_at": "2026-08-21T09:11:35.951514Z",
  "blockers": [
    {
      "type": "rollback_plan_unagreed",
      "ref_kind": "system",
      "ref_id": 1,
      "gate_name": null,
      "gate_type": null,
      "detail": "Mortgage's rollback plan has not been agreed."
    }
  ],
  "warnings": [
    {
      "type": "gate_untyped",
      "ref_kind": "gate",
      "ref_id": 4,
      "gate_name": "Scope Sign-off",
      "gate_type": null,
      "detail": "No gate type set, so no behaviour was declared."
    },
    {
      "type": "rollback_irreversible",
      "ref_kind": "system",
      "ref_id": 1,
      "gate_name": null,
      "gate_type": null,
      "detail": "Mortgage cannot be rolled back — roll forward only."
    },
    {
      "type": "rehearsal_missing",
      "ref_kind": "system",
      "ref_id": 1,
      "gate_name": null,
      "gate_type": null,
      "detail": "No successful rollback rehearsal recorded for Mortgage."
    }
  ],
  "reversibility": "irreversible"
}
```

This response was produced with the tenant's `require_rollback_plan` policy flag **on** — that's what turned the unagreed-plan finding into a blocker; with the flag at its default (off), the same release returns the same four findings but all as warnings, `blockers: []`, and `ok: true`. `rollback_irreversible` stays a warning either way (see *Rollback Policy*, ch. 8) — it never moves into `blockers`.

`ok` is the field a pipeline reads; treat `false` as "not ready — gates or rollback governance." As with *can-deploy*, **HTTP status is not the gate** — a not-ready release still returns `200 OK` with the verdict in the body. Only auth (`401` / `403`) and the release lookup (`404`) use HTTP status for signalling. EnvManager never refuses a deployment or a release transition on the strength of this response; it is advisory, and the caller decides what to do with `ok: false`.

### Rotation and revocation guidance

Treat keys as production secrets. Issue one per consumer so you can revoke a single integration without disrupting the rest, and audit the list quarterly — anything that has not authenticated in ninety days (check the *Last used* column) is a candidate for revocation. Set *Expires at* on short-lived projects so they self-retire.

## 11. Tenant settings

### Concept

Tenant settings hold tenant-scoped configuration that does not belong on any single entity and is not covered by per-entity custom fields. The page at `/admin/settings` exposes one free-form JSON object — the `settings` column on the tenant row — which downstream features can read at runtime. Treat it as a small, hand-curated key/value bag for per-tenant toggles, integration hints, or feature flags that the rest of the platform consults; nothing on this page changes billing, identity, or routing.

### What's editable vs read-only

The header card shows two read-only fields: *Name* (the display label that appears in the tenant switcher and headers) and *Slug* (the short identifier baked into login URLs and tenant-scoped paths). Both are deliberately locked from this page — slug changes would invalidate every existing bookmark and integration, and the name is set when the tenant is provisioned. To change either, a master admin must edit the tenant from `/admin/tenants/{tenantId}`. The only field you can edit here is the *Custom Settings (JSON)* document. The JSON document sits under *Advanced*, collapsed by default.

### Walkthrough: editing

1. Open `/admin/settings`.
2. Edit the JSON in the *Custom Settings (JSON)* textarea.
3. Click *Save Settings*.
4. A green *Settings saved successfully* banner confirms the write; the textarea then reflects the persisted value.

### Validation

The textarea is parsed client-side before the request leaves the browser. Anything that is not valid JSON triggers an inline *Invalid JSON* alert and the *Save Settings* call is suppressed. The payload must parse to a JSON object — top-level arrays, strings, or numbers are rejected. Server-side errors (auth, network) surface in the same alert region with the backend message.

## 12. Import/export

### Concept

Bulk-load entities into a tenant from an Excel workbook — useful when bootstrapping from an existing CMDB, spreadsheet inventory, or another EnvManager tenant. The page at `/import` covers two entity types: **environments** and **systems**, each uploaded as a `.xlsx` file. Two further importers — *Docker Compose* and *Terraform* — live on the system detail page and load **subsystems** into one specific system; see [ch. 5](#5-modelling-your-platform-systems-and-subsystems).

> **Not yet available:** there is no export endpoint or *Download Template* button (the button on the page is rendered but disabled with a *Templates coming soon* tooltip). To migrate data out, use the read-only API endpoints under `/api/v1/environments`, `/api/v1/systems`, etc., documented at `/docs`.

### Walkthrough: importing

1. Navigate to `/import`. The page shows two cards — *Import Environments* and *Import Systems* — with identical UX.
2. In the relevant card, click *Choose File* and pick a `.xlsx` workbook. The file picker only accepts the `.xlsx` extension; the first worksheet is used.
3. The selected filename appears next to the button. Click *Upload*.
4. The button shows *Uploading…* with a spinner while the request is in flight, then a result banner appears: *Created N, Skipped N* (green) or the same with *N error(s)* (amber). When errors are present, an error table lists each failed row with *Row*, *Field*, and *Message*.

### Excel column shapes

The first row of the worksheet is treated as headers. Header matching is case-insensitive; column order does not matter; unknown columns are ignored.

**Environments** — required: `Name`. Optional: `Type` (defaults to `imported`), `Description`.

```
| Name      | Type    | Description           |
| --------- | ------- | --------------------- |
| dev-eu-1  | dev     | Shared EU dev sandbox |
| qa-main   | qa      | Regression QA         |
```

**Systems** — required: `Name`. Optional: `Description`, `GitHub URL`.

```
| Name     | Description     | GitHub URL                          |
| -------- | --------------- | ----------------------------------- |
| Checkout | Order capture   | https://github.com/acme/checkout    |
| Payments | Card processing |                                     |
```

For the IaC importers (`POST /api/v1/import/docker-compose`, `POST /api/v1/import/terraform`), see the API reference at `/docs` for the multipart payload — both take a `system_id` form field plus the raw `docker-compose.yml` or `.tfstate` file.

### Upsert semantics

The matching key for both entity types is `Name`, scoped to the current tenant and excluding soft-deleted rows. Duplicates are **skipped** — never updated — and counted under *Skipped*. The page therefore behaves as an *insert-or-skip*; to amend existing rows, edit them via their normal CRUD pages. Each upload returns three counts: `created`, `skipped`, and a list of per-row errors.

## 13. Appendix: role permission matrix

### How to read this matrix

One row per logical resource area, not per endpoint — list / get / create / update / delete are collapsed into one row when their guard is uniform. Where they differ, the splits are called out as separate rows or footnotes. Cell values: `R` = read, `RW` = read + write, `—` = no access. Master-admin-only routes show `RW` only in the *Master Admin* column. Tenant Admin can do everything any other tenant role can do, by virtue of `require_role(X)` admitting Admin in addition to role X. API-key-protected endpoints are not user-role gated and are listed separately at the bottom.

### Convention check

- `require_role(X)` (`backend/app/core/security.py` lines 92–103) admits the user **if** they are master admin **or** their `role == "Admin"` **or** their `role == X`. So any cell granting `Release Manager` write access also grants Admin and Master Admin write access. The matrix shows the senior role implicitly for that reason.
- `require_tenant_admin()` is `require_role("Admin")` — Admin or Master Admin only.
- `require_master_admin()` admits master admins only; tenant Admin is rejected.
- `api_key_auth(scope)` ignores the user model entirely; only a valid `X-Api-Key` header with the required scope passes.

In practice today, **no** v1 endpoint uses `require_role(...)` with a non-Admin role — every guard is either *any authenticated user*, *Admin*, *Master Admin*, or *API key*. Per-role gradations (Release Manager vs Test Manager vs Developer vs Viewer) currently exist only in the frontend and in service-layer ownership rules (see footnotes). This is intentional: the role enum is provisioned for future use and frontend UX hints, but backend authorisation today is two-tier (Admin vs everyone) plus master admin and API keys.

### Matrix

| Resource | Master Admin | Admin | Release Manager | Test Manager | Developer | Viewer | Source |
|---|---|---|---|---|---|---|---|
| **Tenants** (list, create, get, update, disable) | RW | — | — | — | — | — | `api/v1/admin.py` |
| **Cross-tenant users** (list/create/update/role/deactivate/reactivate/reset-password under `/admin/tenants/.../users`) | RW | — | — | — | — | — | `api/v1/admin.py` |
| **Sign in as tenant** (impersonation) | RW | — | — | — | — | — | `api/v1/admin.py` |
| **Tenant users** (list, create, update, role, deactivate, reactivate under `/tenant/users`) | RW | RW | — | — | — | — | `api/v1/tenant_admin.py` |
| **Auth: register** (open — anonymous; only used to seed the first user) | RW | RW | RW | RW | RW | RW | `api/v1/auth.py` |
| **Auth: login, /me** (any authenticated identity) | RW | RW | RW | RW | RW | RW | `api/v1/auth.py` |
| **Tenant settings** (`/tenant/settings`) | RW | RW | — | — | — | — | `api/v1/tenant_admin.py` |
| **Custom field definitions** (`/tenant/fields`) | RW | RW | — | — | — | — | `api/v1/tenant_admin_fields.py` |
| **Scope-change rules** (change-kind catalogue, `/tenant/scope-change-rules`) | RW | RW | — | — | — | — | `api/v1/tenant_admin.py` |
| **Component type definitions** (host shapes) | RW | RW | — | — | — | — | `api/v1/component_types.py` |
| **Booking lifecycle templates** (`/tenant/lifecycle-templates`) | RW | RW | — | — | — | — | `api/v1/booking_lifecycle.py` |
| **Booking types** (`/tenant/booking-types`) | RW | RW | — | — | — | — | `api/v1/booking_lifecycle.py` |
| **Systems** (list, create, get, update, delete) — read | R | R | R | R | R | R | `api/v1/systems.py` |
| **Systems** — write (create / update / delete) | RW | RW | — | — | — | — | `api/v1/systems.py` |
| **Subsystems** (under `/systems/{id}/subsystems`) — read | R | R | R | R | R | R | `api/v1/systems.py` |
| **Subsystems** — write | RW | RW | — | — | — | — | `api/v1/systems.py` |
| **System dependencies** (depends-on edges) | RW (write) / R (read) | RW (write) / R (read) | R | R | R | R | `api/v1/dependencies.py` |
| **Environments** (list, get, schedule, verify, systems, subsystems, topology, versions) — read | R | R | R | R | R | R | `api/v1/environments.py` |
| **Environments** — write (create, update, delete, attach systems/subsystems/instances/versions) | RW | RW | — | — | — | — | `api/v1/environments.py` |
| **Environment instances** (`/environments/{id}/instances`) — read | R | R | R | R | R | R | `api/v1/environments.py` |
| **Environment instances** — write | RW | RW | — | — | — | — | `api/v1/environments.py` |
| **Environment dependencies** | RW (write) / R (read) | RW (write) / R (read) | R | R | R | R | `api/v1/dependencies.py` |
| **Hosts / infrastructure components** — read | R | R | R | R | R | R | `api/v1/infrastructure_components.py` |
| **Hosts / infrastructure components** — write (create, update, delete) | RW | RW | — | — | — | — | `api/v1/infrastructure_components.py` |
| **Topology view** (`/systems/{id}/topology`) | R | R | R | R | R | R | `api/v1/topology.py` |
| **Bookings** (list, get, create, transition, history, allowed-transitions, edit fields) | RW | RW | RW | RW | RW | RW | `api/v1/bookings.py` |
| **Bookings — delete (series or single occurrence)** | RW | RW | RW | own only | own only | own only | `api/v1/bookings.py` + `services/booking_service.py` (see footnote 1) |
| **Booking requests** (list, create, get, edit, attach env, preview-conflicts) | RW | RW | RW | RW | RW | RW | `api/v1/booking_requests.py` |
| **Booking conflicts** (list / acknowledge) | RW | RW | RW | RW | RW | RW | `api/v1/conflicts.py` |
| **Change requests** (list, create, get, update, transition, allowed-transitions, delete, preview-outage-conflicts) | RW | RW | RW | RW | RW | RW | `api/v1/change_requests.py` (see footnote 2) |
| **Releases** (list, create, get, update, delete, transition, lifecycle, history, calendar, timeline) | RW | RW | RW | RW | RW | RW | `api/v1/releases.py` (see footnote 3) |
| **Release phases / gates / criteria** (CRUD) | RW | RW | RW | RW | RW | RW | `api/v1/releases.py`, `api/v1/gate_criteria.py` |
| **Release systems / dependencies / events / changes / linked CRs / linked bookings** | RW | RW | RW | RW | RW | RW | `api/v1/releases.py` |
| **Release event types** (`/release-event-types`) | RW | RW | RW | RW | RW | RW | `api/v1/release_event_types.py` (see footnote 4) |
| **Release templates** (CRUD + instantiate) | RW | RW | RW | RW | RW | RW | `api/v1/release_templates.py` (see footnote 4) |
| **Builds** (list, get) — read-only over the API; written by webhook only | R | R | R | R | R | R | `api/v1/builds.py` |
| **Deployments** (list, get, link-change) — read-only over the API; written by webhook only | R | R | R | R | R | R | `api/v1/deployments.py` |
| **API keys** (list, create, revoke under `/api-keys`) | RW | RW | — | — | — | — | `api/v1/api_keys.py` |
| **Import** (Excel environments / systems, docker-compose, terraform) | RW | RW | — | — | — | — | `api/v1/import_routes.py` |
| **Enterprise memberships & roll-ups** | RW | RW | RW | RW | RW | RW | `api/v1/enterprise_memberships.py`, `api/v1/enterprise_rollup.py` (see footnote 5) |

### Webhook / API-key endpoints

These endpoints are **not** role-gated. They reject any request without a valid `X-Api-Key` header carrying the required scope, regardless of the caller's role.

| Endpoint | Required scope | Source |
|---|---|---|
| `POST /api/v1/webhooks/deployment` | `webhooks:deployment` | `api/v1/webhooks/deployment.py` |
| `GET /api/v1/webhooks/can-deploy` | `webhooks:deployment` | `api/v1/webhooks/can_deploy.py` |
| `GET /api/v1/webhooks/release-ready` | `webhooks:release` | `api/v1/webhooks/release_ready.py` |

API keys are issued and revoked per-tenant via the **API keys** row above (Admin only). See chapter 10 for scope details and the deployment webhook payload contract.

### Footnotes

1. **Bookings — delete.** The endpoint guard is `get_current_user` (any tenant user), but `services/booking_service.py` (`delete_occurrence`, `delete_series`, lines 411–438) adds an in-handler check: a non-privileged caller can only delete a booking they own. Privileged = master admin, `role == "Admin"`, or `role == "Release Manager"`. So Test Manager / Developer / Viewer can delete *their own* bookings only.
2. **Change requests.** No role guard on any endpoint — any authenticated tenant user can create, transition, and delete CRs. Transitions are filtered by the configured CR lifecycle template, not by role. If a tenant wants per-role gating on CR approval, it must be enforced in the lifecycle template, not by the API.
3. **Releases.** Same shape as change requests — no role guard at the endpoint or service layer. Any tenant user can create a release, drive transitions, and link/unlink change requests. Transitions are bounded by the release lifecycle template only.
4. **Release templates and event types.** Currently any authenticated tenant user can create, edit, and delete templates and event types — there is no Admin gate. Treat this as a known gap; in practice the frontend hides these admin-flavour pages from non-Admin users.
5. **Enterprise memberships and roll-ups.** All endpoints are guarded by `get_current_user` only. The `enterprise_id` arrives in the path, and tenant-scoping is enforced inside the service layer. There is no separate enterprise-admin role today.

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
