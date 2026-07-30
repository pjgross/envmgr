# Frontend Review & Modernisation Recommendations — EnvManager

> **Review date:** 2026-04-18
> **Reviewed branch:** `feature/multi-env-booking-lifecycle`
> **Status (updated 2026-07-30):** partially executed. Vitest/Playwright infrastructure, the
> MUI confirm sweep, nav grouping and the P1 items from [ui-audit.md](ui-audit.md) have landed;
> route-level **code splitting is done** (entry chunk 3,445 kB → 180 kB, PR #31). The remaining
> tiers below are still open. Read alongside [ui-audit.md](ui-audit.md), which is the more
> recent review.

## Context

The live app is served from branch **`feature/multi-env-booking-lifecycle`** at `frontend/`. This review reflects the actual running code: a multi-tenant test-environment management tool with Dashboard, Systems (catalog/detail/topology), Environments (list/detail/topology), Bookings (calendar/list/detail/form with lifecycle transitions, conflicts, custom fields), Import, Admin (tenants, entity config, lifecycle templates, booking types, component types, custom field definitions), Tenant settings, User management, and impersonation.

**Why this review matters now:** the core features exist and work. The question is which modernisation investments would most improve day-to-day usability for the people running releases on this tool.

---

## What actually exists (grounded snapshot)

### Stack
React 18.2 + Vite 5 + TypeScript 5.3 (strict), MUI 5.15 + `@mui/x-data-grid` 6.20, Redux Toolkit 2 + thunks, axios 1.6, FullCalendar 6.1 (daygrid + timegrid + interaction), ReactFlow 11.11 + `@dagrejs/dagre` for topology, date-fns 3, React Router 6.21, Playwright 1.58 (E2E only). ESLint strict (`--max-warnings 0`). No Prettier, no Storybook, no unit-test runner, no form lib, no toast lib, no i18n, no error boundary, no dark mode.

### Shell & routing
- `frontend/src/components/AppLayout.tsx` — persistent 240px drawer, AppBar with avatar menu (user, platform admin, tenant admin, logout), collapsible Bookings group (Calendar/List), Impersonation banner at top.
- `frontend/src/App.tsx` — flat `<Routes>`; `PrivateRoute` with `requireMasterAdmin` / `requiredRole`; session hydration on mount (`authService.getCurrentUser()` if token present but user missing).
- `frontend/src/services/api.ts` — axios interceptor attaches Bearer token from `localStorage`, clears storage and redirects on 401.

### Feature patterns (from reading three representative pages)
- `frontend/src/pages/bookings/BookingList.tsx` — DataGrid, status chips, client-side status filter, per-row kebab menu with lazily-fetched allowed transitions, column visibility persisted to localStorage.
- `frontend/src/pages/environments/EnvironmentDetail.tsx` — tab layout (Overview / Topology / Versions / Versioning), **MUI `Table`** for systems/subsystems/versions, ReactFlow + dagre for topology, several bespoke dialogs, `CustomFieldsSection`.
- `frontend/src/pages/admin/TenantList.tsx` — **MUI `Table`** again, inline-validated Dialog form, Sign-In-As + Disable actions.

### Strengths worth keeping
1. Feature-folder layout with clean `services/` + `store/` separation.
2. Redux Toolkit + thunks consistently applied; `unwrap()` error pattern in pages.
3. Strict TS across the app; well-typed API response shapes in `frontend/src/types/`.
4. FullCalendar + ReactFlow + dagre integrations are non-trivial and work well.
5. Impersonation flow is clean (banner + token swap + exit).
6. Custom fields system tied to lifecycle templates — extensible without schema churn.
7. Conflicts/feedback workflow in `frontend/src/components/bookings/ConflictsPanel.tsx` is a real domain feature, not generic CRUD.

---

## Findings — real gaps (ordered by user-facing impact)

### A. Consistency & reuse
1. **Tables split between `DataGrid` and `MUI Table`.** DataGrid on BookingList / SystemCatalog; plain Table on EnvironmentDetail, TenantList and several admin panels. User preference (stored feedback) is DataGrid everywhere — for column visibility, sorting, density, filtering.
2. **Forms are all manual `useState` + inline validation.** Every dialog reinvents required-field checks, blur behaviour, error display. No shared `FormProvider` / field primitives.
3. **Errors surface in three different ways:** page-level `<Alert>`, local dialog error state, console. No single user-visible channel for "your action succeeded/failed".

### B. UX polish
4. **No toast/snackbar system.** Every mutation relies on inline Alerts or silent success. Save → no feedback.
5. **No dark mode.** `palette.mode: 'light'` hard-coded in `frontend/src/theme.ts`.
6. **Sidebar not responsive.** Permanent 240px drawer with no breakpoint for small screens — tablet/mobile usability is poor.
7. **No app-level error boundary.** A render-time throw in any page blanks the whole app.
8. **No 404 route.** Unknown paths silently redirect.
9. **No breadcrumbs / document title updates.** Deep views (Environment → Topology → Dependency detail) give no back-trail beyond the browser button.
10. **Calendar is click-only.** FullCalendar supports drag-to-create / drag-to-resize; `frontend/src/pages/bookings/BookingCalendar.tsx` doesn't wire `select`/`eventDrop`/`eventResize`.
11. **Lists have no bulk operations.** Approve/reject multiple bookings, disable multiple users — currently one at a time.
12. **Filters don't persist across navigation.** Status filter on BookingList resets on every entry.

### C. Quality infrastructure
13. **No unit tests.** `vitest` + React Testing Library missing; only Playwright E2E. Redux slices, service layer, form validation have zero coverage.
14. **No Prettier.** Mixed quoting/indentation will drift as the app grows.
15. **No CI config** in `.github/`; lint/typecheck/tests aren't enforced on PRs.
16. **No Storybook** for the reusable primitives (`CustomFieldsSection`, `ConflictIndicator`, topology node components).

### D. Accessibility
17. Only two `aria-label` occurrences across the codebase; most icon-only buttons rely on MUI defaults.
18. No skip-to-content link.
19. No focus management on dialog open/close beyond MUI defaults.
20. No keyboard shortcut / command palette — painful once a user has 10+ destinations in the sidebar.

### E. Data-layer ergonomics (not urgent, but worth naming)
21. **Redux-thunk for server state** means each list re-fetches on every mount with no caching, no background refetch, no dedup. TanStack Query would be a structural improvement but is a large migration — call it out, don't tackle now.
22. **401 handling is hard redirect.** No refresh-token path; acceptable per project decisions (simple JWT), but concurrent requests racing a 401 can cause double-redirect.

---

## Recommendation — prioritised modernisation plan

Four tiers, ordered by ROI. Do **Tier 1** next, then reassess.

### Tier 1 — Consistency foundations (1–2 days; immediate quality lift)
1. **Global snackbar system** via `notistack`. Single `enqueueSnackbar('Saved')` call sites across all mutations. Retire inline `<Alert>` from non-form-level places.
2. **App-level error boundary** (`react-error-boundary`) wrapping `<Routes>`. Friendly fallback UI + "reload" action. 404 route added.
3. **Shared form primitives**: `FormDialog`, `FormTextField`, `FormSelect` built on `react-hook-form` + `zod`. Convert **one** dialog (e.g. New Booking) as the reference. Don't mass-convert yet — migrate opportunistically as dialogs are touched.
4. **`DataTable` wrapper** around MUI DataGrid with consistent defaults (density, column visibility persistence, toolbar, empty state, row-count footer). Convert `TenantList` and the systems/subsystems tables on `EnvironmentDetail` as proof cases. Leave the rest to migrate as they're edited.
5. **Dark mode toggle** in the AppBar user menu. `createAppTheme(mode)` factory, persisted to localStorage, respecting `prefers-color-scheme` on first load.
6. **Responsive sidebar**: `variant="permanent"` above `md`, `variant="temporary"` below, with a hamburger on the AppBar at small widths.
7. **Prettier** + `eslint-config-prettier`; one-off `prettier --write .` commit so reviews stop bikeshedding whitespace.

### Tier 2 — Feature UX (2–4 days; user-visible wins)
8. **Calendar drag-to-create + drag-to-resize** on `BookingCalendar.tsx`: wire `selectable`, `select`, `eventDrop`, `eventResize`. Drag-select opens the New Booking dialog prefilled with start/end.
9. **Bulk operations on BookingList / UserManagement / TenantList**: DataGrid `checkboxSelection`, bulk-action toolbar appearing when rows are selected (approve / reject / disable).
10. **Filter persistence per list page** — state in URL query params (shareable) rather than just local state. Browser back/forward restores filters.
11. **Breadcrumbs + `useDocumentTitle` hook** driven from route config.
12. **Inline DataGrid edit** for safe columns (booking notes, environment description) with `processRowUpdate` + optimistic thunk.

### Tier 3 — Quality infrastructure (1–2 days; compounding)
13. **Vitest + React Testing Library** with a smoke test for `Login`, `BookingList`, and a Redux slice. Wire into npm `test` script.
14. **GitHub Actions CI** running `lint`, `tsc --noEmit`, `vitest`, `playwright`. Branch protection on `master`/`main` once green.
15. **Accessibility pass**: skip-link, `aria-label` on every icon-only button, focus trap test on dialogs, eslint-plugin-jsx-a11y.

### Tier 4 — Deeper investments (evaluate later, don't commit now)
16. **TanStack Query** for server state, keeping Redux for auth/UI state only. Migrate feature-by-feature. Large change; only if server-state ergonomics become a real pain.
17. **Command palette** (`cmdk`) for quick navigation once the sidebar passes ~10 destinations.
18. **Storybook** for `DataTable`, form primitives, topology nodes, `ConflictIndicator`.
19. **Token refresh** if/when backend introduces short-lived JWTs.

---

## Critical files to modify for Tier 1

- `frontend/package.json` — add `notistack`, `react-error-boundary`, `react-hook-form`, `zod`, `@hookform/resolvers`; dev: `prettier`, `eslint-config-prettier`, `vitest` (ready for Tier 3), `@testing-library/react`, `jsdom`.
- `frontend/src/main.tsx` — wrap in `<ErrorBoundary>` + `<SnackbarProvider>`.
- `frontend/src/App.tsx` — add `*` → `<NotFound/>` route.
- `frontend/src/theme.ts` — export `createAppTheme(mode)`; consume mode from Redux/localStorage.
- `frontend/src/components/AppLayout.tsx` — responsive drawer; dark-mode toggle in user menu.
- `frontend/src/services/api.ts` — unchanged; keep as-is.

New files:
- `frontend/src/components/DataTable.tsx`
- `frontend/src/components/ErrorFallback.tsx`, `frontend/src/components/NotFound.tsx`
- `frontend/src/components/form/{FormDialog,FormTextField,FormSelect}.tsx`
- `frontend/src/hooks/useSnackbar.ts` (thin wrapper so pages don't import notistack directly)
- `.prettierrc`, `.prettierignore`

Opportunistic rewrites (Tier 1 scope):
- Convert `TenantList` and `EnvironmentDetail` system/subsystem tables to `DataTable`.
- Convert New Booking dialog to `FormDialog` + zod schema as the form-stack reference.
- Replace inline success/failure `<Alert>` usages in mutation handlers with `useSnackbar()`.

---

## Verification

1. `npm install && npm run build` — clean TS compile.
2. `npm run dev` — app loads, sidebar collapses on <md viewport, AppBar shows hamburger.
3. **Dark mode:** toggle in user menu flips theme; persists across reload; matches system on first visit.
4. **Snackbar:** creating a booking shows a success toast; failing shows an error toast; no stray inline Alerts left on those paths.
5. **Error boundary:** temporarily `throw new Error()` at top of `BookingList` → friendly fallback renders, AppLayout + sidebar still usable. Remove the throw.
6. **404:** visit `/nope` → NotFound page with link home.
7. **DataTable:** `TenantList` and the Environment systems table render via DataTable with density toggle, column visibility (persisted), and empty state.
8. **Form stack:** the New Booking dialog now uses react-hook-form + zod — empty submit shows inline validation errors before hitting the API.
9. **Lint/format:** `npm run lint` passes; `npx prettier --check .` passes.
10. **Playwright:** existing E2E suite still green.

No backend changes required for Tier 1.
