# Frontend information architecture, admin mode and page shell

> Status: design approved 2026-09-02; §6 amended 2026-09-03 before PR 2
> (one tab mechanism, `routeMeta` stays static, the segment form becomes a
> route-level redirect — see §6 and §11).
>
> A five-PR frontend programme. It replaces the two disagreeing admin menus with
> one admin mode, restructures the main navigation, turns the Phase-0 placeholder
> dashboard into a landing page plus a personal "My work" inbox, and closes the
> structural half of the 2026-07-22 UI audit (`docs/ui-audit.md`: P2-2, P2-3,
> P2-4, P2-5, P2-6, P2-7, P2-9, P3-4, P3-5, P3-6, P3-8). Visual polish
> (P3-2/P3-3) is deliberately not here.
>
> There are no live users — only testers on test data — so paths and labels
> change freely, with redirects kept for one release.

## 1. The problem

**Two admin menus that disagree.** The main drawer's *Administration* group
(`components/navConfig.tsx`) lists seven items. A second, 220 px sidebar
(`pages/admin/AdminLayout.tsx`) lists seven "Admin" items plus thirteen
"Entity Config" items. The two share four pages and name three of them
differently (*Users* / *User Management*; *Tenant Settings* / *General
Settings*; *API Keys* / *API keys*). *Change Config* in the main drawer lands
on Bookings custom fields. GitHub Integration and Platform Admin exist only in
the main drawer; User Groups, Projects, Environment Groups, Scope-change rules
and all thirteen entity-config pages exist only in the sidebar. Release
Templates — tenant configuration, Admin-gated — sits under *Release
Management*.

**The sidebar appears on five routes and vanishes on the rest.** Only
`/admin/config/*`, `/admin/scope-change-rules`, `/tenant/api-keys`,
`/tenant/raid-settings` and `/admin/github` are nested under `AdminLayout`.
`/tenant/users`, `/tenant/settings`, `/tenant/groups`, `/tenant/projects` and
`/tenant/environment-groups` are not, so clicking *User Management* in the
sidebar removes the sidebar (confirmed in the browser 2026-09-02). User Groups,
Projects and Environment Groups are therefore unreachable from the main drawer
at all — a user must first land on a page that happens to show the sidebar.

**The main drawer loses its place inside admin.** `AppLayout` computes which
group is open once, at mount; arriving at `/admin/config/booking` shows
*Administration* collapsed and nothing selected. The sidebar selects by exact
path match, so a detail route deselects its parent (audit P3-4).

**Three columns of chrome.** 240 px main drawer + 220 px admin sidebar before
any content; the admin sidebar is a `permanent` Drawer with no responsive
behaviour.

**Fragile tabs.** `EntityConfig` computes tab indices arithmetically from
seven feature flags; `ReleaseDetail` (11 tabs), `EnvironmentDetail` (8) and
`SystemDetail` (7) use numeric indices, none in the URL. A tab cannot be
linked to, does not survive reload, and inserting one renumbers the rest.

**The dashboard is a Phase-0 placeholder.** Three tiles hardcoded to `0` and
a welcome paragraph reading "This is Phase 0 … the authentication system is now
working." It is every user's landing page.

**Five action queues, no inbox.** Environment requests, contention
escalations, decommissions, incidents and PIR actions each have a worklist,
spread over three groups. Nothing tells a user work is waiting on them.

**Consistency has regressed since the audit.** 28 raw `<DataGrid>` usages
against 8 `DataTable` (audit: 15 / 4). No shared page header, no breadcrumbs,
no `document.title`, no `<h1>` on any page, label prefixes repeating the group
name ("Releases — Calendar"), group names wrapping at 240 px, six admin items
sharing one wrench icon.

## 2. Targets and non-goals

Laptops and desktops first; iPad Pro (1024 × 1366 portrait) is the smallest
supported viewport; phones are not a target. MUI stays. Redux + service layer
stays.

Out of scope, named so it is not rediscovered as news: theme, colour and
surface polish (P3-2, P3-3); notifications, email or polling; phone layouts;
an icon-rail / collapsible drawer; per-item nav badges; splitting the
1.4–1.9k-line detail pages (a refactor, not a UX change); any change to what
any role may *do* — this programme moves pages, it moves no permissions.

## 3. Main navigation

One 240 px drawer, same slot as today, restructured:

| Position | Items |
|---|---|
| **Dashboard** (top-level) | landing page (§5) |
| **My work** (top-level, count badge) | personal inbox (§5) |
| **Catalogue** | Systems · Environments · Hosts · Compare environments · Import |
| **Bookings** | Calendar · List · Environment requests · Change requests · Projects · Environment groups · Contentions · Decommissions |
| **Releases** | Releases · Calendar · Timeline · Scope windows · Analytics · Builds · Deployments · Incidents · PIR actions |
| **Insights** | DORA metrics · Environment health |
| **Administration** (single entry; role Admin or master admin) | enters admin mode (§4) |

Decisions:

- *Environment Definition / Environment Management* become **Catalogue /
  Bookings**. The split (define vs use) was right; the words were not.
- **Projects and Environment groups leave admin** for *Bookings*. Both are
  readable by every role (`GET /projects`, `GET /environment-groups` are open
  to any tenant member; only writes are Admin) and both exist to coordinate
  bookings (usage agreements, contention rank, group bookings). New paths
  `/projects`, `/projects/:id`, `/environment-groups`,
  `/environment-groups/:id`. Their write controls stay Admin-gated on the page
  exactly as now.
- **Release templates leaves *Releases*** for admin (§4). It was the only
  Admin-gated configuration page filed under a workflow group.
- Child labels drop the group prefix. Labels are sentence case throughout.
  No group or item label wraps at 240 px.
- Dashboard and My work are ungrouped so they are one click and always
  visible.

Behaviour in `AppLayout`:

- The group containing the current route **opens on every navigation**, via an
  effect on `location.pathname`, not only in the `useState` initialiser.
- Group open/closed state persists in `localStorage` under one key, wrapped in
  try/catch, defaulting to open; a user-collapsed group stays collapsed until
  they navigate into it.
- Active state is prefix match (`pathname === p || pathname.startsWith(p + '/')`)
  everywhere, including the admin drawer.
- The app title in the AppBar is a `Link` to `/dashboard` (P3-6).
- Below `md` the existing temporary drawer behaviour is unchanged.

`navConfig.tsx` stays the single declarative source. `NavItem` gains
`badge?: 'my-work'`; the file exports two trees, `appNav` and `adminNav`
(§4), rendered by one `<NavDrawer items>` component.

## 4. Admin mode

### 4.1 Shell

`/admin` and everything under it is admin mode. `AppLayout` detects the
prefix and renders the **admin drawer in the same 240 px slot**; AppBar,
avatar menu and content area are unchanged. The admin drawer is headed by
**"← Back to EnvManager"**, which returns to the last non-admin route
(remembered in `uiSlice`; falls back to `/dashboard`). `AdminLayout.tsx` and
its second drawer are deleted.

### 4.2 Menu

One `adminNav` tree, in sections. Section = icon + overline heading; items have
no icons.

| Section | Items → route |
|---|---|
| **Organisation** | Users `/admin/users` · User groups `/admin/user-groups`, `/admin/user-groups/:id` · Tenant settings `/admin/settings` |
| **Environments** | Tiers `/admin/environments/tiers` · Naming policy `/admin/environments/naming-policy` · Lifecycle & decommissioning `/admin/environments/lifecycle-policy` · Request lifecycle `/admin/environment-requests/lifecycle` · Custom fields `/admin/environments/fields` |
| **Bookings** | Booking types `/admin/bookings/types` · Lifecycle `/admin/bookings/lifecycle` · Custom fields `/admin/bookings/fields` |
| **Releases** | Templates `/admin/releases/templates`, `/admin/releases/templates/:id` · Gate types `/admin/releases/gate-types` · Rollback policy `/admin/releases/rollback-policy` · Event types `/admin/releases/event-types` · Lifecycle `/admin/releases/lifecycle` · Scope-change rules `/admin/releases/scope-change-rules` · RAID settings `/admin/releases/raid` · Custom fields `/admin/releases/fields` · Scope item fields `/admin/release-changes/fields` |
| **Delivery** | Change requests `/admin/change-requests/{fields,lifecycle}` · Builds `/admin/builds/fields` · Deployments `/admin/deployments/fields` · Incidents `/admin/incidents/{fields,lifecycle}` · Systems `/admin/systems/fields` · Subsystems `/admin/subsystems/fields` · Component types `/admin/component-types` · Environment request fields `/admin/environment-requests/fields` |
| **Integrations** | API keys `/admin/api-keys` · GitHub `/admin/github` |
| **Platform** (master admin only) | Tenants `/admin/tenants`, `/admin/tenants/:id` |

Sections group by **what an admin is configuring**, not by which table holds
the setting: RAID settings and scope-change rules sit beside release templates,
where a release manager looks for them.

### 4.3 Entity configuration pages

`EntityConfig` becomes `/admin/<entity>/<tab>` with **string-keyed tabs in the
route** (`useUrlTab`, §6). The per-entity page keeps its tab strip
(so an admin on *Tiers* can see *Naming policy* is next door), but each tab is
a first-class URL, so the drawer can point at a tab directly. The seven
`*_SUPPORTED` feature lists move into a single `entityConfigTabs` table:
`{ entity, tab, label, panel }` rows. The drawer items for a section are
derived from that table, not hand-listed a second time.

### 4.4 Landing page

`/admin` renders section cards, each listing its items with a one-line
description taken from `adminNav`. It is generated from the config; nothing on
it is hand-maintained. This is the hub audit P2-9 asked for.

### 4.5 Routes and redirects

All admin routes nest under one layout route:

```
<Route path="/admin" element={<PrivateRoute requiredRole="Admin"><Outlet/></PrivateRoute>}>
  <Route index element={<AdminHome/>} />
  …
  <Route path="tenants" element={<PrivateRoute requireMasterAdmin>…} />
</Route>
```

Master admins who are not role Admin: `PrivateRoute` for `/admin` accepts
`role === 'Admin' || is_master_admin`, matching today's nav rule ("a
master-admin who is not role Admin still sees Platform Admin"). Such a user
sees only the Platform section.

Old paths redirect with `<Navigate replace>` for one release, then are
removed:

| Old | New |
|---|---|
| `/tenant/users` | `/admin/users` |
| `/tenant/settings` | `/admin/settings` |
| `/tenant/groups(/:id)` | `/admin/user-groups(/:id)` |
| `/tenant/projects(/:id)` | `/projects(/:id)` |
| `/tenant/environment-groups(/:id)` | `/environment-groups(/:id)` |
| `/tenant/api-keys` | `/admin/api-keys` |
| `/tenant/raid-settings` | `/admin/releases/raid` |
| `/admin/config/:slug` | `/admin/<entity>/fields` (per-slug map) |
| `/admin/config/component-types` | `/admin/component-types` |
| `/admin/scope-change-rules` | `/admin/releases/scope-change-rules` |
| `/admin/release-templates(/:id)` | `/admin/releases/templates(/:id)` |
| `/admin/github` | unchanged |
| `/admin/tenants(/:id)` | unchanged |

Every in-app link to an old path is updated in the same PR (grep the eleven
literal paths in `src/`); the redirects exist for bookmarks, not for code.

### 4.6 Tenant settings

Name and slug are read-only fields. The JSON editor is kept — nothing in the UI
reads specific keys, so no form is invented for them — but demoted to an
"Advanced" accordion, collapsed by default, with the same validation and save.

## 5. Dashboard and My work

### 5.1 My work

`/my-work` answers "what is waiting on me?" from queues that already exist and
already have the filters:

| Queue | Filter (all exist today) | Counted for |
|---|---|---|
| Environment requests to action | `GET /environment-requests?actionable=true` | operating-team members; Admin |
| Contentions I must decide | `GET /contentions?state=open&owner_user_id=<me>` | the named owner |
| Decommissions needing action | `GET /decommissions?state=warned\|extension_requested\|due`, narrowed to environments whose operations group contains me (Admin: all) | ops-team members; Admin |
| PIR actions I own | `GET /pir-actions?owner_id=<me>&status=open`; overdue counted separately | the owner |
| Open incidents | `GET /incidents?status=open` | everyone — incidents have no assignee |

Each queue is a card: count, the five most urgent rows (soonest deadline,
then oldest), and "View all →" to the existing worklist **with the same filter
in its URL**. Every worklist already reads its filters from search params
(`useServerGrid`), so no worklist changes. An empty queue renders its card
with "Nothing waiting on you"; cards are never hidden.

**`GET /api/v1/me/work`** (new, JWT) returns the five counts plus the
per-queue top-five rows in one round trip:

```json
{
  "as_of": "2026-09-02T09:00:00Z",
  "queues": {
    "environment_requests": { "count": 2, "items": [ … ] },
    "contentions":          { "count": 0, "items": [] },
    "decommissions":        { "count": 1, "items": [ … ] },
    "pir_actions":          { "count": 3, "overdue": 1, "items": [ … ] },
    "incidents":            { "count": 4, "items": [ … ] }
  }
}
```

Rules:

- **One clock.** `now` is taken once; `expiry_boundary(now)` decides overdue
  and decommission state, the same day-not-instant rule every worklist uses.
- **No restated predicates.** Counts call the existing service query seams —
  `contention_service.worklist_query`, `pir_finding_service.worklist_query`,
  `environment_decommission_service` state predicate, the
  `environment_request_service` actionable clause — never a second
  implementation. A named test asserts each count equals the worklist's
  `X-Total-Count` under the same filter and the same clock.
- **Decommission narrowing** reuses the group-membership read
  `environment_service.assert_may_edit_handover` is built on; it is the third
  reader of membership after the two B3b established, and follows their
  tenant scoping and Admin bypass.
- Items carry display names with the row (environment name, release name,
  owner username), never ids — `usernames_for` is not tenant-qualified, per
  A4/C2.

The nav badge on *My work* is the sum of the five counts, fetched on mount and
on every route change through a `useMyWork` hook backed by `uiSlice`. No
polling.

### 5.2 Dashboard

The Phase-0 text goes. The page becomes:

- **Four live tiles**, each a link to the filtered list: *Active environments*
  (`GET /environments?status=active`), *Bookings live now*
  (`GET /bookings?start=<now>&end=<now>` semantics via the existing range
  params — half-open `[start, end)`), *Releases in flight* (non-terminal
  status), *Open incidents*. Counts read `X-Total-Count` from a `limit=1`
  fetch of the existing list endpoint; no aggregation endpoint is invented.
- **Coming up**: bookings starting in the next 7 days and releases whose
  target date falls in the next 14, from the calendar range endpoints.
- **Needs attention**: the existing `ContentionHorizon` widget and the
  Environment Health alert banner, reused unchanged; for Admins, one line with
  governance-gap and quarantined counts (`?governance_gap=true`,
  `?quarantined=true`).

Same page for every role; role changes which counts are non-zero. The
personal part lives in My work.

## 6. Page shell, wayfinding, tabs

**`components/layout/PageHeader.tsx`** — `title`, optional `subtitle`,
`actions`, `breadcrumbs`. One padding; title rendered as `<h1>` at `h5` size
(P3-8); actions right-aligned. Every list and admin page adopts it.

**`components/layout/DetailPageHeader.tsx`** — `back` (explicit target, never
`history.back()`, which lands on a form after a create), `title`, optional
`status` chip, `actions`. Every `*Detail` page adopts it.

**`routeMeta.ts`** — one map of path pattern → `{ label, parent }`. Drives
breadcrumbs and `document.title` (`"Naming policy · Admin · EnvManager"`)
through `usePageTitle`. `TenantDetail`'s ad-hoc breadcrumbs move onto it.

**The map is STATIC; a dynamic name is passed in, never stored in it.**
A detail page's title is its entity's name, which no static map can hold, so
`usePageTitle` takes an optional leading override — `usePageTitle(env.name)`
on `/environments/2` yields `"Mortgage_SIT · Environments · EnvManager"`.
Putting entity data into `routeMeta` would make a wayfinding table depend on
fetched state and give it two sources of truth.

**`hooks/useUrlTab.ts`** — `useUrlTab(keys, defaultKey)` reads and writes
`?tab=` (replace, not push). Adopted by `ReleaseDetail`, `EnvironmentDetail`,
`SystemDetail`, `EnterpriseTabs` and the entity-config pages; numeric tab
indices are removed from all of them. Unknown `?tab=` values fall back to the
default. Deep links elsewhere in the app (incident → release PIR tab,
environment → topology) switch to `?tab=<key>`. Any `<Tabs>` with more than
six entries gets `variant="scrollable" scrollButtons="auto"`.

**ONE MECHANISM: THE TAB IS A QUERY PARAM, EVERYWHERE.** PR 1 shipped the
admin entity-config tab as a *route segment* (`/admin/:entity/:tab`) because a
drawer item has to point straight at "Naming policy". That works, but it left
two ways to say which tab a page is on — the exact shape of drift the
programme was raised to remove, one layer down. `EntityConfig` therefore stops
reading `useParams().tab`, `entityTabPath` emits `/admin/:entity?tab=<key>`,
and `adminNavConfig`'s items move with it in the same commit, so the drawer
never emits a URL that immediately redirects.

**The old segment form is a ROUTE-LEVEL redirect, not a `LEGACY_REDIRECTS`
entry.** `/admin/:entity/:tab` stays registered and renders
`<Navigate replace to={`/admin/${entity}?tab=${tab}`} />`. Two reasons, and
they are separate: `LEGACY_REDIRECTS` is already scheduled for deletion one
release after PR 1, and filling it with URLs two days old would extend the
life of the whole table for no one's benefit; and that table answers "this
PAGE moved", while this answers "a tab is addressed differently" — folding
them together would leave the next reader unable to delete either safely.

**Three corrections to what this section assumed when it was written**, all
found by reading the code before planning rather than by trusting the comments
in it.

**The `?tab=phases&phase=:phaseId` deep link CANNOT BE BUILT, and is struck
from this section.** `ReleaseCalendar`'s header comment documents exactly that
destination, and the page's own subtitle reads "Phase timeline for all active
releases. Click a phase to open the release." Both are fiction:
`GET /releases/calendar` returns `ReleaseCalendarEntry` — `{id, title, start,
end, status, release_type}` — so the events on that calendar are **releases,
not phases**, and no phase id exists anywhere in the payload to deep-link
with. `handleEventClick` navigates to `/releases/:id`, which is the only thing
it could do. PR 2 therefore corrects the comment and the subtitle to describe
what the page does, and builds no deep link. A phase-level calendar is a
different feature needing a different endpoint; it is not smuggled in here.
Recorded at this length because two pieces of prose asserted this behaviour
confidently enough that a spec repeated it.

**The scrollable-tabs clause is partly done**: C4 added it to `ReleaseDetail`
when an eleventh tab rendered off-screen, and `EnterpriseTabs` always had it;
PR 2 covers the remainder and adds the test that stops the next tab regressing
it.

**`ConfirmDialog` already focuses *Cancel* when `destructive`** (audit P2-6) —
implemented, commented, and with no test. PR 2 adds the guard and fixes the
eleven messages (P2-7) only. There are exactly eleven, so that count was
right.

**`ConfirmDialog`**: focuses *Cancel* when `destructive` (P2-6). The eleven
generic confirm messages the audit listed name the entity (P2-7).

## 7. Tables and the iPad pass

**`DataTable` everywhere.** The 28 raw `<DataGrid>` sites migrate to
`components/DataTable.tsx`. It is a pass-through
(`Omit<DataGridProps, visibility | slots>` + `storageKey`, `emptyMessage`,
`showToolbar`), so it composes with `useServerGrid` unchanged. Each migration
adds a unique `storageKey`, an entity-specific `emptyMessage`, and
`disableColumnFilter` wherever the grid is server-paged (docs/pagination.md).

Two rules become mechanical: ESLint `no-restricted-imports` forbids
`DataGrid` from `@mui/x-data-grid` outside `components/DataTable.tsx`; a test
walks `src/` and asserts every `storageKey` literal is unique.

**Silent fetch failures** (P2-2): `BuildList`, `DeploymentList`,
`ReleaseList` render their slice `error` as `<Alert severity="error">`.

**Touch**: icon-only row actions get a 40 px hit area and an `aria-label`;
destructive actions sit last; row click opens the detail on every grid.

**iPad Pro pass**: at 1024 px the permanent drawer leaves 784 px. Every list
page is checked at that width — wide grids scroll inside their own container,
never the page; the multi-tab detail pages rely on §6's scrollable tabs; the
booking calendar and Gantt already scroll. Nothing phone-specific.

## 8. Sequencing

| PR | Delivers | Depends on |
|---|---|---|
| 1 — Navigation & admin mode | §3, §4 | — |
| 2 — Page shell & tabs | §6 | 1 |
| 3 — Dashboard & My work | §5 | 1, 2 |
| 4 — Tables | §7 (migration, lint, alerts, touch) | 2 |
| 5 — iPad pass | §7 (width check, fixes found) | 1–4 |

Each PR leaves the app consistent on its own. PR 1 is the one that fixes the
problem the programme was raised for; the rest can pause between PRs.

## 9. Testing

Named tests for the promises, in the pattern this codebase already uses:

- **Every admin route renders inside the admin shell**: walk `adminNav`,
  render each path, assert the admin drawer and "Back to EnvManager" are
  present. The "sidebar vanishes" defect becomes unrepresentable.
- **Every nav item resolves to a route** (both trees) and **every old path
  redirects** to the table in §4.5 — the B5 "built and connected to nothing"
  class, guarded structurally.
- **Group opens on navigation, not only at mount**: render at `/dashboard`,
  navigate to `/admin/…` and to `/releases/…`, assert the containing group is
  open each time — *re-render, don't just mount* (A2/A3).
- **`GET /me/work` equals the worklists**: for each queue, seed rows on both
  sides of the filter and assert the count equals the worklist's
  `X-Total-Count` under the same filter and clock; on both engines. A PIR
  action due today is **not** overdue; a decommission whose teardown day is
  today is `warned`, not `due`.
- **Membership narrowing on decommissions**: a user in no group sees an empty
  decommission queue; an Admin sees all; a member sees only their group's
  environments.
- **`useUrlTab`**: unknown key falls back; changing tab replaces rather than
  pushes history; the deep links updated in §6 land on the named tab.
- **No page addresses a tab by a route segment.** A structural sweep asserts
  no route pattern ends in `:tab` and that `entityTabPath` emits a query
  param — the one-mechanism rule of §6 is otherwise a sentence nothing checks,
  and the segment form is still reachable as a redirect, so a page could
  quietly go back to it and every behavioural test would stay green.
- **The old `/admin/:entity/:tab` still lands on the right tab**, through the
  route-level redirect rather than `LEGACY_REDIRECTS`.
- **`storageKey` uniqueness** and the `DataGrid` import lint rule.
- **Frontend suite runs whole**, not targeted files — a regression here
  survived six verification steps on targeted runs. Three runs mean SQLite,
  PostgreSQL and the frontend.
- **Browser pass per PR**, recorded in the PR description: every programme in
  this repository found its worst defects only by opening the page.

## 10. Docs

In the same PRs, not after: user guide §2 (dashboard, left navigation, top
bar) and every "Admin → …" path in the admin guide are rewritten in PR 1 and
PR 3; `docs/ui-audit.md` gains a status column marking the findings this
programme closes; CLAUDE.md gets one banner paragraph at the end of PR 5.

## 11. Decisions on record

- **Admin is a mode, not a group** (GitHub / Linear pattern). Considered and
  declined: one drawer with a fifteen-item Administration group (crowds the
  main drawer for the 5 % of time spent administering); a hub page with
  config moved next to each entity (scatters "what can I configure?" across
  the app).
- **Projects and Environment groups are not admin pages.** They are readable
  by every role and used when booking. Moving them out changes no permission.
- **No polling, no notifications.** The badge is fetched on navigation; a
  user who never navigates sees a stale count, which is acceptable for an
  inbox and avoids a standing load per open tab.
- **Counts come from existing endpoints.** `X-Total-Count` on `limit=1`
  fetches for the dashboard tiles; `GET /me/work` is the one new endpoint,
  and it composes existing service query seams rather than restating rules.
- **Tenant settings JSON stays.** Nothing reads named keys through the UI;
  inventing a form for an opaque blob would be a guess.
- **Redirects live one release.** Test bookmarks are the only consumers.
- **A tab is a query param, not a route segment** (amended 2026-09-03, before
  PR 2). Considered and declined: keeping both, with the rule "a tab a drawer
  item targets is a segment, a tab a page owns is a query param" — defensible,
  and rejected because PR 1 exists precisely because two defensible rules
  drifted apart; and converting the detail pages to segments instead
  (`/releases/:id/:tab`), which is tidier REST but rewrites routing for three
  large pages and every link into them, to fix a problem only the admin
  section has.
