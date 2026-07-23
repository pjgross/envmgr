# Navigation Menu Grouping — Design

**Date:** 2026-07-23
**Status:** Approved (design), pending implementation plan
**Scope:** Frontend-only. Reorganize the sidebar navigation in `frontend/src/components/AppLayout.tsx` from a flat list into workflow-lifecycle groups. No routes, pages, or backend change.

---

## Problem

The current sidebar is a flat list of 10+ top-level items with admin/config pages scattered across the avatar dropdown and several routes that have no menu entry at all:

```
Dashboard · Systems · Environments · Bookings▸ · Builds · Change Requests ·
Deployments · Releases▸ · Hosts · Import · Admin
```

Issues (confirmed with the user):

1. **Too many flat items** — no logical top-level grouping.
2. **Doesn't scale** — every feature so far was appended to the end; new tools have no obvious home.
3. **Doesn't match the user mental model** — ordering doesn't follow how a release/environment manager actually works (define → operate → ship → measure).
4. **Admin clutter** — config pages (Users, Tenant Settings, API Keys, RAID Settings, Scope Change Rules, Release Templates, Platform Admin) are hidden in the avatar dropdown or have no menu entry.

## Goal

Group navigation by the **workflow lifecycle**: *Define what you have → Operate it → Ship changes → Measure → Configure.* Each group is a stable bucket so future tools land in an obvious place instead of extending a flat list.

---

## Proposed Structure

Five collapsible groups replace the flat list. Group order follows the lifecycle, with Insights first because it holds the post-login landing page.

```
▸ Insights                    (expanded by default)
    Dashboard                 → /dashboard
    DORA Metrics (future)     — placeholder, added in Phase 5

▸ Environment Definition
    Systems                   → /systems
    Environments              → /environments
    Hosts / Infrastructure    → /infrastructure/hosts
    Import                    → /import

▸ Environment Management
    Bookings ─ Calendar       → /bookings/calendar
    Bookings ─ List           → /bookings/list
    Change Requests           → /change-requests

▸ Release Management
    Releases ─ List           → /releases
    Releases ─ Calendar       → /releases/calendar
    Releases ─ Timeline       → /releases/timeline
    Release Templates         → /admin/release-templates   (Admin only)
    Builds                    → /builds
    Deployments               → /deployments

▸ Administration              (rendered only when role === 'Admin')
    Users                     → /tenant/users
    Tenant Settings           → /tenant/settings
    Change Config             → /admin/config/booking       (booking rules, change kinds, scope-change rules)
    RAID Settings             → /tenant/raid-settings
    API Keys                  → /tenant/api-keys
    Platform Admin            → /admin/tenants              (rendered only when is_master_admin === true)
```

### Placement decisions (resolved with user)

- **Dashboard** lives inside **Insights** (not standalone). Insights defaults to expanded so Dashboard is visible on login — no perceived extra click.
- **Import** lives under **Environment Definition** (where the imported data lands; discoverable for everyday inventory setup).
- **Release Templates** lives under **Release Management** (next to Releases where they're used), even though the route is `/admin/release-templates` and Admin-gated.

---

## Behavior

- **Collapsible groups.** Each group header expands/collapses its children (reuse the existing MUI `Collapse` pattern already used for Bookings/Releases in `AppLayout.tsx`).
- **Insights expanded by default**; other groups collapsed by default.
- **Auto-expand active group.** When the current route matches a child, its parent group expands automatically (e.g. deep-linking to `/releases/:id` opens Release Management). This must work on direct load / refresh, not just in-app clicks.
- **Active-item highlight** on the matching child, as today.
- **Role gating:**
  - `Administration` group renders only when `user?.role === 'Admin'`.
  - `Platform Admin` row within it renders only when `user?.is_master_admin === true`.
  - `Release Templates` row renders only when `user?.role === 'Admin'` (it's Admin-gated today).
  - Regular users see only the top four groups (Insights, Environment Definition, Environment Management, Release Management), minus any Admin-only rows.
- **Avatar dropdown shrinks.** The Platform Admin and Tenant Admin links move into the Administration group, leaving the avatar menu as just Theme toggle + Logout.

---

## Non-Goals / Out of Scope

- No new routes, pages, or components beyond the nav definition.
- No backend changes.
- No change to existing URLs — bookmarks and deep-links keep working identically.
- The `DORA Metrics` row is a **placeholder note only**; it is not wired up here (arrives with Phase 5). Do not add a dead link — either omit it or render it disabled with a "coming soon" affordance. Decision deferred to the plan.
- No visual redesign of the sidebar chrome (colors, width, icons) beyond what grouping requires.

---

## Files Touched

- `frontend/src/components/AppLayout.tsx` — the nav item data structure and the render logic for groups. This file already contains the flat list (lines ~62–89), the conditional Admin item (lines ~327–338), and the avatar dropdown. The nav definition should be refactored into a declarative group structure (array of groups, each with children + optional role predicate) to keep the render logic simple and make future additions a data-only change.

---

## Testing

- Manual: verify each group expands/collapses; verify auto-expand on direct navigation to a child route (including refresh); verify role gating for a regular user, an Admin, and a Master Admin.
- Verify every existing route is still reachable from the menu (no orphaned pages) — cross-check against the route table in `App.tsx`.
- Verify the avatar dropdown now shows only Theme + Logout.
