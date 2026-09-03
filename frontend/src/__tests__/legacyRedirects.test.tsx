import { waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LEGACY_REDIRECTS } from '../components/legacyRedirects';
import { renderAppAt } from '../test/renderApp';

vi.mock('../services/authService', () => ({
  authService: { getCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn() },
}));
// See navRoutes.test.tsx for why these two GETs need an object, not the
// empty-array default: EnvironmentNamingPolicyPanel and RaidSettings both
// throw on render otherwise (real page bugs — reported, not papered over).
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

const fill = (pattern: string) => pattern.replace(/:[a-zA-Z]+/g, '42');

describe('legacy paths redirect', () => {
  afterEach(() => document.body.replaceChildren());

  it.each(LEGACY_REDIRECTS.map((r) => [r.from, r.to]))('%s → %s', async (from, to) => {
    renderAppAt(fill(from), { role: 'Admin', is_master_admin: true });
    await waitFor(() => expect(window.location.pathname).toBe(fill(to)), { timeout: 4000 });
  });

  it('no source file navigates to a legacy path', () => {
    // Deliberately `.tsx` only, not `.ts` — some legacy UI paths and live
    // backend API paths are the same string (e.g. `services/tenantAdminService.ts`
    // holds '/tenant/settings' and '/tenant/users' as endpoints, and
    // `services/userGroupService.ts` holds '/tenant/groups'). Widening this to
    // `.ts` would flag those real API calls as offenders.
    const files = import.meta.glob('../**/*.tsx', { as: 'raw', eager: true }) as Record<string, string>;
    const offenders: string[] = [];
    for (const [file, src] of Object.entries(files)) {
      if (file.includes('__tests__') || file.includes('legacyRedirects')) continue;
      for (const r of LEGACY_REDIRECTS) {
        const literal = r.from.replace(/\/:[a-zA-Z]+/g, '');
        // The three forms a real navigation literal actually takes, plus a
        // template-literal interpolation start (`` `${literal}/${ `` ``) —
        // built by concatenation so the backtick escaping stays legible.
        // A bare `${literal}/` substring check would also match unrelated,
        // longer endpoints that happen to share this prefix (e.g. a comment
        // mentioning `/tenant/users/lite` would false-flag against the
        // legacy path `/tenant/users`), which is why this is whole-literal,
        // not prefix, matching.
        const singleQuoted = "'" + literal + "'";
        const doubleQuoted = '"' + literal + '"';
        const backticked = '`' + literal + '`';
        const interpolated = '`' + literal + '/${';
        if (
          src.includes(singleQuoted) ||
          src.includes(doubleQuoted) ||
          src.includes(backticked) ||
          src.includes(interpolated)
        ) {
          offenders.push(`${file}: ${literal}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
