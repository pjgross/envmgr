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

*To be drafted in Task 5.*

## 5. Modelling your platform: systems and subsystems

*To be drafted in Task 6.*

## 6. Modelling environments

*To be drafted in Task 7.*

## 7. Modelling infrastructure (hosts)

*To be drafted in Task 8.*

## 8. Configuring change kinds and gates

*To be drafted in Task 9.*

## 9. Release templates

*To be drafted in Task 10.*

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
