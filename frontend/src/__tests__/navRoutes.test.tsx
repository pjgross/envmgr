import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adminNav } from '../components/adminNavConfig';
import { appNav, isNavGroup } from '../components/navConfig';
import { renderAppAt } from '../test/renderApp';

vi.mock('../services/authService', () => ({
  authService: { getCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn() },
}));
// Every page fetches on mount; answer with nothing so no page crashes and no
// request leaves jsdom. `headers` carries X-Total-Count for paged lists.
//
// Four GETs need an OBJECT, not the empty-array default, or the page that owns
// them throws during render (a real page bug, not a test artifact — see the
// report):
//  - GET /tenant/environment-naming-policy (EnvironmentNamingPolicyPanel):
//    `[]` is truthy, so the panel's `if (!policy) return` guard is skipped
//    and `setAttributes(policy.required_attributes)` feeds `undefined` to a
//    MUI `multiple` Select, which throws.
//  - GET /tenant/raid-config (RaidSettings): `config.probability_scale` /
//    `impact_scale` are read directly and iterated, which throws on `[]`.
//  - GET /releases/scope-churn-analytics (ReleaseAnalytics): `[]` is truthy,
//    so `{data && <CohortCard cohort={data.scope_changed} />}` renders with
//    `cohort` undefined, and `cohort.count` in JSX throws.
//  - GET /metrics/dora (DoraDashboard): `[]` is truthy, so `if (!data) return
//    []` doesn't fire, and `data.deployment_frequency.series` throws on the
//    missing `deployment_frequency`.
//  - GET /metrics/environments/utilization (also ReleaseAnalytics): `[]`
//    has no `.rows`, so `setUtilization(o.rows)` sets `undefined`, and the
//    DataGrid's own rows-changed effect throws reading `.length` of it.
//
// GET /me/work (AppLayout's nav badge, via `useMyWork`, on EVERY page — and
// MyWork.tsx itself at /my-work) deliberately falls through to the plain `[]`
// default below: `selectMyWorkTotal` and AppLayout's own `attention` check
// are now defensive against exactly this shape (finding 4 of the PR 3
// whole-branch review — `[]` has no `.queues`) and must not crash. That is
// the assertion this sweep makes for `/me/work`; it is not merely untested.
vi.mock('../services/api', () => {
  const empty = () => Promise.resolve({ data: [], headers: { 'x-total-count': '0' } });
  const get = vi.fn((url: string) => {
    if (url.includes('/tenant/environment-naming-policy')) {
      return Promise.resolve({
        data: {
          is_enabled: false,
          name_pattern: null,
          name_pattern_example: null,
          required_attributes: [],
          grace_days: 14,
          effective_from: '2026-01-01T00:00:00Z',
        },
        headers: {},
      });
    }
    if (url.includes('/tenant/raid-config')) {
      return Promise.resolve({
        data: { probability_scale: [], impact_scale: [], rag_bands: [] },
        headers: {},
      });
    }
    if (url.includes('/releases/scope-churn-analytics')) {
      return Promise.resolve({
        data: {
          date_from: null,
          date_to: null,
          scope_changed: { count: 0, delayed_count: 0, delayed_pct: 0, issue_count: 0, issue_pct: 0 },
          stable: { count: 0, delayed_count: 0, delayed_pct: 0, issue_count: 0, issue_pct: 0 },
          releases: [],
        },
        headers: {},
      });
    }
    if (url.includes('/metrics/dora')) {
      return Promise.resolve({
        data: {
          deployment_frequency: { total: 0, series: [] },
          lead_time: { median_seconds: 0, p90_seconds: 0, count: 0, series: [] },
          change_failure_rate: { rate: 0, failed_count: 0, shipped_count: 0 },
          mttr: { mean_seconds: 0, median_seconds: 0, count: 0, series: [] },
        },
        headers: {},
      });
    }
    if (url.includes('/metrics/environments/utilization')) {
      return Promise.resolve({ data: { rows: [], unconfigured_count: 0 }, headers: {} });
    }
    // GET /me/work deliberately gets the plain `[]` default — see the
    // comment above this mock for why that is the point of this sweep now,
    // not a gap in it.
    return empty();
  });
  return { default: { get, post: vi.fn(empty), put: vi.fn(empty), patch: vi.fn(empty), delete: vi.fn(empty) } };
});

const appPaths = appNav.flatMap((e) => (isNavGroup(e) ? e.children : [e])).map((i) => i.path);
const adminPaths = adminNav.flatMap((s) => s.children).map((c) => c.path);
// The main admin loop below runs as { role: 'Admin', is_master_admin: true },
// so it cannot detect a `requireMasterAdmin` guard accidentally applied to a
// non-Platform admin route — a master admin satisfies both checks at once.
// This one runs the same paths as a plain Admin who is NOT a master admin, to
// prove every non-Platform admin route is reachable on the role gate alone.
const nonPlatformAdminPaths = adminNav
  .filter((section) => section.label !== 'Platform')
  .flatMap((section) => section.children)
  .map((c) => c.path);

// `window.location.pathname` alone never contains a query string, and an
// admin entity-config path now legitimately carries `?tab=` (§6: the tab is
// a query param). Comparing the full URL is strictly STRONGER than the old
// pathname-only check: it now also proves the right tab landed, not merely
// the right page.
const currentUrl = () => window.location.pathname + window.location.search;

// `EnvironmentRequestList` passes no `defaultSort` to `useServerGrid`, so it
// falls back to that endpoint's own resolved default (created_at desc) and
// `useServerGrid` writes the RESOLVED sort back into the URL on mount (a
// pre-existing, deliberate feature — a shared link then shows the sort that
// is actually applied, not silently omit it). That happens on this branch
// too, unrelated to §6/the tab work: `git diff` against this branch's base
// touches neither `EnvironmentRequestList.tsx` nor `useServerGrid.ts`. The
// stronger `currentUrl()` check below is correct to catch it — it is a real
// part of "where did we land" — so it is named here rather than loosening
// the check for every path to tolerate it.
const EXPECTED_LANDING_OVERRIDES: Record<string, string> = {
  '/environment-requests': '/environment-requests?sort_by=created_at&sort_dir=desc',
};

describe('every nav item resolves to a real route', () => {
  afterEach(() => document.body.replaceChildren());

  it.each(appPaths)('app path %s does not 404', async (path) => {
    renderAppAt(path, { role: 'Admin' });
    // Wait for the SHELL, not the page: the whole Routes tree sits under one
    // top-level <Suspense>, so a bare 404-absence check resolves trivially
    // while the lazy page's chunk is still loading (the fallback spinner has
    // no "page not found" text either) — before the page has had a chance to
    // render or crash. "EnvManager" is AppLayout's own brand link, not lazy,
    // so waiting for it means the page (and any throw it made) has already
    // been decided in the same commit.
    await screen.findByText('EnvManager', {}, { timeout: 4000 });
    expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument();
    // AppLayout's ErrorBoundary wraps only the Outlet, so a page that throws
    // still renders a non-404 shell at the right URL — the fallback's own
    // copy is the only thing that tells the two apart.
    expect(screen.queryByText('Something went wrong.')).not.toBeInTheDocument();
    // still on the requested path — no guard bounced us to /dashboard
    expect(currentUrl()).toBe(EXPECTED_LANDING_OVERRIDES[path] ?? path);
  });

  it.each(adminPaths)('admin path %s renders inside the admin shell', async (path) => {
    renderAppAt(path, { role: 'Admin', is_master_admin: true });
    expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Something went wrong.')).not.toBeInTheDocument();
    expect(currentUrl()).toBe(path);
  });

  it.each(nonPlatformAdminPaths)(
    'admin path %s renders inside the admin shell for a plain Admin (not master)',
    async (path) => {
      renderAppAt(path, { role: 'Admin', is_master_admin: false });
      expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
      expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument();
      expect(screen.queryByText('Something went wrong.')).not.toBeInTheDocument();
      expect(currentUrl()).toBe(path);
    }
  );

  it('a Developer can still open a user group page, inside the admin shell', async () => {
    renderAppAt('/admin/user-groups/3', { role: 'Developer' });
    expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(currentUrl()).toBe('/admin/user-groups/3');
  });

  it('a Developer is bounced from an Admin-only admin page', async () => {
    renderAppAt('/admin/users', { role: 'Developer' });
    await waitFor(() => expect(currentUrl()).toBe('/dashboard'));
  });
});
