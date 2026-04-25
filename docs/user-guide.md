# EnvManager User Guide

## About this guide

This guide is for **Release Managers, Test Managers, Developers, and Viewers** using EnvManager day-to-day inside an already-provisioned tenant. It covers logging in, the dashboard, core concepts, browsing systems and environments, booking environments, raising change requests, working with releases, reading builds and deployments, topology and dependency views, and a small cookbook of common workflows. Platform setup tasks — provisioning tenants, managing users, modelling systems and environments, configuring change kinds, release templates, API keys, and import/export — live in [`admin-guide.md`](admin-guide.md).

## Table of contents

1. [Introduction](#1-introduction)
2. [Logging in and the dashboard](#2-logging-in-and-the-dashboard)
3. [Concepts in 5 minutes](#3-concepts-in-5-minutes)
4. [Browsing systems and environments](#4-browsing-systems-and-environments)
5. [Booking environments](#5-booking-environments)
6. [Raising change requests](#6-raising-change-requests)
7. [Working with releases](#7-working-with-releases)
8. [Builds and deployments](#8-builds-and-deployments)
9. [Topology and dependency views](#9-topology-and-dependency-views)
10. [Tips and common workflows](#10-tips-and-common-workflows)
11. [Appendix: status lifecycles cheat sheet](#11-appendix-status-lifecycles-cheat-sheet)

## 1. Introduction

EnvManager keeps track of the systems, environments, and release work going on across your tenant. From the UI you'll browse the systems and environments your team owns, book environments through a calendar, raise *change requests* and group them into *releases*, and watch a feed of CI builds and deployments as they land. The view is single-tenant: you only see data belonging to the tenant you're signed into.

**Who this guide is for.** Day-to-day end users — **Release Managers** planning and shipping releases, **Test Managers** booking environments for test cycles, **Developers** raising change requests and watching deployments, and **Viewers** reading status and history. Most actions in the UI are open to anyone signed into your tenant; senior responsibilities (managing other users, configuring tenant-level settings) sit with **Admin**. For anything setup-related, see [`admin-guide.md`](admin-guide.md).

**How to read this guide.** Three orientation pointers:

- For the big picture, read [ch. 3 (Concepts in 5 minutes)](#3-concepts-in-5-minutes) first — it diagrams how the entities fit together.
- For day-to-day workflows, [ch. 5 (Booking environments)](#5-booking-environments) and [ch. 7 (Working with releases)](#7-working-with-releases) are the meatiest chapters.
- For quick recipes, [ch. 10 (Tips and common workflows)](#10-tips-and-common-workflows) has cookbook-style scenarios.

If you're standing up a new tenant or modelling your platform, see [`admin-guide.md`](admin-guide.md). If you're working on EnvManager itself, see [`../CLAUDE.md`](../CLAUDE.md).

## 2. Logging in and the dashboard

### Logging in

EnvManager is multi-tenant: every login is scoped to one tenant. Your Admin will give you a tenant slug, a username, and a password.

1. Open the EnvManager URL given to you (typical dev: `http://localhost:5173`).
2. Enter the tenant slug into *Tenant* (e.g. `demo`).
3. Enter your username into *Username* and your password into *Password*.
4. Click *Login*.

On success you land on `/dashboard`. If you have access to more than one tenant, sign out and sign back in with the other tenant's slug — there is no in-app tenant switcher today. The bundled dev demo tenant uses slug `demo` with `admin` / `admin123`.

### The dashboard

The dashboard is a four-card landing pad above a welcome panel — a quick orientation, not a metrics view. Today only the *Environments* card reflects live data; the other three are wired to placeholder zeros until later phases populate them. Use the left navigation to actually drill in.

- *Environments* — *Total environments* visible to your tenant. (Live.)
- *Bookings* — *Active bookings*. *(Placeholder zero today.)*
- *Changes* — *Pending changes*. *(Placeholder zero today.)*
- *Releases* — *Active releases*. *(Placeholder zero today.)*

> **Not yet available:** the *Bookings*, *Changes*, and *Releases* cards are static zeros in the current build. Treat the dashboard as a landing page, not a status board — head straight to the relevant section in the left navigation for real numbers.

### The left navigation

The sidebar is the same for every authenticated user. *Bookings* and *Releases* are expandable groups; everything else is a single entry.

| Nav entry | Route | What's there | Covered in |
|-----------|-------|--------------|------------|
| *Dashboard* | `/dashboard` | Summary cards and welcome panel. | this chapter |
| *Systems* | `/systems` | System and subsystem catalogue. | [ch. 4](#4-browsing-systems-and-environments) |
| *Environments* | `/environments` | Environment inventory and detail. | [ch. 4](#4-browsing-systems-and-environments) |
| *Bookings → Calendar* | `/bookings/calendar` | Calendar view of reservations. | [ch. 5](#5-booking-environments) |
| *Bookings → List* | `/bookings/list` | Tabular view of reservations. | [ch. 5](#5-booking-environments) |
| *Builds* | `/builds` | CI build feed per subsystem. | [ch. 8](#8-builds-and-deployments) |
| *Change Requests* | `/change-requests` | Change-request inbox. | [ch. 6](#6-raising-change-requests) |
| *Deployments* | `/deployments` | Deployment feed per environment. | [ch. 8](#8-builds-and-deployments) |
| *Releases → List* | `/releases` | Release inventory. | [ch. 7](#7-working-with-releases) |
| *Releases → Calendar* | `/releases/calendar` | Release schedule by date. | [ch. 7](#7-working-with-releases) |
| *Releases → Timeline* | `/releases/timeline` | Release timeline view. | [ch. 7](#7-working-with-releases) |
| *Releases → Templates* | `/admin/release-templates` | Reusable release blueprints (read-only for non-Admins). | [`admin-guide.md` ch. 9](admin-guide.md#9-release-templates) |
| *Hosts* | `/infrastructure/hosts` | Infrastructure host inventory. | [`admin-guide.md` ch. 7](admin-guide.md#7-modelling-infrastructure-hosts) |
| *Import* | `/import` | Bulk Excel import (Admin write — readable nav for everyone). | [`admin-guide.md` ch. 12](admin-guide.md#12-importexport) |

Admin-only pages — user management and tenant configuration — appear under an extra *Admin* sidebar entry that's hidden unless your role is *Admin*.

### The top bar

The top bar carries the EnvManager logo (click to return to the dashboard) and your avatar on the right. Click the avatar to open the user menu:

- Header — your username, email, and role (master admins also see *Master Admin*).
- *Light mode* / *Dark mode* / *System theme* — click to cycle.
- *Logout* — ends the session and returns you to `/login`.

> **Not yet available:** there is no in-app *Change password* action or tenant switcher in the user menu today. Ask your Admin to reset your password if needed.

## 3. Concepts in 5 minutes

### Why eight concepts

Almost everything you do in EnvManager combines a handful of the same eight nouns. Once you can place each one — what it represents, who owns it, and how it links to the others — the rest of this guide will click into place quickly. This chapter is the orientation map; later chapters drill into individual workflows.

### The big picture diagram

Read this diagram from left to right. *Systems* on the left are owned by your platform team; *Releases* on the right are managed by Release Managers; *Environments* in the middle are where work actually happens.

```
   ┌─ business level ─┐                       ┌─ deployment runtime ─┐
   │     System       │  defines structure of │   Environment        │
   │       │          │ ────────────────────▶ │  (e.g. UAT-1)        │
   │       ▼          │                       │      │               │
   │   Subsystem      │ ──── ships build ────▶│      ▼               │
   └──────────────────┘                       │  Env. Instance       │
                                              │      ▲               │
   ┌─ planned work ───┐                       │      │               │
   │   Booking        │ ──── reserves ───────▶│   Environment        │
   │   Change Request │ ──── changes ────────▶│   Environment        │
   │   Release        │ ──── delivered to ───▶│   Environment        │
   └──────────────────┘                       │      ▲               │
                                              │      │               │
   ┌─ CI artefact ────┐                       │      │               │
   │   Build          │ ── deploys to ───────▶│   Deployment         │
   └──────────────────┘                       └──────────────────────┘
```

### The eight nouns

- **System** — A product or app at the business level (e.g. *Payments*). Systems are modelled by your Admin during onboarding; see [admin guide ch. 5](admin-guide.md#5-modelling-your-platform-systems-and-subsystems).
- **Subsystem** — One deployable unit of a system (e.g. *payments-api*, *payments-web*). Each subsystem maps 1:1 to a CI build target. Also covered in [admin guide ch. 5](admin-guide.md#5-modelling-your-platform-systems-and-subsystems).
- **Environment** — A logical instance of one or more systems (e.g. *UAT-1*, *PROD-EU*) — what humans book, change, and release into. Modelled by your Admin; see [admin guide ch. 6](admin-guide.md#6-modelling-environments). You'll browse them in [ch. 4](#4-browsing-systems-and-environments).
- **Booking** — A time-bounded reservation of an environment for a test cycle, dry run, or other use. Anyone in the tenant can raise one; see [ch. 5](#5-booking-environments).
- **Change Request** — A planned change against an environment, with a *kind* (e.g. *Code Deploy*, *Config Change*) and a status lifecycle. Covered in [ch. 6](#6-raising-change-requests).
- **Release** — A coordinated rollout that groups change requests, scope items, gates, and target environments into a single deliverable. Driven by Release Managers; see [ch. 7](#7-working-with-releases).
- **Build** — A CI artefact produced for a subsystem. Builds are read-only in EnvManager — they're pushed in by your CI system via webhook. See [ch. 8](#8-builds-and-deployments).
- **Deployment** — A specific build deployed to an environment instance. Also read-only and pushed in by CI; see [ch. 8](#8-builds-and-deployments).

### What you'll usually do

Day-to-day, you'll spend most of your time in five workflows: browse systems and environments to see what's where ([ch. 4](#4-browsing-systems-and-environments)); book an environment for a test cycle ([ch. 5](#5-booking-environments)); raise a change request when you're about to alter one ([ch. 6](#6-raising-change-requests)); plan, drive, and close out a release ([ch. 7](#7-working-with-releases)); and watch CI builds and deployments land in real time ([ch. 8](#8-builds-and-deployments)). For step-by-step recipes that combine these, see [ch. 10](#10-tips-and-common-workflows).

## 4. Browsing systems and environments

Most reading in EnvManager starts on one of two list pages: *System Catalog* or *Environments*. Both follow the same pattern — a DataGrid you can search, sort, and click into for a detail page. This chapter covers reading and finding things; for who creates and maintains them, see admin guide ch. 5–6.

### Browsing systems

Open `/systems` from the sidebar to land on the *System Catalog*. The header has a search box and a *New System* button; below it, a paginated DataGrid lists every system in your tenant.

Columns in source order:

- *Name* — system name, in bold.
- *Description* — the short description, or `—` if none.
- *GitHub* — a clickable *GitHub* chip when a repository URL is set; clicking opens the repo in a new tab without selecting the row.
- Any tenant custom fields, one column each.
- An unlabelled actions column with *Edit* and *Delete* icons (visible to users with edit permission).

The header search box filters rows by *Name* (case-insensitive substring). Click any column header to sort, and use the column-menu on header hover to hide columns; your column visibility is remembered per-user in your browser. Click a row to open `/systems/:id`.

### Inside a system

The system detail page is tab-based. Tabs in source order:

- *Overview* — system metadata (name, description, GitHub repository link) and any tenant custom fields.
- *SubSystems* — table of the system's deployable units, showing *Name*, *Category* (the component type chip), *Technology*, and *Description*.
- *Dependencies* — system-to-system dependencies, with direction (incoming / outgoing), the related system, dependency type, and one-way / two-way.
- *Component Deps* — subsystem-to-subsystem dependencies merged across every subsystem of this system, including protocol, port, and any documented endpoints.
- *Topology* — an interactive graph rendering of subsystems and the edges between them; click an edge to see its details.

Maintenance of subsystems and dependencies (creation, edits, imports from `docker-compose.yml` or Terraform state) is described in admin guide ch. 5.

### Browsing environments

Open `/environments` from the sidebar. The header has search and *New Environment*; immediately below, a row of status filter chips scopes the grid to *All*, *Active*, *Inactive*, *Maintenance*, or *Decommissioned*.

Columns in source order:

- *Name* — environment name, in bold.
- *Type* — the free-text type your tenant uses (for example `staging`, `uat`, `prod`).
- *Status* — a coloured chip: green for *active*, yellow for *maintenance*, grey for *inactive*, red for *decommissioned*.
- *Created* — localised creation date.
- Any tenant custom fields, one column each.
- Actions column with *Edit* and *Delete* icons.

Search filters by *Name*; status chips are AND-combined with the search. Sort and column visibility work as on the System Catalog. Click a row to open `/environments/:id`.

### Inside an environment

The environment detail page is also tab-based. Tabs in source order:

- *Overview* — metadata (name, description, type, status chip), tenant custom fields, created and updated timestamps, and a *Verify Environment* button that runs a dependency check against the environment's system contents (see admin guide ch. 6).
- *Systems* — the systems attached to this environment; rows for systems that are required by a dependency but not yet attached are listed in greyed-out form.
- *Components* — one row per subsystem instance, with the *Real / Mock* toggle chip, *Category*, *Type*, *Latest Version*, a *Hosts* dialog button, and a *Record Version* dialog launched from the page header.
- *Topology* — an interactive graph for this environment's components and their dependencies.
- *Schedule* — bookings, change requests, and (Phase 4) deployments overlaid on a calendar.
- *Deployments* — a deployment feed for this environment, showing recent and in-flight deployments (Phase 4).

In day-to-day use, the *Schedule* and *Deployments* tabs are where most reading happens — they answer "is this environment free?" and "what's the latest build out there?" without needing to leave the page.

### How custom fields appear

Tenant-defined custom fields show up as additional columns in the System and Environment DataGrids and as additional sections on the *Overview* tab of each detail page. If your team relies on custom fields, those columns are often the most useful sort keys for finding what you need.

## 5. Booking environments

### Concept

A booking reserves one or more environments for a time window. It records the project, booking type, notes, exclusive-use flag, optional delegates, and tenant custom fields. A single *booking request* can span **several environments at once** — useful when a test campaign needs an app environment plus a database — and each environment gets its own per-env *booking* row that travels through the lifecycle independently.

### Status lifecycle

The default template has six states. *Draft* is where every new booking starts; *Submitted* puts it in front of an approver; *Approved* means the slot is yours; *Rejected* and *Closed* are terminal; *Extension Request* is the side-track for asking for more time on an *Approved* booking. The state keys below match the template exactly.

```
            ┌─────────┐
            │  draft  │  ◄──── (Return for Revision)
            └────┬────┘                     ▲
                 │ Submit                    │
                 ▼                           │
          ┌────────────┐                     │
          │ submitted  │ ────────────────────┘
          └─┬────────┬─┘
   Approve  │        │  Reject
            ▼        ▼
       ┌────────┐  ┌──────────┐
       │approved│  │ rejected │  (terminal)
       └─┬────┬─┘  └──────────┘
         │    │ Close
         │    ▼
         │  ┌────────┐
         │  │ closed │  (terminal)
         │  └────────┘
         │
         │ Request Extension
         ▼
  ┌──────────────────────┐  Approve Extension
  │ extension_requested  │ ─────────────────► approved
  └──────────┬───────────┘
             │ Reject Extension
             ▼
          rejected
```

Tenant Admins can replace this template — see admin guide ch. 8 — so transitions may differ in your tenant.

### Calendar vs list view

- **Calendar** at `/bookings/calendar` — a FullCalendar grid showing every booking as a coloured block. Use *Filter by Environment* to narrow it down, click a block to open the side drawer with details and transition buttons, or click *+ New Booking* in the toolbar. Best for "when can I get UAT?" planning.
- **List** at `/bookings/list` — DataGrid columns in source order: *Project*, *Environment*, *Booked By*, *Start*, *End*, *Type*, *Status*, *Conflicts*, and a kebab actions column. Status chips filter to *All / Draft / Submitted / Approved / Rejected / Ext. Requested / Closed*. Tenant custom fields appear as hideable columns. Best for filtering by team or status.

### Walkthrough: creating a booking

1. Open `/bookings/calendar` and click *+ New Booking* in the top toolbar (or open `/bookings/list` and click *+ New Booking* in the top-right).
2. Fill the *New Booking Request* dialog:
   - **Environments** — multi-select; pick one or several (Phase 2.5 multi-env).
   - **Project Name** — required; this is the user-facing label that appears on the calendar.
   - **Booking Type** — required; picks the lifecycle template (defaults to *Standard Booking*).
   - **Start Date & Time** / **End Date & Time** — required.
   - **Context Tag** — *None / Deployment / Regression*. Auto-derived later if you link the booking to a release.
   - **Exclusive use requested** — toggle on if you need the environment to yourself for that window.
   - **Delegates (optional)** — other tenant users who can manage the booking on your behalf.
   - **Notes** and any **custom fields** the booking type exposes in *draft*.
3. Click *Create Booking*.

The booking is saved in *draft* — the dialog flags this with an info banner: *"Booking will be saved as Draft. Submit when ready for approval."* Conflict detection runs as you type (debounced); shared overlaps warn but allow creation, exclusive overlaps raise a 409 and force you to pick a new window.

### Conflict detection

Conflicts surface live in the new-booking dialog as you set the dates, and on the booking detail in the *Conflicts* panel after creation. A conflict is any other non-rejected booking on the **same environment** whose window overlaps yours. If either side requested exclusive use, the conflict is **blocking** (creation fails with HTTP 409). If both sides are shared, the conflict is a **warning** — the booking is created and gets an unacknowledged-conflicts indicator until the booker (or a delegate) acknowledges it. On a blocking conflict, pick a different window, drop the exclusive flag if shared use will do, or ask the existing booker to release their slot.

### Walkthrough: requesting an extension

If your booking is in *approved*, you can ask for more time:
1. Open the booking detail at `/bookings/:id`.
2. In the *Environments* panel, click *Request Extension* on the env you want extended.
3. The state moves to *extension_requested*; edit the *End Date* via *Edit dates* and add a justification in *Notes*.
4. An Admin or Release Manager clicks *Approve Extension* (returns to *approved* with the new end-date) or *Reject Extension* (sends to *rejected*).

Any tenant role can request the extension; only Admin / Release Manager can approve or reject.

### Walkthrough: cancelling

There is no dedicated *Cancel* button — cancellation is achieved by **deleting** the booking (or the whole recurring series) from the detail page. Per the service-layer rule (admin guide ch. 13, footnote 1):

- **Test Manager / Developer / Viewer** can delete only bookings they own.
- **Admin / Release Manager / Master Admin** can delete any booking.

Deletion is a soft delete — the slot is freed immediately and the booking disappears from the calendar and list, but the row is retained for audit. *Rejected* and *Closed* are the lifecycle's two terminal exits, reached via the transition buttons (Admin / Release Manager only).

If your test cycle is part of a release, see [ch. 7 (Working with releases)](#7-working-with-releases) — releases can have linked bookings.

## 6. Raising change requests

### Concept

A **change request** (CR) describes a planned change against one or more environments and/or hosts. It carries a *type* — *Configuration*, *Infrastructure*, or *Code Deployment* — a *status* driven by a tenant lifecycle template, a scheduled window, an optional outage flag with its own window, and links to the entities it affects. When you target a host, affected environments are *derived* automatically through the host-to-subsystem-to-environment join and shown as derived chips on the detail page.

CRs auto-generated by the deployment webhook (type *Code Deployment*) appear in the same list — recorded so the deployment timeline and DORA metrics have something to anchor to. You can raise a human-authored CR alongside one (see admin guide ch. 8 on the change-kind catalogue).

### Status lifecycle

CR status is driven by the lifecycle template chosen at creation. Every new tenant is seeded with three: *Simple Approval* (the default human flow), *Emergency* (no approval gate), and *Code Deployment* (system-only, used by the webhook). Your tenant Admin may have added or replaced these — see admin guide ch. 8.

The *Simple Approval* default looks like this:

```
        ┌─────────┐
        │  draft  │ ◄────────────── (Return for Revision)
        └────┬────┘                          ▲
             │ Submit                         │
             ▼                                │
       ┌───────────┐                          │
       │ submitted │ ─────────────────────────┘
       └─┬───────┬─┘
 Approve │       │ Reject
         ▼       ▼
   ┌──────────┐ ┌──────────┐
   │ approved │ │ rejected │  (terminal)
   └─────┬────┘ └──────────┘
         │ Mark Completed
         ▼
   ┌───────────┐
   │ completed │  (terminal)
   └───────────┘
```

*Emergency* collapses this to *draft → in_progress → completed* for urgent work that bypasses approval.

### List view

Navigate to `/change-requests` to see every CR in your tenant. DataGrid columns in source order: *ID*, *Title*, *Type*, *Status* (coloured chip), *Environments* (derived envs flagged in blue), *Hosts*, *Outage*, and *Scheduled*. Three filters above the grid: *Status*, *Environment*, and *Host*. There's no built-in *my open CRs* filter today — the useful end-user pivots are *Status: Submitted* to see what's awaiting approval, or *Environment: <yours>* before booking against it. Click any row to open `/change-requests/:id`.

### Walkthrough: creating a CR

1. From `/change-requests`, click *New Change Request* in the top-right.
2. Fill the *New Change Request* dialog:
   - **Title** — required.
   - **Change Type** — *Configuration* / *Infrastructure* / *Code Deployment*.
   - **Lifecycle** — picks the state machine; defaults to the tenant's default template.
   - **Environments** and **Hosts** — multi-select autocompletes (at least one of either is required). Hosts surface a readonly *Host impact* panel showing the derived environments.
   - **Subsystem** *(optional, only when exactly one environment is selected)* — narrows the change to one subsystem.
   - **Scheduled Start** / **Scheduled End** — required; render an overlay Gantt of bookings on the affected envs.
   - **This change causes an outage** — toggle to expose **Outage Start** / **Outage End**; runs a live booking-conflict preview.
   - **Custom fields** — any tenant-configured CR fields (admin guide ch. 8).
   - **Description** — multi-line free text.
3. Click *Create Change Request*.

The CR enters the lifecycle's initial state — *draft* on both default templates — and you're navigated to the detail page.

### Walkthrough: transitioning a CR

The *Actions* panel on the detail page renders one button per transition allowed for your current state and role. On *Simple Approval*: *Submit* (*draft* → *submitted*), *Approve* / *Reject* / *Return for Revision* from *submitted*, *Mark Completed* from *approved*. Any tenant user can create or transition a CR — there is no API-level role guard (admin guide ch. 13 footnote 2). Role gating, where it exists, comes from the lifecycle template's per-transition `allowed_roles`; on *Simple Approval*, *Approve* / *Reject* / *Return for Revision* are limited to *Admin* and *Release Manager*. If a button isn't shown, your role isn't allowed for it on this template.

### Linking environments and hosts

Environments and hosts are linked at creation via the multi-select fields above, and edited later from the *Edit* button on the detail page (which reopens the same dialog). The links power the audit trail — CRs are queryable by environment or host on the list filters and on the environment schedule view — and let bookings and deployments report which CR they relate to.

## 7. Working with releases

### Concept

A **release** groups change requests, scope items, gates, environments, and (post-deployment) deployments under a single shippable unit. It has a *type* — one of *project*, *hotfix*, *patch*, *major*, or *minor* — a *kind* (*project* or *enterprise*), a target date, and a status that flows through a tenant-configurable lifecycle. The type also picks the release lifecycle template (admin guide ch. 9). A release with kind *project* can join exactly one *enterprise* release — the bundle — letting several teams' work ship together as a coordinated quarterly drop.

```
     Release "2026-Q2"
       ├── Scope items (granular work units, each with a change_kind)
       ├── Linked Requests (change requests pulled into this release)
       ├── Environments (target envs for this release)
       ├── Test Phases (time-boxed test cycles with start/end dates)
       │      └── Gates (pass/fail checkpoints with absolute due dates)
       └── Deployments (read-only, populated post-rollout by CI)

     Optional: ──── joins ────▶ Enterprise Release "FY26 Q2 Bundle"
```

### Status lifecycle

The default *Major* lifecycle for project releases has ten states. The happy path is *draft* → *submitted* → *approved* → *in_progress* → *ready_for_release* → *completed*, with branches off to *completed_with_issues*, *backed_out*, *rejected*, or *cancelled*. *Minor* skips *submitted*; *Emergency* skips both *submitted* and *ready_for_release*. State keys below match the *Major* template exactly.

```
     ┌─────┐  Submit   ┌──────────┐  Approve   ┌──────────┐
     │draft│ ────────▶ │submitted │ ─────────▶ │ approved │
     └──┬──┘           └─────┬────┘            └─────┬────┘
        │                    │ Reject                │ Start Release
        │                    ▼                       ▼
        │              ┌──────────┐            ┌──────────────┐
        │              │ rejected │            │ in_progress  │
        │              └──────────┘            └──────┬───────┘
        │                                             │ Mark Ready
        │ Cancel                                      ▼
        ▼                                ┌────────────────────┐
  ┌──────────┐                           │ ready_for_release  │
  │cancelled │                           └──┬─────────┬────┬──┘
  └──────────┘                  Complete │       │ │ Back Out
                                          ▼       ▼ ▼
                              ┌──────────┐ ┌───────────────────────┐ ┌────────────┐
                              │completed │ │completed_with_issues  │ │ backed_out │
                              └──────────┘ └───────────────────────┘ └────────────┘
```

Tenant Admins can replace this template — see admin guide ch. 9 — so transitions may differ in your tenant. *Enterprise* releases run their own lifecycle (*draft* → *planning* → *admission_open* → *admission_closed* → *integration_testing* → *uat* → *staging* → *cab* → *deploying* → *deployed*).

### The three views

- **List** at `/releases` — DataGrid columns in source order: *ID*, *Name*, *Type*, *Kind*, *Status*, *Target Date*, *Phases*, *Scope*, *Scope Changes*, *Blockers*, *Overdue*, *Created*. Filters: *Status*, *Type*, and a *Kind* toggle (*All / Projects / Enterprise*). A *Backlog* tab lists scope items not yet pulled into any release. Best for "what's in flight?"
- **Calendar** at `/releases/calendar` — FullCalendar month view of release phases, colour-coded by release status. Click a phase block to open the parent release.
- **Timeline** at `/releases/timeline` — Gantt: rows are releases, bars are phases, orange diamonds mark *target_date*, status-coloured diamonds mark gate due dates. Best for "what's competing for the same window?"

### Walkthrough: creating a release

1. From `/releases`, click *New Release* (top right).
2. Fill the *New Release* dialog:
   - **Kind** — *Project* or *Enterprise*. Project releases belong to a single team; enterprise releases roll up multiple project releases.
   - **Type** — required; the dropdown lists every release lifecycle template defined for this tenant (e.g. *Major*, *Minor*, *Emergency*). Type determines the lifecycle. The tenant default is pre-selected.
   - **Name** — required.
   - **Description**, **Target Date**, and any **custom fields** the lifecycle exposes in *draft*.
3. Click *Create Release*. You land on the new release's detail page.

The release enters *draft*. If your tenant has configured a release template (admin guide ch. 9) for the chosen type, picking it on creation pre-populates phases and gates so you don't have to build them by hand.

### Inside a release

The detail page at `/releases/:id` is tab-based:

- **Main** — release metadata, target/actual dates, type, kind, current state, and the buttons that drive the lifecycle. Header icons open the *Status history* and *Event log* drawers.
- **Gates & Test Phases** — read-only phase Gantt at the top, editable phases table below, and the gates list with criteria.
- **Environments** — target environments for this release.
- **Linked Requests** — change requests pulled into this release (see ch. 6).
- **Scope** — granular scope items, each with a *change_kind* (story / defect / task / spike) that tenant rules use to decide whether a late edit counts as a *scope change* (admin guide ch. 8).
- **Enterprise** — for project releases, shows the current bundle (if any) and a history of past membership requests. For enterprise releases, the page swaps to a layout that lets you triage admission requests.
- **Deployments** — populated by the CI deployment webhook (see [ch. 8](#8-builds-and-deployments)). Read-only.

Honest API note: every release endpoint is guarded by *get_current_user* only — no `require_role`. Role checks come from the lifecycle template's `allowed_roles` per transition, so whoever configures the template (your Tenant Admin) decides who can advance the release. See admin guide ch. 13, footnote 3.

### Walkthrough: transitioning a release

1. Open the release detail and stay on the *Main* tab.
2. The available buttons depend on the current state and your role's place in the template's `allowed_roles`. For *Major*, *Admin* / *Release Manager* drive almost every transition; *Developer* can only *Submit for Approval* from *draft*.
3. Click the next-state button (e.g. *Submit for Approval*, *Approve*, *Start Release*, *Mark Ready*, *Complete*, *Back Out*).
4. Add an optional note; the transition is recorded in *Status history* and emits an outbox event.

Gate completion is **not** an enforced precondition for advancing — you can mark a release *completed* with pending gates. Gates and their *overdue* badges are UX cues, not a backend block. For hard blocking, configure required fields in the lifecycle template (admin guide ch. 9).

### Gates and scope

- **Gates** live on the *Gates & Test Phases* tab. Click *Add Gate* to create one with a name and an absolute *due_date* (a timestamp, not a relative offset). Add criteria from the expanded row; each criterion has its own due date that drives the gate's *overdue* badge. To move a gate off *pending*, click *Decide* and pick *passed*, *failed*, or *overridden*. Gates render as status-coloured diamonds on the timeline.
- **Scope items** live on the *Scope* tab. Click *Add Item* to set a *title*, *change_kind* (story / defect / task / spike), and any release custom fields. Late edits — adding or removing a scope item after the release leaves *draft* — count as a *scope change* per tenant rules (admin guide ch. 8) and surface on the *Scope Changes* column on the list view.

### Enterprise membership

A project release joins one enterprise release at a time (the live FK is `parent_release_id`); the membership table records every admission request and decision as an append-only audit log. The *Enterprise* tab on a project release shows the current bundle (if any) plus a *History* list of past requests — *pending_request*, *accepted*, *rejected*, *withdrawn*, or *removed*. Why bother: enterprise releases give you cross-project rollups and one shared schedule when several teams' work must ship together.

### Status history

The header's history icon opens the *Status history* drawer — a read-only audit trail of every state transition: who, when, from-state, to-state, and notes. Useful for compliance reviews and post-go-live retros. The *Event log* icon opens the freeform *Release events* drawer (reschedule reasons, scope-change notes, stakeholder updates, post-go-live incidents) — typed entries you record manually.

Once a release is in flight, see [ch. 8 (Builds and deployments)](#8-builds-and-deployments) for what your CI populates.

## 8. Builds and deployments

### Concept

Builds and deployments are **read-only artefacts** in the UI. You never create them by hand — your CI system POSTs to the deployment webhook (admin guide ch. 10), and EnvManager turns one event into three things: a Build (per Subsystem + git_sha, idempotently upserted), a Deployment (per `event_id`), and an auto-created `code_deployment` CR so every deployment has a CR-of-record. Builds belong to a Subsystem; Deployments belong to an Environment Instance. Together they answer "what's deployed where, and from which commit?"

```
   CI runs --> POST /api/v1/webhooks/deployment --> EnvManager
                                                      |
                                                      |--> upsert Build (per subsystem + git_sha)
                                                      |--> create Deployment (per event_id)
                                                      `--> auto-create code_deployment ChangeRequest
```

### Browsing builds

Navigate to `/builds`. DataGrid columns, in order:

- *SubSystem* — the subsystem the build belongs to.
- *Branch* — git branch the commit was on.
- *SHA* — first eight characters of the commit SHA.
- *Build #* — the CI build number, if your pipeline supplied one.
- *Release* — linked release name, if the webhook included a `release_id`.
- *Commit at* — commit timestamp.
- *Latest step* — name and status of the last pipeline step recorded.

Filters above the grid: *SubSystem* (substring match on the subsystem name), *Branch* (server-side filter), *From* / *To* (date range on the commit timestamp). Click any row to open the build detail.

### Inside a build

The build detail page (`/builds/:id`) opens with a header showing *SubSystem*, *Branch*, *SHA* (first 12 chars), *Build #* (if any), linked *Release* (if any), and the *Committed* timestamp.

Below the header you get four sections, rendered only if there's content:

- *Pipeline steps* — one row per step: a status chip, the step name, and the duration computed from `started_at`/`finished_at`.
- *Jira tickets* — chips for any ticket keys the webhook attached.
- *Custom fields* — the per-tenant build custom fields (admin guide ch. 5).
- *Deployments* — every deployment that came from this build, with environment, status chip, and timestamp; click to pivot to the deployment detail.

### Browsing deployments

Navigate to `/deployments`. DataGrid columns, in order:

- *Environment* — the environment instance the deployment landed in.
- *Build* — the eight-character SHA of the deployed commit.
- *Status* — coloured status chip (see lifecycle below).
- *Deployer* — `deployer_name` from the webhook (CI user or pipeline name).
- *Deployed at* — timestamp the webhook reported as `deployed_at`.
- *Release* — linked release name, if any.
- *Change request* — title of the linked CR (auto or human-authored).

Filters above the grid: *Environment* and *Release* (client-side substring match), and *Status* (server-side dropdown — *Any*, *pending*, *in_progress*, *success*, *failed*, *rolled_back*). Click any row to open the deployment detail.

### Inside a deployment

The deployment detail page (`/deployments/:id`) opens with a header combining the environment name and the build identifier, plus a status chip:

- Subline: *Environment*, linked *Release* (if any), *Deployed* timestamp, and *by* deployer name.
- *Build* card — SubSystem, SHA (12 chars), branch, build number; *View full build* jumps to `/builds/:id`.
- *Change request* card — the CR title (click to open it) and its current status chip.
- *Custom fields* — per-tenant deployment custom fields, if any are set.

### Deployment status lifecycle

Five states, all driven by webhook calls from CI:

- *pending* — deployment accepted but not started.
- *in_progress* — CI has begun rolling out.
- *success* — completed cleanly. The linked CR auto-transitions to *deployed* and the environment's running version is updated.
- *failed* — rollout broke. The linked CR auto-transitions to *failed*.
- *rolled_back* — only reachable from *success* or *failed*.

```
 pending --> in_progress --+--> success --+--> rolled_back
                            |              |
                            `--> failed ---'
```

Webhook re-deliveries are idempotent (matched by `event_id`) and any forward transition that violates the diagram returns 409.

### The auto-created CR and how to swap it

When a deployment lands, EnvManager files a `Code Deployment` change request automatically — there's always a CR-of-record, even if your team hadn't raised one. After the fact you can swap that auto-CR for a human-authored CR (e.g. a real RFC filed in advance for audit purposes).

Walkthrough:

1. Open the deployment detail page.
2. In the *Change request* card, click *Link a different change request*. The button is enabled only while the deployment is attached to the auto-created `Code Deployment` CR; after one swap it greys out.
3. In the dialog, search and select an existing CR; confirm to relink.

This calls `POST /api/v1/deployments/{id}/link-change` and isn't role-gated server-side — any authenticated tenant user can do it. If your policy reserves audit-relinking for Admins, enforce that through process.

If a deployment failed, see [ch. 10 (Tips and common workflows)](#10-tips-and-common-workflows) for the recipe.

## 9. Topology and dependency views

### Where to find topology views

The topology view is embedded in two places: the *Topology* tab on a System detail page (`/systems/:id`) and on an Environment detail page (`/environments/:id`). There's no top-level topology page — you always view a topology in the context of one entity.

### System topology

Subsystems are grouped inside their parent system. The current system gets a blue dashed border; external systems pulled in by cross-system dependencies sit alongside it with a grey border. Subsystems render as rounded boxes with a coloured chip for the *component type* — `database` (blue), `cache` (amber), `message_queue` (purple), `web_service` (green), `api_gateway` (teal), `worker` (orange), `frontend` (indigo), `other` (grey). The *technology* tag, if set, appears below the chip.

Edges are component dependencies. The arrow head points from consumer to provider — an edge from A to B means "A depends on B". Two-way dependencies show arrow heads at both ends. Edge labels show the dependency's *label* (or its *type* as a fallback).

Click any edge to open the *Link Details* pane: from/to subsystems, dependency type, direction, *protocol* and *port* if recorded, and documented endpoints (HTTP method + path). Click the edge again to dismiss. Nodes are not clickable and not draggable.

### Environment topology

The environment view groups per-environment subsystem instances under their parent system. Systems belonging to the environment use the blue dashed border; systems pulled in only as dependency targets are labelled `— not in environment` with a grey border.

Mocked subsystems render with a dashed grey border and a `mocked` caption. Outside dependencies — links that cross the environment boundary — are drawn alongside in-environment edges. Click an edge to inspect details in the same side pane.

The *Verify environment* action on the *Overview* tab populates the mocked / not-in-environment annotations.

### Reading the diagram

- **Pan**: drag the background.
- **Zoom**: scroll wheel or the zoom controls in the bottom-left.
- **Minimap**: bottom-right; keeps you oriented when zoomed in.
- **Click an edge**: open the *Link Details* pane.
- Layout is auto-computed; you cannot reposition nodes manually.

> **Not yet available:** node-click handlers — clicking a system or subsystem node doesn't navigate anywhere. Use the breadcrumbs or the *Overview* tab to jump to related entities.

### When topology helps

- **Impact analysis**: if subsystem X is going down, inbound edges show every subsystem (and parent system) that depends on it.
- **Onboarding**: a new team member can see the platform shape at a glance.

## 10. Tips and common workflows

These recipes chain steps from earlier chapters — refer back to chapters 4–9 for the underlying screens. Each scenario assumes you have the relevant role or template permissions; if a button isn't visible, your tenant's lifecycle template may have role-restricted that step.

### Recipe 1: I'm releasing a hotfix

1. From `/releases`, click *New Release* (top right).
2. In the *New Release* dialog: *Kind* = *Project*, *Type* = *Emergency* (the *Emergency* template skips *submitted* and *ready_for_release* for fast-track), *Name* = e.g. `2026-04-25-hotfix-payments-401`, *Target Date* = today. Click *Create Release*.
3. The release lands in *draft* on the detail page.
4. On the *Scope* tab, click *Add Item* and describe the fix. Pick a *change_kind* (typically *defect*) — see admin guide ch. 8 for what counts as a scope change once you leave *draft*.
5. On the *Environments* tab, attach the production environment.
6. *(Optional)* On the *Linked Requests* tab, link a pre-existing CR. If you skip this, the deployment webhook will auto-create a `code_deployment` CR.
7. Back on *Main*, click the *Emergency* template's first transition (typically *Start Release*) — *draft → in_progress*.
8. Trigger your CI pipeline. CI calls `POST /api/v1/webhooks/deployment` (admin guide ch. 10). EnvManager upserts the Build, creates the Deployment, and (if you skipped step 6) auto-creates the CR. The Deployment appears on the release's *Deployments* tab.
9. On *Gates & Test Phases*, mark gates *passed* via *Decide*, then transition through to *completed* on *Main*. Gates are UX cues, not enforced preconditions (see ch. 7).

### Recipe 2: I need to book UAT for a 2-week test cycle

1. Open `/bookings/calendar` and click *New Booking* in the top toolbar (or open `/bookings/list` and click *+ New Booking* in the top-right).
2. Fill the *New Booking Request* dialog:
   - *Environments* — multi-select; pick UAT (add other envs if your test campaign needs them).
   - *Project Name* — your project or test cycle name; this is what shows on the calendar.
   - *Booking Type* — picks the lifecycle template; defaults to *Standard Booking*.
   - *Start Date & Time* / *End Date & Time* — your two-week window.
   - *Context Tag* — *None* / *Deployment* / *Regression*.
   - *Exclusive use requested* — toggle on if you need the env locked to your team for the window.
   - *Delegates (optional)* — other tenant users who can act on the booking on your behalf.
   - *Notes* and any custom fields the booking type exposes.
3. Click *Create Booking*. The booking is saved in *draft* (the dialog banner confirms this).
4. Open the booking detail (click the calendar block, or the row on `/bookings/list`) and click *Submit* — state moves to *submitted*, awaiting an Admin or Release Manager.
5. If the live conflict preview flagged an exclusive overlap, creation will have failed with HTTP 409 — pick a different window, drop the exclusive flag, or coordinate with the existing booker.
6. If your work overruns once approved, click *Request Extension* on the per-env panel, edit the end-date via *Edit dates*, add a justification, and wait for an Admin or Release Manager to *Approve Extension* (see ch. 5).

### Recipe 3: My deployment failed — where do I look?

1. Open `/deployments`. Set *Status* = `failed` and *Environment* = the affected env (substring match). Click the *Deployed at* column header to sort descending.
2. Click into the failing deployment.
3. Read the header: *Environment*, linked *Release*, *Deployed* timestamp, *by* deployer name, and the status chip — *failed* (or *rolled_back* if a recovery rollout followed).
4. In the *Build* card, click *View full build* to jump to `/builds/:id`. The *Pipeline steps* section shows one row per step with status and duration — the first non-success step is your starting point.
5. Pivot back to the deployment and click into the *Change request* card. If it's the auto-created `Code Deployment` CR, the title anchors what was being deployed; the CR's status will have auto-transitioned to *failed* per the deployment lifecycle (ch. 8).
6. If CI re-runs the deployment, the new event upserts the same Build (matched on subsystem + git_sha) and creates a fresh Deployment row keyed on `event_id`. The failed row stays in history.
7. To swap the auto-CR for a human-authored RFC, click *Link a different change request* on the *Change request* card. The button greys out after one swap.

### Recipe 4: I want to see what changed in production last week

Two paths — pick whichever is more direct.

**Path A: deployments feed.** Best when you want a clean roll-up of just deployments.

1. Open `/deployments`. Set *Environment* = your production env and *Status* = `success`.
2. Click the *Deployed at* column header to sort descending. Scroll down to a week ago — there is no built-in date-range filter today, so the sort is the way to scope.
3. Each row's *Build* column shows the eight-character SHA of the deployed commit; click into the deployment to pivot to the build (commit SHA, branch, and any Jira tickets the webhook attached) via *View full build*.
4. The *Change request* column links to the CR-of-record for that deployment — the auto-`Code Deployment` CR by default, or a human-authored CR if someone relinked it. The *Release* column tells you whether the deployment was part of a coordinated release or an ad-hoc roll-out.

**Path B: per-environment schedule.** Best when you want bookings, change requests, and deployments together for context.

1. Open `/environments` and click your production env.
2. Switch to the *Schedule* tab — bookings, change requests, and deployments are overlaid on one calendar (Phase 4 Sub-2).
3. Page back to the last 7 days. Each deployment block links to its detail page; bookings and CRs in the same window give you the why-context (was someone testing? was a config change running?).
4. The *Deployments* tab on the same env page is the unfiltered feed for that environment if you'd rather scroll a list than read a calendar.

## 11. Appendix: status lifecycles cheat sheet

*To be drafted in Task 25.*

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
