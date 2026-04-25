# User Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `docs/admin-guide.md` and `docs/user-guide.md` that document the post-Phase-4 EnvManager product for tenant admins and end users, matching the spec at `docs/superpowers/specs/2026-04-25-user-manual-design.md`.

**Architecture:** Two self-contained markdown files written chapter-by-chapter. Each chapter is verified against the actual frontend source before drafting, so the manual matches reality. ASCII diagrams only, no screenshots. Cross-links between guides via relative-path anchors.

**Tech Stack:** Markdown (CommonMark, GitHub-flavoured for tables and code fences). No tooling. Verification is via `Read` against `frontend/src/pages/`, `frontend/src/App.tsx`, and the relevant backend services.

---

## Notes for the implementer

- **This is a documentation plan, not code.** The TDD "failing test → implementation" pattern does not apply. The repeating pattern is **verify → draft → commit**.
- **Verification is not optional.** Every chapter that names a route, component, button, field, or lifecycle state must be verified against the current frontend before it's drafted. The acceptance criterion "no fabricated controls" is the most important quality gate.
- **Chapters are independent.** Drafting a chapter does not depend on any earlier chapter's prose, only on the spec and the source. Tasks 2–14 (admin guide) and 15–25 (user guide) can be reordered if needed; the scaffolding (Task 1) and the wrap-up (Task 26) are positional.
- **Branch:** Work continues on `docs/user-manual-spec` (already cut from `main`, contains the spec commit `34386e4`).
- **Commit cadence:** One commit per chapter. Conventional-commits style: `docs(admin-guide): ch.5 systems and subsystems`, `docs(user-guide): ch.7 releases`.
- **DataGrid columns and field lists:** When a chapter describes a list view's columns, read the page component and list the columns as they appear, in order. Don't paraphrase. Same for form fields.
- **Lifecycle states:** Every status diagram must come from the backend service or model file, not from memory. The four lifecycles (booking, change request, release, deployment) are each defined in `backend/app/services/`.
- **"Not yet available" callouts:** Use the exact prefix `> **Not yet available:**` so they're greppable.
- **No screenshots, no inline images.** ASCII/markdown diagrams only.

---

## File Structure

Files this plan creates or modifies:

- **Create:** `docs/admin-guide.md` — 13-chapter admin/operator manual.
- **Create:** `docs/user-guide.md` — 11-chapter end-user manual.
- **Modify:** `CLAUDE.md` — add pointers to the two new guides in the header banner block.

Files this plan reads (verification sources):

- `frontend/src/App.tsx` — route table.
- `frontend/src/pages/**/*.tsx` — page components for every route described.
- `frontend/src/components/**/*.tsx` — shared widgets referenced by name.
- `backend/app/services/*.py` — lifecycle source of truth (booking, change request, release, deployment).
- `backend/app/db/models/*.py` — entity field lists.
- `backend/app/api/v1/**/*.py` — endpoint paths and required scopes.
- `docs/requirements.md`, `docs/plan.md`, `docs/phases/phase-{1,2,3,4}.md` — vocabulary and intent.

---

## Task 1: Scaffold both manual files

**Files:**
- Create: `docs/admin-guide.md`
- Create: `docs/user-guide.md`

- [ ] **Step 1: Read the spec to confirm chapter list and tone conventions**

Read: `docs/superpowers/specs/2026-04-25-user-manual-design.md`. Confirm chapter counts (13 admin, 11 user) and the tone/conventions block.

- [ ] **Step 2: Write `docs/admin-guide.md` scaffold**

The scaffold contains: a one-paragraph "About this guide" intro, a table of contents linking to each `## N. Chapter Title` heading, and 13 empty chapter headings each with a one-line italic placeholder `*To be drafted in Task N.*` that includes the task number. Role badges go on the chapter heading (e.g. `## 2. Provisioning a new tenant *(Master Admin only)*`). The scaffold also includes the conventions footer:

```markdown
---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
```

- [ ] **Step 3: Write `docs/user-guide.md` scaffold**

Same shape as admin-guide. 11 chapters. Same conventions footer.

- [ ] **Step 4: Commit**

```bash
git add docs/admin-guide.md docs/user-guide.md
git commit -m "docs(manual): scaffold admin guide + user guide with chapter stubs"
```

---

## Task 2: Admin guide ch. 1 — Introduction

**Files:**
- Modify: `docs/admin-guide.md` (replace ch. 1 placeholder)

- [ ] **Step 1: Verify role list against backend**

Read: `backend/app/core/security.py` for the `Role` enum. Confirm the five roles are: Admin, Release Manager, Test Manager, Developer, Viewer. Confirm the Master Admin flag is a separate `is_master_admin` boolean on the User model — read `backend/app/db/models/user.py` to verify.

- [ ] **Step 2: Draft chapter 1**

Content:
- One-paragraph product description: EnvManager is a multi-tenant test environment management platform covering inventory, booking, change management, releases, and CI/CD deployment tracking.
- Who this guide is for: Master Admins (briefly — only ch. 2) and Tenant Admins (the bulk).
- Role model: a 6-row table of role × one-line description (Master Admin, Admin, Release Manager, Test Manager, Developer, Viewer).
- "How this guide relates to other docs": user-guide.md (link), CLAUDE.md (developer-facing), `docs/prod architecture.md` (architecture).
- Length target: ~250 words. No subsections.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.1 introduction"
```

---

## Task 3: Admin guide ch. 2 — Provisioning a new tenant *(Master Admin only)*

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify the master-admin tenant flow**

Read: `frontend/src/pages/admin/TenantList.tsx` and `frontend/src/pages/admin/TenantDetail.tsx`. List the controls a master admin sees: *New Tenant* button, fields on the create form (name, slug), the *Sign in as tenant* action, the *Disable* action, the per-tenant user-creation form (username, email, password, role, is_master_admin checkbox).

Confirm the master-admin login by reading: `backend/scripts/seed_master_admin.py` for the `masteradmin` / `masteradmin123` credentials and `system` tenant.

- [ ] **Step 2: Draft chapter 2**

Content:
- Concept: master admin scope (cross-tenant), how it differs from a tenant Admin.
- Logging in as `masteradmin` (with a one-line warning to change the seeded password in production).
- Walkthrough: navigate to `/admin/tenants` → click *New Tenant* → enter name/slug → submit. List the exact fields.
- Walkthrough: open the new tenant's detail page → create the first Admin user (list the exact form fields and the role drop-down). Note that the first user must be Admin.
- Walkthrough: *Sign in as tenant* — what it does (impersonation; restores via the user menu), when to use it.
- Walkthrough: disabling/re-enabling a tenant.
- ASCII diagram of the master-admin journey:
  `masteradmin login → /admin/tenants → New Tenant → /admin/tenants/:id → New User (Admin) → Sign in as tenant → tenant Admin starts ch. 3`
- Length target: ~600 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.2 provisioning a new tenant"
```

---

## Task 4: Admin guide ch. 3 — Onboarding your tenant

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify dashboard and nav**

Read: `frontend/src/pages/Dashboard.tsx` for the actual cards shown. Read the layout component (likely `frontend/src/components/Layout/*.tsx` or `frontend/src/App.tsx`) for the left-nav entries visible to an Admin role.

- [ ] **Step 2: Draft chapter 3**

Content:
- The mental model diagram (use ASCII):
  ```
  Systems ──┬── Subsystems ──── Builds ──┐
            │                            ├── Deployments ── Environments ── Bookings
            └── (deps) ─────────── Environments ──┤                          Change Requests
                                                  └── Instances on Hosts     Releases
  ```
  Then walk through the diagram in 3–4 sentences.
- Dashboard tour: list the cards shown (env count, active bookings, pending changes — verify exact wording).
- The left nav: list each entry an Admin sees, in order, with one-line descriptions and a pointer to the chapter that covers it.
- Suggested setup order with cross-links:
  1. Create users (ch. 4)
  2. Model systems and subsystems (ch. 5)
  3. Model environments (ch. 6)
  4. Optional: model hosts (ch. 7)
  5. Configure change kinds and gates (ch. 8)
  6. Optional: release templates (ch. 9), API keys (ch. 10)
- Length target: ~500 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.3 onboarding your tenant"
```

---

## Task 5: Admin guide ch. 4 — Managing users and roles

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify the tenant-admin user-management page**

Read: `frontend/src/pages/tenant/UserManagement.tsx`. List the controls (create user form fields, edit form fields, the role drop-down, deactivate action, password reset action). Read `backend/app/core/security.py` for the role check decorators (`require_role`, `require_tenant_admin`) and `backend/app/api/v1/users.py` for the endpoint set.

- [ ] **Step 2: Draft chapter 4**

Content:
- Concept: roles are tenant-scoped; one role per user per tenant; Admin is required to manage other users.
- The five roles: a table of role × what they can do (read-only summary; pointer to the appendix matrix in ch. 13 for full detail).
- Walkthrough: navigate to `/tenant/users` → create user (list fields) → assign role → save.
- Walkthrough: edit user, deactivate user, reactivate user.
- Walkthrough: password reset (whatever flow exists in the page; verify against source).
- Note: master-admin assignment is master-admin-only — pointer to ch. 2.
- Length target: ~450 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.4 managing users and roles"
```

---

## Task 6: Admin guide ch. 5 — Modelling your platform: systems and subsystems

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify systems/subsystems pages**

Read: `frontend/src/pages/SystemCatalog.tsx`, `frontend/src/pages/SystemDetail.tsx`, and the subsystem-related components used inside SystemDetail (likely a tab or section). Read `backend/app/db/models/system.py` and `backend/app/db/models/subsystem.py` for the field set (name, description, GitHub URL, custom_fields, dependencies).

Read: `frontend/src/components/SystemTopologyDiagram.tsx` (or similar) to understand what the topology view shows (nodes, edges, types of dependencies).

- [ ] **Step 2: Draft chapter 5**

Content:
- Concept: System = a product/app (e.g. *Payments*); Subsystem = a deployable unit of that product (e.g. *payments-api*, *payments-web*). Hierarchy: systems contain subsystems.
- ASCII diagram: `System "Payments" → Subsystems: payments-api, payments-web, payments-worker`.
- Walkthrough: create a system at `/systems` (list exact fields including GitHub URL and custom fields).
- Walkthrough: open `/systems/:id`, add subsystems (list the form fields).
- Walkthrough: add a system dependency (this system depends on another system).
- Walkthrough: add a component dependency (a subsystem depends on another component — explain the difference: system-level vs subsystem-level).
- Reading the topology view: what circles vs squares mean, what arrow direction indicates, how to expand/collapse (whatever the actual UI does; verify).
- Length target: ~700 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.5 systems and subsystems"
```

---

## Task 7: Admin guide ch. 6 — Modelling environments

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify environment pages and model**

Read: `frontend/src/pages/EnvironmentList.tsx`, `frontend/src/pages/EnvironmentDetail.tsx`. Read `backend/app/db/models/environment.py` and `backend/app/db/models/environment_instance.py` for fields and statuses. Read `frontend/src/components/EnvironmentTopologyDiagram.tsx`.

Confirm the four statuses: active / maintenance / inactive / decommissioned (or whatever the source actually says — these may differ).

- [ ] **Step 2: Draft chapter 6**

Content:
- Concept: Environment = a logical instance (e.g. *UAT-1*, *PROD-EU*) of one or more systems. Has a type, a status, dependencies on other environments, and *environment instances* (the deployed copies of subsystems running in that environment, optionally pinned to hosts).
- ASCII diagram: `Environment "UAT-1" ─ instances ─ {payments-api on host-7, payments-web on host-8}`.
- Status lifecycle (verify exact states from source):
  `active ─┬─→ maintenance ─→ active`
          `└─→ inactive ──→ decommissioned`
- Walkthrough: create an environment at `/environments` (list fields: name, type, status, custom fields).
- Walkthrough: add environment instances (which subsystem; which host if used).
- Walkthrough: add environment dependencies (this env depends on another env, e.g. UAT-payments depends on UAT-shared-db).
- Walkthrough: decommissioning safely — what to do first (cancel active bookings, close out CRs).
- Reading the environment topology diagram: nodes vs edges, what's an instance vs a dependency.
- Length target: ~700 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.6 modelling environments"
```

---

## Task 8: Admin guide ch. 7 — Modelling infrastructure (hosts)

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify hosts page and model**

Read: `frontend/src/pages/InfrastructureComponentList.tsx` (or whatever the actual filename is — confirm via `frontend/src/App.tsx`'s route table). Read `backend/app/db/models/infrastructure_component.py` (or equivalent) for the field set: type, provider, region, location, external_id, source enum (manual / cloudformation / terraform).

- [ ] **Step 2: Draft chapter 7**

Content:
- Concept: hosts are physical/virtual machines that environment instances can be pinned to. Optional — purely-logical environments work fine without hosts. You'd model hosts when you want to ask questions like "what's running on this server?"
- When to model hosts: a short bulleted list of scenarios.
- Walkthrough: create a host at `/infrastructure/hosts` (list fields).
- Sources explained: manual (you typed it), cloudformation/terraform (imported by IaC discovery — confirm whether discovery is implemented or pending; if pending, mark *Not yet available*).
- Linking a host to an environment instance: pointer to ch. 6.
- Length target: ~400 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.7 modelling infrastructure hosts"
```

---

## Task 9: Admin guide ch. 8 — Configuring change kinds and gates

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify change-kind and gate configuration**

Read: the MR !17 + !18 work — search the codebase for `change_kind` (likely `backend/app/db/models/change_kind.py` and a settings page in `frontend/src/pages/` or `frontend/src/pages/admin/`). Read `backend/app/services/change_request_service.py` for default kinds. Read the gate-due-dates work referenced in `docs/superpowers/specs/2026-04-23-release-gate-due-dates-design.md`.

If a UI page exists for editing change kinds, document it. If kinds are seeded only and not yet UI-editable post-Phase-4, document the seeded set and mark UI editing as *Not yet available* if applicable. **Verify before assuming.**

- [ ] **Step 2: Draft chapter 8**

Content:
- Concept: a *change kind* is a tenant-configurable category of change request (e.g. infrastructure, application, database, security). Each kind can carry its own custom fields.
- Concept: a *gate* on a release is a checkpoint that must pass (e.g. *Test sign-off*, *Security review*) before the release can advance. Gates can have due dates (MR !17).
- Walkthrough: list the default change kinds; describe how to add a new kind (or note that this is admin/CLI only if no UI exists).
- Walkthrough: configuring gates on a release template (forward-pointer to ch. 9).
- Length target: ~450 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.8 change kinds and gates"
```

---

## Task 10: Admin guide ch. 9 — Release templates

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify release-template pages**

Read: `frontend/src/pages/admin/ReleaseTemplateLibrary.tsx`, `frontend/src/pages/admin/ReleaseTemplateForm.tsx`. Read `backend/app/db/models/release_template.py` for fields. Read `backend/app/services/release_template_service.py` for application logic (how a template materialises into a release).

- [ ] **Step 2: Draft chapter 9**

Content:
- Concept: a release template is a reusable skeleton for releases — it carries the gates, scope-item shape, and custom-field defaults. Useful when your team always ships the same shape of release (e.g. "monthly product release").
- Walkthrough: navigate to `/admin/release-templates` → *New Template* → list fields.
- Walkthrough: editing an existing template; semantics (does editing a template affect already-created releases? — verify and document).
- When a template helps: regular cadenced releases, multi-team coordination.
- When a template hurts: one-off hotfixes (use a blank release).
- Length target: ~400 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.9 release templates"
```

---

## Task 11: Admin guide ch. 10 — API keys and webhooks

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify API-key UI and webhook endpoints**

Read: `frontend/src/components/apikeys/ApiKeyManagement.tsx` (the additional working dir mentioned in the environment). Read `backend/app/api/v1/api_keys.py` for the endpoints, and `backend/app/core/security.py:api_key_auth` for scope semantics. Read `backend/app/api/v1/webhooks/deployment.py` and the build payload schema at `backend/app/api/v1/schemas/build.py` and `backend/app/api/v1/schemas/deployment.py` for the full webhook payload shape.

List all available scopes by searching for `api_key_auth(required_scope=...)` calls and the scope enum (likely in `backend/app/db/models/api_key.py` or `backend/app/core/security.py`).

- [ ] **Step 2: Draft chapter 10**

Content:
- Concept: API keys let CI/CD systems write to EnvManager (currently only the deployment webhook). Keys are tenant-scoped, scope-restricted, and revealed once on creation.
- Walkthrough: navigate to `/tenant/api-keys` → *New API Key* → name, scopes, expiration → reveal screen → copy.
- Critical warning: the raw key is shown **once**. If lost, revoke and re-issue.
- Walkthrough: revoking a key.
- Available scopes: a table of scope name × what it grants × example use.
- Worked example: the full `POST /api/v1/webhooks/deployment` payload from the (already-verified) build payload schema, with a runnable curl. Include `event_id`, `system_slug`, `subsystem_slug`, `environment_slug`, `status`, `deployed_at`, the nested `build` object with all its fields.
- Idempotency: replay semantics — `(tenant_id, subsystem_id, git_sha, build_number)` upsert key.
- Pointer: user guide ch. 8 covers the read side.
- Length target: ~750 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.10 API keys and deployment webhook"
```

---

## Task 12: Admin guide ch. 11 — Tenant settings

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify tenant settings page**

Read: `frontend/src/pages/tenant/TenantSettings.tsx`. Read `backend/app/db/models/tenant.py` for which fields are editable vs read-only.

- [ ] **Step 2: Draft chapter 11**

Content:
- Concept: tenant-level configuration JSON — a free-form bag for tenant preferences.
- Walkthrough: navigate to `/tenant/settings`, edit the JSON, save.
- What's editable (whatever the JSON object contains) vs what's not (name, slug — verify).
- Validation: what happens on bad JSON.
- Length target: ~250 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.11 tenant settings"
```

---

## Task 13: Admin guide ch. 12 — Import/export

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Verify the import/export page**

Read: `frontend/src/pages/ImportPage.tsx`. Read the import API endpoints (search `backend/app/api/v1/` for `import`). Note which entities are supported (systems and environments per the audit; verify).

- [ ] **Step 2: Draft chapter 12**

Content:
- Concept: bulk-load systems and environments via JSON; useful for bootstrapping a tenant from another source-of-truth.
- Walkthrough: navigate to `/import` → choose entity type → upload JSON → review results.
- JSON shape for systems and environments — show a small valid example for each (build the example by reading the model field set).
- Upsert semantics: matching key (slug? id?), what gets updated vs inserted (verify against the import service).
- Reading the result counts: created vs updated vs failed.
- Length target: ~350 words.

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.12 import and export"
```

---

## Task 14: Admin guide ch. 13 — Appendix: role permission matrix

**Files:**
- Modify: `docs/admin-guide.md`

- [ ] **Step 1: Build the matrix from source**

For every top-level route (from `frontend/src/App.tsx`), determine which roles can read it and which roles can mutate it. Cross-reference:
- The route's page component for any `useUser()` / role-gating logic.
- The corresponding backend endpoint(s) for `require_role`, `require_tenant_admin`, `require_master_admin` decorators.

Build a table: route × {Master Admin, Admin, Release Manager, Test Manager, Developer, Viewer} × {read, write}.

- [ ] **Step 2: Draft chapter 13**

Content:
- Intro paragraph: how to read the matrix; "write" includes create/edit/delete.
- The full matrix as a markdown table. Group routes by area (Tenants, Users, Systems, Environments, Bookings, Change Requests, Releases, Builds, Deployments, Hosts, Settings, API Keys, Import).
- Footnotes for any nuance (e.g. "Release Managers can transition releases but not delete completed ones" — only if true).

- [ ] **Step 3: Commit**

```bash
git add docs/admin-guide.md
git commit -m "docs(admin-guide): ch.13 role permission matrix"
```

---

## Task 15: User guide ch. 1 — Introduction

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Draft chapter 1**

Content:
- One-paragraph product description (same opening as admin guide ch. 1).
- Who this guide is for: Release Managers, Test Managers, Developers, Viewers — already in a tenant set up by an Admin.
- Pointer: if you're setting up a tenant from scratch, see `admin-guide.md`.
- Pointer: if you're a developer working on EnvManager itself, see `CLAUDE.md`.
- Length target: ~200 words.

- [ ] **Step 2: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.1 introduction"
```

---

## Task 16: User guide ch. 2 — Logging in and the dashboard

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify login + dashboard**

Read: the login page (search `frontend/src/pages/` for `Login`), `frontend/src/pages/Dashboard.tsx`, and the layout/nav component for the left-nav entries visible to each role. Confirm the demo login: `admin` / `admin123`, tenant `demo`.

- [ ] **Step 2: Draft chapter 2**

Content:
- Walkthrough: login screen → enter credentials + tenant → dashboard.
- Dashboard cards: list each card with what it shows (count + click-through destination if any).
- The left nav: a table of nav entry × destination route × one-line description × which roles see it.
- Top bar: the user menu (logout, switch tenant if applicable).
- Length target: ~350 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.2 logging in and dashboard"
```

---

## Task 17: User guide ch. 3 — Concepts in 5 minutes

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Draft chapter 3**

Content:
- ASCII entity diagram showing the eight core concepts and their relationships:
  ```
  System ──contains──> Subsystem ──ships as──> Build ──deploys as──> Deployment
                                                                      │
                                                                      v
  Environment <──instance of subsystem on host── Environment Instance
       │
       ├──reserved by──> Booking
       ├──changed by──> Change Request
       └──delivered to──> Release ──groups──> Change Requests + Scope Items
  ```
- For each of the eight concepts: one sentence definition + cross-link to the chapter that covers it (in either guide):
  - System → admin-guide ch. 5
  - Subsystem → admin-guide ch. 5
  - Environment → admin-guide ch. 6
  - Booking → user-guide ch. 5
  - Change Request → user-guide ch. 6
  - Release → user-guide ch. 7
  - Build → user-guide ch. 8
  - Deployment → user-guide ch. 8
- Length target: ~400 words.

- [ ] **Step 2: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.3 concepts in 5 minutes"
```

---

## Task 18: User guide ch. 4 — Browsing systems and environments

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify list and detail pages**

Read: `frontend/src/pages/SystemCatalog.tsx`, `frontend/src/pages/SystemDetail.tsx`, `frontend/src/pages/EnvironmentList.tsx`, `frontend/src/pages/EnvironmentDetail.tsx`. List the DataGrid columns of each list view, in order. Identify the filter controls. Identify the tabs/sections of each detail view.

- [ ] **Step 2: Draft chapter 4**

Content:
- Walkthrough: `/systems` — DataGrid columns (in order), filters, sort, click-through to detail.
- System detail: tabs/sections (overview, subsystems, dependencies, topology, custom fields).
- Walkthrough: `/environments` — DataGrid columns, filters, statuses badge.
- Environment detail: tabs/sections (overview, instances, dependencies, topology, schedule per Phase 2, deployments tab per Phase 4).
- How custom fields render in DataGrid columns and detail panels.
- Length target: ~600 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.4 browsing systems and environments"
```

---

## Task 19: User guide ch. 5 — Booking environments

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify booking pages and lifecycle**

Read: `frontend/src/pages/bookings/BookingCalendar.tsx`, `frontend/src/pages/bookings/BookingList.tsx`, `frontend/src/pages/bookings/BookingDetail.tsx`. Read `backend/app/services/booking_service.py` for the lifecycle states and the multi-env booking semantics (Phase 2.5 / spec `2026-04-15-multi-env-booking-lifecycle-design.md`).

Confirm the lifecycle states from the source. Confirm the conflict-detection behaviour from the service. Confirm the extension-request flow.

- [ ] **Step 2: Draft chapter 5**

Content:
- Concept: a booking reserves one or more environments for a time window. Has a status lifecycle and a creator.
- Lifecycle ASCII (from source):
  `draft → submitted → approved → in_use → completed`
        `       └→ rejected`
        `       └→ cancelled`
  (Use the actual states as verified.)
- Walkthrough: calendar view at `/bookings/calendar` — drag/click to create, the new-booking dialog and its fields (start, end, environments, purpose, custom fields). Confirm against source.
- Walkthrough: list view at `/bookings/list` — DataGrid columns and filters.
- Walkthrough: booking detail — fields, transitions, who can transition.
- Conflict detection: what triggers it, how the UI surfaces it.
- Extension request: from the booking detail, request more time; who approves.
- Cancelling a booking: when it's allowed.
- Length target: ~700 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.5 booking environments"
```

---

## Task 20: User guide ch. 6 — Raising change requests

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify CR pages and lifecycle**

Read: `frontend/src/pages/ChangeRequestList.tsx`, `frontend/src/pages/ChangeRequestDetail.tsx`. Read `backend/app/services/change_request_service.py` for the lifecycle and the kinds. Read the kind-customisation work (admin guide ch. 8 reference).

- [ ] **Step 2: Draft chapter 6**

Content:
- Concept: a change request is a planned change with a kind (configurable), linked environments/hosts, and a status lifecycle.
- Lifecycle ASCII (from source):
  `draft → submitted → approved → in_progress → completed`
        `       └→ rejected`
- Walkthrough: `/change-requests` list — columns, filters by kind/status/environment.
- Walkthrough: create a CR — exact fields (title, description, kind, environments, hosts, custom fields).
- Walkthrough: CR detail — sections, transition buttons, who can act.
- Linking environments and hosts: how (multi-select on the form), why (audit trail).
- Filtering: combinations that are useful.
- Length target: ~600 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.6 raising change requests"
```

---

## Task 21: User guide ch. 7 — Working with releases

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify release pages and lifecycle**

Read: `frontend/src/pages/releases/ReleaseList.tsx`, `frontend/src/pages/releases/ReleaseCalendar.tsx`, `frontend/src/pages/releases/ReleaseTimeline.tsx`, `frontend/src/pages/releases/ReleaseDetail.tsx`. Read `backend/app/services/release_service.py` for the lifecycle, gate semantics, scope items, and enterprise membership. Cross-check with `docs/superpowers/specs/2026-04-19-phase-3-core-releases-design.md` and `2026-04-22-enterprise-releases-design.md`.

- [ ] **Step 2: Draft chapter 7**

Content:
- Concept: a release groups change requests, scope items, gates, environments, and (post-deployment) deployments. Has a type (project/hotfix/patch/major/minor) and a lifecycle. Releases can join enterprise releases for multi-project coordination.
- Lifecycle ASCII (from source):
  `draft → planning → in_progress → submitted → approved → completed`
        `        └→ cancelled (any prior state — verify)`
- Walkthrough: list view (`/releases`) — columns, filters, type badges.
- Walkthrough: calendar view (`/releases/calendar`) — what it shows, click semantics.
- Walkthrough: timeline view (`/releases/timeline`) — what it shows.
- Walkthrough: create a release — fields including type, dates, template (if used), gates, scope.
- Release detail: tabs/sections (overview, scope, change requests, environments, deployments per Phase 4, gates, status history, enterprise membership).
- Walkthrough: transitioning a release — who can do what at each state.
- Gates: how to mark a gate complete; what blocks transition.
- Scope items: what they are (granular pieces of release content), how to add.
- Linking change requests and environments to a release.
- Enterprise releases: joining a release to an enterprise umbrella, membership semantics.
- Status history: read-only audit trail.
- Length target: ~1100 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.7 working with releases"
```

---

## Task 22: User guide ch. 8 — Builds and deployments

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify build and deployment pages**

Read: `frontend/src/pages/builds/BuildList.tsx`, `frontend/src/pages/builds/BuildDetail.tsx`, `frontend/src/pages/deployments/DeploymentList.tsx`, `frontend/src/pages/deployments/DeploymentDetail.tsx`. Read `backend/app/services/build_service.py` and `backend/app/services/deployment_service.py` for the data model and the link-CR write surface. Confirm Phase 4 behaviour from `docs/phases/phase-4.md`.

- [ ] **Step 2: Draft chapter 8**

Content:
- Concept: builds and deployments are read-only artefacts in the UI. They're created by CI via the deployment webhook (admin guide ch. 10).
- ASCII:
  `CI runs → POST /api/v1/webhooks/deployment → upserts Build + creates Deployment + auto-creates code_deployment CR → visible in UI`
- Walkthrough: `/builds` — DataGrid columns, filters (subsystem, branch, date).
- Build detail: pipeline steps table, custom fields, linked release, jira tickets.
- Walkthrough: `/deployments` — DataGrid columns, filters (env, release, status).
- Deployment detail: status, deployer, timestamps, build link, CR link, custom fields.
- Lifecycle ASCII for deployment status (from source):
  `pending → in_progress → success`
                          `└→ failed`
                          `└→ rolled_back`
- Walkthrough: swapping the auto-created `code_deployment` CR for a human-authored CR (Phase 4 Sub-2 write surface). Who can do this (Admin), how (the deployment-detail action).
- "Find which build went to which environment": filter `/deployments` by environment, sort by date, pivot to build.
- > **Not yet available:** Manual build creation in the UI; build-form / deployment-form for non-CI users.
- Length target: ~700 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.8 builds and deployments"
```

---

## Task 23: User guide ch. 9 — Topology and dependency views

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Verify topology components**

Read: `frontend/src/components/SystemTopologyDiagram.tsx`, `frontend/src/components/EnvironmentTopologyDiagram.tsx` (or similarly-named files). Confirm node shapes/colours, edge kinds, interaction (zoom, click, expand).

- [ ] **Step 2: Draft chapter 9**

Content:
- Concept: the topology view shows the dependency graph for a system or environment. Surfaced inline on the System Detail and Environment Detail pages.
- System topology: what nodes are (system + subsystems + dependent systems), what edges are (system-level vs component-level dependencies).
- Environment topology: what nodes are (environment + instances + dependent environments + hosts), what edges are.
- Reading the diagram: arrow direction = "depends on"; click semantics; zoom controls (verify against source).
- Length target: ~350 words.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.9 topology views"
```

---

## Task 24: User guide ch. 10 — Tips and common workflows

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Validate each cookbook against the demo tenant or source**

For each of the four workflows below, walk through the click-path mentally using the verified source from earlier chapters. If a step doesn't actually work in the current UI, rewrite the workflow.

- [ ] **Step 2: Draft chapter 10**

Content — four cookbook workflows:

1. **"I'm releasing a hotfix"**
   - Create release of type `hotfix` at `/releases` → New Release.
   - Add scope item describing the fix.
   - Link the affected environment(s).
   - Optional: link an existing CR; otherwise the deployment webhook will auto-create one.
   - Drive lifecycle: draft → planning → in_progress.
   - Wait for CI to push the deployment.
   - Verify the deployment appears under the release's Deployments tab.
   - Mark gates complete, transition to submitted → approved → completed.

2. **"I need to book UAT for a 2-week test cycle"**
   - Open `/bookings/calendar` for the UAT environment.
   - Click on the start date, drag through the end date (or use the dialog).
   - Fill purpose + custom fields.
   - Submit; wait for approval.
   - If a conflict surfaces, see the conflict dialog and either pick a different window or coordinate with the conflicting booking's owner.

3. **"My deployment failed — where do I look?"**
   - Open `/deployments`.
   - Filter by status = failed (or by environment + recent date).
   - Click into the deployment detail.
   - Read the pipeline-steps table for the failed step.
   - Pivot to the linked build to see commit + jira tickets.
   - Pivot to the linked CR for the audit trail.
   - If a re-run is needed, the CI system handles it; EnvManager will upsert on replay.

4. **"I want to see what changed in production last week"**
   - Open `/deployments`.
   - Filter environment = PROD, status = success, date range = last 7 days.
   - For each deployment, the build link shows commit/branch and the CR link shows the change description.
   - Alternatively, open the production environment's detail page → Schedule tab; deployments are surfaced there alongside bookings and CRs (Phase 4 Sub-2).

- Length target: ~900 words total (~225 each).

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.10 cookbook workflows"
```

---

## Task 25: User guide ch. 11 — Appendix: status lifecycles cheat sheet

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Pull lifecycle diagrams from earlier chapters**

Re-read the lifecycles drafted in user-guide ch. 5 (booking), ch. 6 (CR), ch. 7 (release), and ch. 8 (deployment). They must already match source after their verification steps.

- [ ] **Step 2: Draft chapter 11**

Content: four ASCII lifecycle diagrams on a single page, in this order: Booking, Change Request, Release, Deployment. Each gets a one-line caption and a cross-link to the chapter where it's described in detail. No new content — this is a quick-reference appendix.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs(user-guide): ch.11 lifecycles cheat sheet"
```

---

## Task 26: Cross-link audit + CLAUDE.md banner update + final review

**Files:**
- Modify: `docs/admin-guide.md`
- Modify: `docs/user-guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Audit cross-links**

Grep both guides for relative links: `grep -nE '\]\((admin-guide|user-guide)\.md#' docs/admin-guide.md docs/user-guide.md`. For each link, verify the target anchor exists. Anchors are GitHub-style: lowercase, spaces → hyphens, punctuation stripped. Fix any broken ones.

- [ ] **Step 2: Audit "Not yet available" callouts**

Grep both guides: `grep -n 'Not yet available' docs/admin-guide.md docs/user-guide.md`. Confirm every callout uses the exact prefix and points to the phase that delivers it (or just states "deferred" if no phase is committed).

- [ ] **Step 3: Verify acceptance criterion 1 — admin guide chapters**

Read: `docs/admin-guide.md`. Confirm 13 chapters present and non-empty. Confirm each chapter's claims about UI controls were verified against source during its task.

- [ ] **Step 4: Verify acceptance criterion 2 — user guide chapters**

Read: `docs/user-guide.md`. Confirm 11 chapters present and non-empty. Confirm the four cookbook workflows in ch. 10 reference only verified UI paths.

- [ ] **Step 5: Update CLAUDE.md banner**

Add two bullets to the docs links block in `CLAUDE.md`'s header (the block currently containing Requirements / App Architecture / Infra / Roadmap):
- `> **Admin Guide**: [docs/admin-guide.md](docs/admin-guide.md)`
- `> **User Guide**: [docs/user-guide.md](docs/user-guide.md)`

- [ ] **Step 6: Commit**

```bash
git add docs/admin-guide.md docs/user-guide.md CLAUDE.md
git commit -m "docs(manual): cross-link audit, banner update, final pass"
```

- [ ] **Step 7: Push the branch and open MR**

```bash
git push -u origin docs/user-manual-spec
```

Then open an MR via the GitLab API per `reference_gitlab.md` (project_id 2, target `main`). MR title: `docs: add admin guide + user guide`. MR description: link to the spec at `docs/superpowers/specs/2026-04-25-user-manual-design.md`.

---

## Self-review checklist

- [x] Spec coverage: every chapter in the spec maps to a task (admin 1–13 → tasks 2–14; user 1–11 → tasks 15–25; banner update → task 26).
- [x] No placeholders: every task has explicit verification sources, content outline, and exact commit commands.
- [x] Type consistency: lifecycle diagrams referenced consistently across user-guide ch. 5/6/7/8 and the appendix in ch. 11.
- [x] No fabricated controls: every chapter task starts with a "verify against source" step before drafting.
- [x] Branch strategy clear: continue on `docs/user-manual-spec`, push and MR at end (Task 26 step 7).
- [x] Acceptance criteria from spec all addressed in Task 26's verification steps.
