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

The *Sign In As* action lives on each row of the `/admin/tenants` table. Clicking it issues an impersonation token: your session adopts the target tenant's `active_tenant_id`, so every page renders exactly as that tenant's Admin would see it. Use it for support, smoke-testing a freshly provisioned tenant, or troubleshooting a reported issue. While impersonating, a sticky warning banner reads "Viewing as *<tenant name>*. Exit to return to your account." Click *Exit* in that banner to drop the impersonation token and return to your master-admin context.

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

Once your Master Admin has seeded you as the first *Admin*, open the login page and enter three things: your **tenant slug** (e.g. `acme-corp`), your **username**, and the **password** the Master Admin set. Submit. The app drops you on `/dashboard` — every authenticated session lands there. Change your password immediately via the user menu (top-right avatar); the seeded password was chosen by someone who is not you.

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
- *Changes* — *Pending changes* awaiting approval or implementation (`user-guide.md` ch. 6).
- *Releases* — *Active releases* currently in flight (`user-guide.md` ch. 7).

> **Not yet available:** the *Bookings*, *Changes*, and *Releases* cards are wired to placeholder zeros in the current build; only *Environments* reflects live data. Treat the dashboard as a landing page, not a metrics view.

### The left navigation

The sidebar is the same for every authenticated user, with one extra entry — *Admin* — visible only to users with role *Admin*. Two entries (*Bookings*, *Releases*) are expandable groups.

| Nav entry | Route | What's there | Covered in |
|-----------|-------|--------------|------------|
| *Dashboard* | `/dashboard` | Summary cards and welcome panel. | this chapter |
| *Systems* | `/systems` | System and subsystem catalogue. | ch. 5 |
| *Environments* | `/environments` | Environment inventory and detail. | ch. 6 |
| *Bookings → Calendar* | `/bookings/calendar` | Calendar view of reservations. | `user-guide.md` ch. 5 |
| *Bookings → List* | `/bookings/list` | Tabular view of reservations. | `user-guide.md` ch. 5 |
| *Builds* | `/builds` | CI build feed per subsystem. | `user-guide.md` ch. 8 |
| *Change Requests* | `/change-requests` | Change-request inbox. | `user-guide.md` ch. 6 |
| *Deployments* | `/deployments` | Deployment feed per environment. | `user-guide.md` ch. 8 |
| *Releases → List* | `/releases` | Release inventory. | `user-guide.md` ch. 7 |
| *Releases → Calendar* | `/releases/calendar` | Release schedule by date. | `user-guide.md` ch. 7 |
| *Releases → Timeline* | `/releases/timeline` | Release timeline view. | `user-guide.md` ch. 7 |
| *Releases → Templates* | `/admin/release-templates` | Reusable release blueprints. | ch. 9 |
| *Hosts* | `/infrastructure/hosts` | Infrastructure host inventory. | ch. 7 |
| *Import* | `/import` | Bulk CSV/JSON import. | ch. 12 |
| *Admin* (Admin only) | `/admin/config/booking` | Tenant config: change kinds, gates, scope rules, API keys. | ch. 8, ch. 10, ch. 11 |

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

1. Navigate to `/tenant/users`.
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

### Password resets

> **Not yet available:** there is no tenant-admin password-reset flow on `/tenant/users`. If a user has lost their password, ask your Master Admin to call `POST /api/v1/admin/tenants/{tenant_id}/users/{user_id}/reset-password` with a fresh `new_password`, then share the new value out of band.

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
   - **Environment Type** (required) — free text, e.g. *staging*, *uat*, *dev*, *prod*. Use a small consistent vocabulary across your tenant; this drives filtering.
   - **Status** — defaults to *active*.
   - **Custom Fields** — any tenant-defined fields for the *environment* entity (configured in *Tenant Settings → Entity Config*; see [ch. 11](#11-tenant-settings)).
3. Click *Create*. The environment is created with no systems attached.
4. Open the new row to land on the detail page, then move to the *Systems* tab to attach systems.

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

### Walkthrough: decommissioning safely

Before flipping an environment to *decommissioned*:

1. Cancel or close out any active bookings that overlap with today (*Schedule* tab on the environment, or `/bookings`).
2. Close any in-flight change requests that target this environment.
3. Detach instances or note that hosts will keep their last attachment record.
4. Edit the environment and set *Status* to **decommissioned**.

The status change is **reversible** — the environment is still soft-deleted only when you click *Delete* on the list page. Use *decommissioned* to hide an environment from working views without losing history; use *Delete* (which sets `deleted_at`) only when you're sure the audit trail no longer needs to surface it.

### Reading the environment topology

The *Topology* tab on the environment detail page renders a force-directed graph (built on React Flow). Each *system* is a labelled group box; subsystems sit inside their parent system. Solid-bordered nodes are real instances, dashed-grey nodes are mocked. Subsystems pulled in by an outside dependency appear in a separate group labelled *— not in environment*. Edges are component dependencies; arrows show direction (two-way edges have arrowheads on both ends).

You can pan, zoom, and use the minimap. **Click an edge** to open a side panel with the dependency's type, label, protocol/port, and any documented endpoints. Nodes are not draggable — the layout is computed automatically.

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

A **gate** is a checkpoint on a single release that must be cleared before the release advances — *UAT sign-off*, *Security review*, *CAB approval*. Each gate carries a required `due_date` (an absolute timestamp, not a relative offset) and a list of *criteria*. Gates block release transitions until cleared, and the `due_date` renders as a status-coloured diamond on the release timeline.

### Walkthrough: managing change kinds

The change-kind admin UI lives at `/admin/scope-change-rules` — page component `TenantScopeChangeRules`. Every new tenant is seeded with four kinds:

| Kind | Counts as scope change |
|------|------------------------|
| `story` | yes |
| `defect` | no |
| `task` | no |
| `spike` | no |

To add a kind:

1. Navigate to `/admin/scope-change-rules`.
2. In the *Add a new change kind* panel, type a slug into the *Kind* field. Allowed: lowercase letters, digits, `_` and `-`, up to 20 characters. Examples: `chore`, `epic`, `migration`.
3. Click *Add*. The new kind appears in the rules table with *Counts as scope change* off.
4. Toggle the switch on if items of this kind should contribute to the rolled-up scope-change metric.
5. Click *Save* to persist all pending changes in one batch.

> **Not yet available:** the UI has no rename, archive, or delete control — once a kind exists, the only switch you can flip is *Counts as scope change*. To remove or relabel a kind today, edit `scope_change_kind_rule` directly; the admin API at `PUT /api/v1/tenant/scope-change-rules` only upserts. A full CRUD page is on the backlog.

### Walkthrough: configuring gates

There is **no tenant-level gate library**. Gates exist in two places only:

- **On a release template** — the template's `gates` JSON array carries a skeleton that is materialised into real gate rows when a release is created from the template. Edit the skeleton from the *Release Templates* admin page — see ch. 9.
- **On a release** — the *Plan* tab on any release has a *Gates* section. Click *Add Gate*, fill *Name* (e.g. *UAT Sign-off*) and *Due date* (a calendar picker — required, stored as an absolute UTC timestamp), then *Create*. Each gate can carry one or more *criteria*, each assignable to a user and toggleable as *open* or *done*.

A release cannot advance while any gate is pending or has open criteria past `due_date`. Gate dates render on the release Gantt as coloured diamonds — slate pending, green passed, red failed, amber overridden — so missed milestones jump out.

### Tips

Keep the change-kind list short — three to six is plenty. Use kind-scoped custom fields rather than free-text fields for any value you'll later filter or report on. Pre-define gates on release templates so each new release starts with the same readiness checklist, and override only when a release genuinely deviates.

## 9. Release templates

### Concept

A *release template* is a reusable skeleton for releases. It bundles a release type, an ordered list of phases, and a set of gates attached to those phases (or to the release as a whole). When your team always ships the same shape of release — a monthly product release, a hotfix, a quarterly platform upgrade — a template gives you consistency, faster setup, and a stable audit trail. Without templates every release is hand-built; with templates the structure is codified once and reused.

### Walkthrough: creating a template

1. Sign in as a tenant admin and navigate to *Admin → Release Templates* (`/admin/release-templates`).
2. Click *New Template* to open the form at `/admin/release-templates/new`.
3. Fill in the *Metadata* panel:
   - *Name* (required, up to 200 chars).
   - *Release Type* — one of `project`, `hotfix`, `patch`, `major`, `minor`. This becomes the type on every release built from the template.
   - *Description* (multi-line).
4. In the *Phases* panel, add one row per phase. Each phase has *Phase Name* (required), *Default Duration (days)* (used to back-compute phase dates from the release's target date — the last phase ends on the target date), and *Activities* (a comma-separated list of free-text labels). Use the up/down arrows to reorder; phase order is renumbered on save.
5. In the *Gates* panel, add one row per gate. Each gate skeleton holds *Gate Name*, *Attach to Phase* (a phase name from the list above, or "Release-level (no phase)"), and *Acceptance Criteria* (free text). At instantiation each gate becomes a *ReleaseGate* with status `pending`; the acceptance-criteria text, if present, seeds a single criterion titled *Acceptance criteria*.
6. Click *Save*.

### Walkthrough: editing and deleting

To edit a template, open *Admin → Release Templates* and click the edit (pencil) icon on the row, or visit `/admin/release-templates/:id` directly. The form is the same as create; saving bumps the template's internal version counter.

**Editing a template does *not* affect releases already created from it.** Each release gets its own copies of the *TestPhase* and *ReleaseGate* rows at instantiation — the template is a snapshot, not a live reference. Adjust the in-flight release directly if its gates or phases need to change.

To delete a template, click the red trash icon and confirm. Deletion is refused with a *409 Conflict* if any active release still references the template — release that work first.

### When templates help (and when they don't)

Templates earn their keep when releases follow a predictable cadence: a monthly product release with a fixed test/staging/prod phase shape, a regulated change pipeline where the same gates must always be evidenced, or multi-team coordination where everyone reaches for the same checklist. They are less useful for one-off hotfixes that don't follow your standard shape — for those, start from a blank release and add only the phases and gates that apply.

## 10. API keys and webhooks

*To be drafted in Task 11.*

## 11. Tenant settings

*To be drafted in Task 12.*

## 12. Import/export

*To be drafted in Task 13.*

## 13. Appendix: role permission matrix

*To be drafted in Task 14.*

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
