# EnvManager UI Audit — 2026-07-22

A full-surface review of the React 18 + TypeScript + MUI + Redux Toolkit frontend for **usability, consistency, and modern feel**. Produced by four parallel source-code audits (design-system, state/feedback, navigation/IA, accessibility/microcopy) plus a runtime DOM pass driving the live app.

## Executive verdict

The app is **functionally solid and internally consistent in its newer code** (the release / RAID / gates / admin surfaces are exemplary — uniform `useConfirm` + `useSnackbar`, proper `loading`/`empty`/`error` handling via the `DataTable` wrapper). What holds it back from feeling *modern and effortless* is three things, in priority order:

1. **A near-empty MUI theme** — no typography scale, radius, spacing, or component defaults — so every page hand-rolls its shell inline. The result reads as "default un-customised MUI" rather than a designed product. This is the single highest-leverage fix.
2. **A cluster of real correctness bugs in the older CRUD pages** — swallowed delete errors and a stale-derived-view bug — that make the app *look broken* when an operation fails.
3. **A broken deep-link / refresh experience** on every role-gated route (bounces to the dashboard), plus systemic accessibility gaps (unnamed icon buttons, `#id` name fallbacks, one failing contrast pair).

None of this is architectural — it's all fixable incrementally, and a handful of foundational changes (theme + a shared page shell + the auth-gate fix) move the needle disproportionately.

---

## P1 — Fix first

### Correctness bugs (make the app look broken)

| # | Finding | Where | Fix |
|---|---------|-------|-----|
| C1 | **Deep-link / hard-refresh bounces to `/dashboard`** on every role/master-admin-gated route. On reload `auth.token` is rehydrated but `auth.user` is `null` (fetched async in a `useEffect`), so `PrivateRoute` evaluates the role check against `null` and redirects before the user loads. Breaks bookmarks, refresh, and shared links for all `/tenant/*` and `/admin/*` pages. | `App.tsx:52-57` (PrivateRoute), `App.tsx:66-80` (async bootstrap), `store/authSlice.ts:21-28` | Add an `authInitialized` flag to `authSlice` (true on `setCredentials`/`logout`, and immediately when there's no token). Don't render `<Routes>` (or the role check) until auth is resolved — render a spinner while `isAuthenticated && !user`. |
| C2 | **Swallowed delete errors** — `try/finally` with no `catch` (and no success toast): a failed delete (e.g. 409 "has dependents/active bookings") silently closes the dialog as if it succeeded. | `SystemDetail.tsx:640` (explicit swallow w/ comment), `EnvironmentDetail.tsx:223-232`, `EnvironmentList.tsx:288-295`, `SystemCatalog.tsx:251-258`, `SystemDetail.tsx:415,454,645` | Add `catch` → surface the error (snackbar or inline `Alert`); keep the dialog open on failure; add a success snackbar. |
| C3 | **Stale derived view after mutation** (same class as the RAID bug fixed earlier): removing a system does **not** refetch the subsystems/Components tab, so it keeps showing the removed system's subsystems. Add-system *does* refetch; remove doesn't. | `EnvironmentDetail.tsx:223-232` vs `:215` | Add `dispatch(fetchEnvSubsystems(envId))` after a successful remove. |

### Foundational quality

| # | Finding | Where | Fix |
|---|---------|-------|-----|
| Q1 | **The MUI theme is a stub** — only a primary/secondary colour + font; no typography scale, `shape.borderRadius`, spacing, or `components:` defaults. Root cause of the "plain / un-themed" feel and of hundreds of inline `sx` overrides. | `theme.ts` | Populate the theme: `shape.borderRadius`, a typography scale (define the page-title style once), `palette.background`, and `components` defaults for `MuiButton` (`size:'small'`, `disableElevation`), `MuiTextField` (`size:'small'`), `MuiPaper`/`MuiCard`, `MuiChip`. |
| Q2 | **Dashboard is a Phase-0 placeholder** — stat cards hardcode `0`, and a "This is Phase 0… features will be added later" welcome block. It's the landing screen and first impression. | `pages/Dashboard.tsx` | Wire the cards to real Redux selectors (env/booking/release/change counts); delete the roadmap block. |
| Q3 | **`DeploymentStatusChip` hardcodes hex + `color:'white'`** instead of MUI semantic `color=` tokens (every other status chip does it right). Won't survive dark mode; visually diverges. | `components/deployments/DeploymentStatusChip.tsx` | Return `color="success\|error\|warning\|default"`, drop the `sx` override. |

### Accessibility

| # | Finding | Where | Fix |
|---|---------|-------|-----|
| A1 | **Icon-only buttons with no accessible name.** Some have neither label nor tooltip; many rely on a `<Tooltip>`, which sets `aria-describedby` on hover — **not** an accessible *name*. Screen readers announce "button". Runtime pass confirmed ≥1 unnamed button on the release detail; there is no `<h1>` on any page either. | No-name: `AppLayout.tsx:177`, `EnvSubsystemHostsDialog.tsx:196`, `ScopeTable.tsx:205`. Tooltip-only (needs `aria-label` too): `EnvironmentList.tsx:208,213`, `SystemCatalog.tsx:177,182`, `ScopeTable.tsx:181,195`, `ApiKeyManagement.tsx:80`, many in `SystemDetail.tsx` | Add an explicit `aria-label` to every icon button (in addition to the Tooltip). Set `component="h1"` on the primary page title. |
| A2 | **`#id` display-name-rule violations (~18 sites)** — renders `SubSystem #7`, `Release #42`, `User #3`, `Scope #12` when a name is null. Violates the established product rule ("never `#N`"). | `RaidItemDialog.tsx:499,539`, `DependencyDetailPane.tsx:50`, `ScopeHistoryDrawer.tsx:81`, `EnvironmentsPanel.tsx:88`, `ConflictsPanel.tsx:132`, `BookingCalendar.tsx:245`, `EnterpriseMembershipTab.tsx:30,53`, `ChangeRequestDetail.tsx:241,341`, `SystemDetail.tsx:980,1067,1286,1414`, +others | Resolve to a name (lookup map / include name in API payload); if genuinely unknown, use descriptive text ("Unnamed release"), never `#id`. |

---

## P2 — Should fix

Status as of 2026-09-02; the open structural items are PRs 2–4 of `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md`.

| # | Finding | Where | Fix | Status |
|---|---------|-------|-----|--------|
| P2-1 | **White text on amber (`#ff9800`) fails WCAG AA** (~2.1:1; needs 4.5:1). This is the RAG "amber" state — exactly the thing users must read. Present in the recently-added RAID components. | `raidConstants.ts` amber; `RaidTab.tsx:163`, `RaidSummaryCards.tsx:46`, `RaidHeatMap.tsx:70`, `RaidRollupTab.tsx:60,89` | Compute per-band foreground from luminance (dark text on amber/light fills) instead of always `#fff`. | Open |
| P2-2 | **Silent list-fetch failures** — `BuildList`, `DeploymentList`, `ReleaseList` never read their slice's `error`, so a failed fetch is an unexplained empty grid. | `BuildList.tsx`, `DeploymentList.tsx`, `ReleaseList.tsx` (errors exist in the slices) | Render an `<Alert severity="error">` from the slice error. | Open |
| P2-3 | **Two incompatible tab systems + fragile numeric indices.** `ReleaseDetail` uses `activeTab === 5`; `EnterpriseTabs` uses string keys. Inserting a tab renumbers every branch (already bit this file — its docstring still says "5 tabs"). Tabs also aren't in the URL, so they reset on reload and can't be shared. | `ReleaseDetail.tsx:64,142-166` (+stale docstring 1-9), `EnterpriseTabs.tsx:20-58` | Convert `ReleaseDetail` to string-keyed tabs; reflect the active tab in the URL (`?tab=raid` via `useSearchParams`). | Open |
| P2-4 | **No shared page shell** — the header pattern (`<Box p:3>` → title `h5` → spacer → button) is copy-pasted across ~10 list pages, and padding/title styles have already drifted (Dashboard uses `Container`+`h4`; EnvironmentList bolds its `h5`, ReleaseList doesn't). | `ReleaseList`, `BookingList`, `EnvironmentList`, `ChangeRequestList`, … | Extract `<PageHeader title action>` + `<PageContainer>`; adopt on the top ~6 list pages. | Open |
| P2-5 | **Raw `<DataGrid>` in 15 files vs the `DataTable` wrapper in 4.** The wrapper adds saved column visibility, consistent density, and empty-state text — most tables miss all of it. | `BookingList`, `EnvironmentList`, `BuildList`, `SystemCatalog`, `DeploymentList`, `ApiKeyManagement`, +admin/enterprise | Migrate raw-DataGrid list pages to `components/DataTable.tsx`. | Open |
| P2-6 | **`autoFocus` on the destructive confirm button** — Enter/Space immediately deletes. | `components/ConfirmDialog.tsx:41` | Focus Cancel (or the body) when `destructive`; only autofocus confirm for non-destructive. | ✅ Closed (PR 2). The behaviour was already implemented — `autoFocus={destructive}` with a comment — but had **no test**. PR 2 added the guard; it passed on first run, confirming the fix was real and not merely believed. |
| P2-7 | **Generic confirm messages** that don't name the item ("Delete this scope item?", "Revoke this API key?") — 11 sites. Good pattern already exists (`Delete R-002 "…"`). | `ScopeTable.tsx:90`, `GatesTable.tsx:129,194`, `ApiKeyManagement.tsx:44`, `UserManagement.tsx:115`, `TenantList.tsx:68`, … | Include the entity name in the message. | ✅ Closed (PR 2). All 11 sites name their entity, each falling back to the original generic wording rather than to `undefined` or an id. Handler signatures moved from `(id)` to `(entity)` so no site resolves a name by `.find()` into a possibly-capped collection. |
| P2-8 | **Disabled Save with no explanation** — required fields show no inline error, just a greyed button. | `RaidItemDialog.tsx:592`, `CriterionDialog.tsx:66`, `ReleaseEventDrawer.tsx:175` | Show inline `error`/`helperText` on submit (match the EnvironmentList/SystemCatalog pattern). | Open |
| P2-9 | **Admin area poorly discoverable** — the main-nav "Admin" item hard-navigates to `/admin/config/booking`; RAID Settings / API keys / scope rules live only inside the AdminLayout sidebar or the avatar menu (3 disjoint entry points). | `AppLayout.tsx:327-338`, `AdminLayout.tsx:25-76` | Point "Admin" at a stable landing and rely on the AdminLayout sidebar as the single hub; ensure every admin page is ≤2 clicks from the main shell. | Closed — PR 1 (admin mode) |

---

## P3 — Polish

| # | Finding | Where | Fix | Status |
|---|---------|-------|-----|--------|
| P3-1 | Missing success snackbars on Environment/System create/update/delete (inconsistent with release/admin pages). | `EnvironmentList.tsx`, `SystemCatalog.tsx` | Add `snackbar.success(...)`. | Open |
| P3-2 | Flat, inconsistent surfaces — 106 `variant="outlined"` vs 2 `elevation`; hairline borders everywhere, no depth. | across pages | Pick one surface strategy in the theme (subtle elevation + radius) as the `MuiPaper`/`MuiCard` default. | Open |
| P3-3 | ~101 hardcoded hex colours in charts/SVG, with three different "greens" for success. | `ReleaseTimeline`, `ReleaseCalendar`, topology diagrams, `raidConstants.ts` | Central `statusColor()` helper reading `palette.success/error/warning`; feed SVG `fill`/`stroke`. | Open |
| P3-4 | Exact-match nav active state (`pathname === item.path`) de-selects on nested/param routes. | `AdminLayout.tsx:105,121` | Use `pathname === p || pathname.startsWith(p + '/')` (AppLayout already does this). | Closed — PR 1 |
| P3-5 | Inconsistent detail-page wayfinding — no breadcrumbs, no `document.title`, per-page back affordance; `DeploymentDetail` builds its own header. | `ReleaseDetail` vs `DeploymentDetail`, all `*Detail` | Shared `<DetailPageHeader back title actions>`; set page titles per route. | ✅ Closed (PR 2). All 13 detail pages adopt `DetailPageHeader`; ~40 list/admin pages adopt `PageHeader`. Breadcrumbs and `document.title` come from one static `routeMeta` table. |
| P3-6 | Clickable `<Typography onClick>` (app title, calendar cells) isn't keyboard-operable. | `AppLayout.tsx` title, `BookingCalendar.tsx:183` | Use a `Button`/`Link` or add `role="button"` + `tabIndex` + `onKeyDown`. | Closed — PR 1 (title link; calendar cells remain) |
| P3-7 | Timeline SVG has no text alternative. | `ReleaseTimeline.tsx:240` | `role="img"` + `aria-label` summary. | Open |
| P3-8 | Heading hierarchy tracks visual size, not document outline; no `<h1>` on any page. | app-wide | Set `component="h1/h2"` where the outline level differs from the visual variant. | ✅ Closed (PR 2) for page titles: both shared headers render the title as `component="h1" variant="h5"`, so all 53 pages now have exactly one `<h1>`. A sweep test keeps new `variant="h4"` page titles from reappearing (allowlisting 7 genuine non-title uses: stat tiles, a device code, a non-routed tab, and `Login`). Deeper heading levels within pages are untouched. |

---

## Highest-ROI sequence (recommended)

1. **Theme pass (Q1)** — one file, app-wide lift; removes most inline `sx` and makes everything feel designed. Biggest perceived-quality jump.
2. **The three correctness bugs (C1–C3)** — small, high-impact; stop the app looking broken on failure/refresh.
3. **Quick a11y wins** — `aria-label` on icon buttons (A1), dark-on-amber contrast (P2-1), Cancel-focus on destructive confirm (P2-6). Cheap, and P2-1 is in code we just shipped.
4. **Shared `<PageHeader>` + `<PageContainer>` (P2-4)** and migrate list pages to `DataTable` (P2-5) — locks in consistency structurally.
5. **`#id` name-rule sweep (A2)** and string-keyed/URL tabs (P2-3) — correctness + polish.
6. Dashboard (Q2), admin discoverability (P2-9), and the P3 polish as time allows.

## Already good (no action)
- RAG/status chips pair colour **with text** — never colour-alone.
- MUI dialogs give focus-trap/restore for free; no custom portal bypasses it.
- The release / RAID / gates / admin surfaces: consistent confirm+snackbar, `loading`/`empty`/`error` states, `DataTable` wrapper.
- `Login.tsx` is exemplary (semantic h1, required fields, `<Alert>` errors, autofocus).
- No `<img>` without alt; hamburger and decorative icons are correctly labelled/hidden.

## Method & limitations
- 4 parallel read-only source audits + a runtime DOM pass on Dashboard and ReleaseDetail (heading/landmark/icon-name/`div[onClick]` checks).
- A full **axe-core** run was **not** completed — loading it from a CDN was sandbox-blocked, and the naive contrast probe can't resolve MUI's translucent chip backgrounds. Contrast findings here are from the code-level audit (computed `#fff`-on-`#ff9800`); a proper axe/Lighthouse pass in-browser is a worthwhile follow-up for a definitive contrast/ARIA sweep.
