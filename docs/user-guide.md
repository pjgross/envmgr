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

*To be drafted in Task 20.*

## 7. Working with releases

*To be drafted in Task 21.*

## 8. Builds and deployments

*To be drafted in Task 22.*

## 9. Topology and dependency views

*To be drafted in Task 23.*

## 10. Tips and common workflows

*To be drafted in Task 24.*

## 11. Appendix: status lifecycles cheat sheet

*To be drafted in Task 25.*

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
