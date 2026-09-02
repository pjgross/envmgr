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
// Two GETs need an OBJECT, not the empty-array default, or the page that owns
// them throws during render (a real page bug, not a test artifact — see the
// report):
//  - GET /tenant/environment-naming-policy (EnvironmentNamingPolicyPanel):
//    `[]` is truthy, so the panel's `if (!policy) return` guard is skipped
//    and `setAttributes(policy.required_attributes)` feeds `undefined` to a
//    MUI `multiple` Select, which throws.
//  - GET /tenant/raid-config (RaidSettings): `config.probability_scale` /
//    `impact_scale` are read directly and iterated, which throws on `[]`.
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
    return empty();
  });
  return { default: { get, post: vi.fn(empty), put: vi.fn(empty), patch: vi.fn(empty), delete: vi.fn(empty) } };
});

const appPaths = appNav.flatMap((e) => (isNavGroup(e) ? e.children : [e])).map((i) => i.path);
const adminPaths = adminNav.flatMap((s) => s.children).map((c) => c.path);

describe('every nav item resolves to a real route', () => {
  afterEach(() => document.body.replaceChildren());

  it.each(appPaths)('app path %s does not 404', async (path) => {
    renderAppAt(path, { role: 'Admin' });
    await waitFor(() => expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument(), { timeout: 4000 });
    // still on the requested path — no guard bounced us to /dashboard
    expect(window.location.pathname).toBe(path);
  });

  it.each(adminPaths)('admin path %s renders inside the admin shell', async (path) => {
    renderAppAt(path, { role: 'Admin', is_master_admin: true });
    expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument();
    expect(window.location.pathname).toBe(path);
  });

  it('a Developer can still open a user group page, inside the admin shell', async () => {
    renderAppAt('/admin/user-groups/3', { role: 'Developer' });
    expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/admin/user-groups/3');
  });

  it('a Developer is bounced from an Admin-only admin page', async () => {
    renderAppAt('/admin/users', { role: 'Developer' });
    await waitFor(() => expect(window.location.pathname).toBe('/dashboard'));
  });
});
