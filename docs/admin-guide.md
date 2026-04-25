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
| *Import* | `/import` | Bulk Excel import. | ch. 12 |
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

### Concept

API keys are tenant-scoped, scope-restricted credentials that let external systems — typically your CI/CD pipelines — write to EnvManager. A key belongs to one tenant, carries one or more named scopes, and is presented in the `X-Api-Key` header. Keys are stored as a SHA-256 hash; the plaintext is shown **once**, on the screen that follows creation. EnvManager has no way to recover a lost plaintext — if you lose it, revoke and re-issue.

Today the only write endpoint covered by API keys is the deployment webhook, which registers a build, a deployment, and (on first call) an auto-generated change request in one round trip. The corresponding read views are described in user guide ch. 8.

### Walkthrough: creating an API key

API keys are managed by **Tenant Admins** at `/tenant/api-keys` (left nav: *API keys*).

1. Navigate to `/tenant/api-keys`.
2. Click *New key* (top right).
3. Fill the *New API key* dialog:
   - *Name* — required, max 120 chars; pick something that identifies the consumer (for example `gitlab-ci-deploy`).
   - *Scopes* — at least one must be selected. Today the only scope on offer is *CI/CD deployment webhook* (`webhooks:deployment`).
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
| `webhooks:deployment` | `POST /api/v1/webhooks/deployment` — register a build and deployment, auto-create a `code_deployment` change request on first call. | GitLab/Jenkins/GitHub Actions step that fires after a successful deploy stage. |

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

The auto CR is a placeholder so every deployment is auditable. To register the change manually first, send the existing `change_request_id` in the payload to skip auto-create; you can also swap the linked CR after the fact from the *Deployments* page (see user guide ch. 8).

> **Not yet available:** Jira ticket sync (resolving ticket IDs to live Jira issues, surfacing status / assignees inline) is a Phase 3 Sub-3 deferred item. The webhook stores `jira_tickets` as plain strings today; the Build detail renders them as deep links if a Jira base URL is configured on the system, but no two-way sync exists.

### Rotation and revocation guidance

Treat keys as production secrets. Issue one per consumer so you can revoke a single integration without disrupting the rest, and audit the list quarterly — anything that has not authenticated in ninety days (check the *Last used* column) is a candidate for revocation. Set *Expires at* on short-lived projects so they self-retire.

## 11. Tenant settings

### Concept

Tenant settings hold tenant-scoped configuration that does not belong on any single entity and is not covered by per-entity custom fields. The page at `/tenant/settings` exposes one free-form JSON object — the `settings` column on the tenant row — which downstream features can read at runtime. Treat it as a small, hand-curated key/value bag for per-tenant toggles, integration hints, or feature flags that the rest of the platform consults; nothing on this page changes billing, identity, or routing.

### What's editable vs read-only

The header card shows two read-only fields: *Name* (the display label that appears in the tenant switcher and headers) and *Slug* (the short identifier baked into login URLs and tenant-scoped paths). Both are deliberately locked from this page — slug changes would invalidate every existing bookmark and integration, and the name is set when the tenant is provisioned. To change either, a master admin must edit the tenant from `/admin/tenants/{tenantId}`. The only field you can edit here is the *Custom Settings (JSON)* document.

### Walkthrough: editing

1. Open `/tenant/settings`.
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

API keys are issued and revoked per-tenant via the **API keys** row above (Admin only). See chapter 10 for scope details and the deployment webhook payload contract.

### Footnotes

1. **Bookings — delete.** The endpoint guard is `get_current_user` (any tenant user), but `services/booking_service.py` (`delete_occurrence`, `delete_series`, lines 411–438) adds an in-handler check: a non-privileged caller can only delete a booking they own. Privileged = master admin, `role == "Admin"`, or `role == "Release Manager"`. So Test Manager / Developer / Viewer can delete *their own* bookings only.
2. **Change requests.** No role guard on any endpoint — any authenticated tenant user can create, transition, and delete CRs. Transitions are filtered by the configured CR lifecycle template, not by role. If a tenant wants per-role gating on CR approval, it must be enforced in the lifecycle template, not by the API.
3. **Releases.** Same shape as change requests — no role guard at the endpoint or service layer. Any tenant user can create a release, drive transitions, and link/unlink change requests. Transitions are bounded by the release lifecycle template only.
4. **Release templates and event types.** Currently any authenticated tenant user can create, edit, and delete templates and event types — there is no Admin gate. Treat this as a known gap; in practice the frontend hides these admin-flavour pages from non-Admin users.
5. **Enterprise memberships and roll-ups.** All endpoints are guarded by `get_current_user` only. The `enterprise_id` arrives in the path, and tenant-scoping is enforced inside the service layer. There is no separate enterprise-admin role today.

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
