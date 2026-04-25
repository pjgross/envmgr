# User Manual — Admin Guide + User Guide

**Status:** Spec — awaiting approval before implementation
**Date:** 2026-04-25
**Phase:** Documentation (post-Phase 4)

## Summary

Produce two end-user documentation files that explain how to use EnvManager
for the audiences who actually drive the product day-to-day:

- `docs/admin-guide.md` — for **Master Admins** (one-time tenant
  provisioning) and **Tenant Admins** (ongoing platform configuration:
  users, systems, environments, change kinds, release templates, API
  keys, infrastructure, settings, import/export).
- `docs/user-guide.md` — for **Release Managers, Test Managers,
  Developers, and Viewers** working in an already-provisioned tenant
  (browse, book, raise change requests, manage releases, read builds and
  deployments).

Both guides are concept-led and task-oriented: every chapter opens with
a short conceptual intro, then numbered "how to" walkthroughs. Diagrams
are markdown/ASCII only; no screenshots in the first cut.

## Goals

1. A tenant admin standing up a brand-new tenant can read
   `admin-guide.md` end-to-end and have a usable, populated tenant
   without needing to read code or ask questions.
2. A new end user (e.g. a Release Manager joining a team) can read
   `user-guide.md` and complete the common day-to-day workflows
   (book an environment, raise a CR, drive a release through its
   lifecycle, find a build/deployment) using only the UI.
3. The manual matches the **post-Phase-4** state of the product. No
   features are described that don't exist; deferred features (DORA,
   Jira) are explicitly called out as out of scope.
4. The guides cross-reference each other rather than duplicate
   concepts. A user who needs to know "where did this system come from?"
   gets pointed back to the admin guide.
5. Both files are self-contained markdown — no docs-site tooling
   required — and live alongside existing `docs/` content.

## Non-goals

- **Deployment / install instructions** — covered in `CLAUDE.md`,
  `docs/architecture copy.md`, and `docs/prod architecture.md`.
- **API reference** — Swagger UI at `http://localhost:8000/docs` is
  authoritative; the manual links to it but does not duplicate it.
- **Master-admin platform operations beyond tenant provisioning** —
  e.g. infrastructure host setup of EnvManager itself, monitoring,
  backups. Out of scope.
- **Phase 5+ features** — DORA metrics, Jira integration, GitHub
  discovery enrichment. Explicitly flagged as not yet available.
- **Screenshots** — text + ASCII diagrams only in this iteration. May
  be layered in later as the UI stabilises past Phase 5.
- **Localisation** — English only.

## Audience and tone

| Reader | Reads | Expected level |
|--------|-------|----------------|
| Master Admin (one-off) | Admin guide ch. 2 | Knows their way around a SaaS admin panel |
| Tenant Admin (primary) | All of admin guide | Mid-technical; comfortable with CRUD, custom fields, JSON |
| Release Manager / Test Manager | All of user guide | Process-aware, not necessarily a developer |
| Developer / Viewer | User guide ch. 2–8 | Technical, light on EnvManager concepts |

Tone:

- Imperative, second person. "Click *New Release*", "Open
  `/releases/calendar`".
- Routes and identifiers in code spans. UI labels in `*italics*`.
- No marketing language ("powerful", "seamless", "robust").
- Role badges on chapter headings where the chapter is role-gated, e.g.
  *(Admin only)*, *(Release Manager+)*.
- ASCII state diagrams over prose for lifecycles
  (`draft → submitted → approved → in_progress → completed`).
- Every chapter ends with a one-line cross-link to the related
  chapter in the other guide where applicable.

## File: `docs/admin-guide.md`

Chapter list:

1. **Introduction** — what EnvManager does in one paragraph; who this
   guide is for; the role model (Master Admin / Admin / Release Manager
   / Test Manager / Developer / Viewer); how this guide relates to the
   user guide and the architecture docs.
2. **Provisioning a new tenant** *(Master Admin only)* — the
   `masteradmin` login; `/admin/tenants`; creating tenant + slug;
   creating the first Admin user for that tenant; using
   "sign in as tenant"; disabling a tenant.
3. **Onboarding your tenant** — first login as Admin; dashboard tour;
   the mental model:
   `Systems → Subsystems → Environments → Bookings/Changes/Releases → Builds/Deployments`;
   suggested setup order.
4. **Managing users and roles** — `/tenant/users`; the five roles
   (Admin, Release Manager, Test Manager, Developer, Viewer) and what
   each can do; creating users; deactivating; password resets;
   pointer to permission-matrix appendix.
5. **Modelling your platform: systems and subsystems** — concept
   (System = a product/app; Subsystem = a deployable unit of that
   product); creating a system; GitHub URL; custom fields; creating
   subsystems; system dependencies vs component dependencies; reading
   the topology diagram.
6. **Modelling environments** — concept (Environment = a logical
   instance like UAT-1, with type, status, dependencies, and instances
   on hosts); creating environments; statuses (active / maintenance /
   inactive / decommissioned); environment instances and their
   relation to subsystems; environment dependencies; decommissioning
   safely.
7. **Modelling infrastructure (hosts)** — `/infrastructure/hosts`;
   when this is needed (physical/virtual hosts backing environment
   instances) vs when purely logical environments suffice; types,
   providers, regions; sources (manual / cloudformation / terraform).
8. **Configuring change kinds and gates** *(tenant-configurable)* — the
   tenant-level kinds list (MR !18); gate definitions and due-date
   policies (MR !17); how this drives the change-request and release
   workflows.
9. **Release templates** — `/admin/release-templates`; concept
   (a reusable release skeleton: gates, scope shape, custom fields);
   creating templates; editing; when a template helps vs hurts.
10. **API keys and webhooks** — `/tenant/api-keys`; the one-time-reveal
    flow; scopes (especially `webhooks:deployment`); what your CI must
    POST to `/api/v1/webhooks/deployment`; key rotation and revocation;
    pointer to user-guide ch. 8 for the read-side experience.
11. **Tenant settings** — `/tenant/settings`; the editable JSON object;
    examples of useful tenant-level settings; what name/slug fields are
    immutable.
12. **Import/export** — `/import`; supported entities (systems,
    environments); JSON shape; upsert semantics and how to read import
    results.
13. **Appendix: role permission matrix** — table mapping every
    significant route × every role × {read, write, admin}.

## File: `docs/user-guide.md`

Chapter list:

1. **Introduction** — what EnvManager does in one paragraph; who this
   guide is for; what the role lens means in practice; pointer to
   admin guide for setup-side concerns.
2. **Logging in and the dashboard** — login screen; demo creds; the
   dashboard's three cards (env count, active bookings, pending
   changes); the left navigation.
3. **Concepts in 5 minutes** — illustrated entity overview:
   `System → Subsystem → Environment → Booking → Change Request → Release → Build → Deployment`.
   ASCII entity diagram. Cross-links to admin guide for who creates
   each artefact.
4. **Browsing systems and environments** — `/systems`, `/environments`;
   list filters and DataGrid columns; detail pages; reading the
   topology diagrams; how custom fields are surfaced.
5. **Booking environments** — concept (a time-bounded reservation with
   a status lifecycle); calendar (`/bookings/calendar`) vs list view;
   creating a booking; lifecycle
   `draft → submitted → approved/rejected`; conflict detection;
   requesting an extension; cancelling.
6. **Raising change requests** — concept (a planned change with gates,
   links to environments/hosts, and tenant-configured kinds);
   `/change-requests`; lifecycle
   `draft → submitted → approved/rejected → in_progress → completed`;
   linking environments and hosts; filtering.
7. **Working with releases** — concept (a coordinated rollout grouping
   CRs, scope items, gates, environments); the three views
   (`/releases` list, `/releases/calendar`, `/releases/timeline`);
   creating a release; lifecycle
   `draft → planning → in_progress → submitted → approved → completed`;
   gates and test phases; scope items; linking CRs and environments;
   enterprise-release membership (multi-project releases); reading the
   status history.
8. **Builds and deployments** — concept (read-only artefacts created
   by CI via the deployment webhook); how CI populates them (pointer
   to admin guide ch. 10); `/builds` and `/deployments` list/detail;
   pipeline steps and custom fields; how to find which build went to
   which environment; how to swap an auto-created `code_deployment`
   CR for a human-authored CR.
9. **Topology and dependency views** — embedded diagrams in System
   Detail and Environment Detail; how to read them; what nodes and
   edges represent.
10. **Tips and common workflows** — short cookbook:
    - "I'm releasing a hotfix"
    - "I need to book UAT for a 2-week test cycle"
    - "My deployment failed — where do I look?"
    - "I want to see what changed in production last week"
11. **Appendix: status lifecycles cheat sheet** — every state diagram
    on one page (booking, change request, release, deployment).

## Tone and conventions (both guides)

- Routes shown in code: `/releases/:id`.
- UI labels italicised: *New Release*, *Submit*.
- API endpoints in code blocks with method:
  `POST /api/v1/webhooks/deployment`.
- Lifecycle diagrams as ASCII single-line arrows where they fit
  (`draft → submitted → approved`); multi-line ASCII boxes only when
  the diagram has branches.
- Role badges: `**(Admin only)**`, `**(Release Manager+)**`,
  `**(Master Admin only)**`.
- Cross-links use relative paths and anchors:
  `[creating a system](admin-guide.md#5-modelling-your-platform-systems-and-subsystems)`.
- "Out of scope / not yet available" callouts use a blockquote with the
  prefix `> **Not yet available:**` so they're trivially greppable.

## Out-of-scope features that must be explicitly marked

These will appear in chapters where a reader might reasonably expect
them, with a `> **Not yet available:**` callout pointing to the phase
that will deliver them:

- DORA metrics dashboards (Phase 5+)
- Jira integration / ticket sync (Phase 3 Sub-3, deferred)
- GitHub-driven infra discovery enrichment beyond what already exists

## Implementation approach

Both files are written from scratch by reading:

- The frontend feature audit summarised in this brainstorming session
  (every page, route, and role gate).
- `docs/requirements.md` and `docs/plan.md` for vocabulary and intent.
- `docs/phases/phase-1.md` … `phase-4.md` for delivered behaviour.
- The frontend source under `frontend/src/pages/` to validate every
  claim made about a control or field.

The implementation plan (writing-plans skill, next step) will break
this into per-chapter tasks so chapters can be drafted, reviewed, and
adjusted independently rather than landing as one ~3000-line PR.

## Acceptance criteria

1. `docs/admin-guide.md` exists, covers all 13 chapters above, and
   every claim about a UI control or route can be verified against the
   current frontend (no fabricated controls).
2. `docs/user-guide.md` exists, covers all 11 chapters above, and the
   four cookbook workflows in chapter 10 are end-to-end runnable
   against the demo tenant.
3. Both files cross-reference each other rather than duplicate concept
   prose.
4. Deferred features are explicitly called out, not silently omitted.
5. No screenshots; ASCII/markdown diagrams only; lifecycle diagrams
   present for booking, change request, release, and deployment.
6. CLAUDE.md banner is updated to point at the new guides.
