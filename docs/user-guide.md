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

*To be drafted in Task 17.*

## 4. Browsing systems and environments

*To be drafted in Task 18.*

## 5. Booking environments

*To be drafted in Task 19.*

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
