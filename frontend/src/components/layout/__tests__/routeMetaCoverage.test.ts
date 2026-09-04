import { describe, expect, it } from 'vitest';
// The REAL file, as text — same primitive as tabMechanism.test.ts, deliberately
// not a hand-maintained duplicate of App.tsx's route list, which is exactly
// what would let a new route drift out of sync with this guard.
import appSource from '../../../App.tsx?raw';
import { ROUTE_META } from '../routeMeta';

/**
 * Routes that legitimately have no breadcrumb/document.title entry:
 *  - `/login` sits outside the authenticated shell PageHeader/DetailPageHeader
 *    live in.
 *  - `/` and `*` are bare redirects/NotFound, never a page with a header.
 *  - `/bookings` is a redirect to `/bookings/calendar`, never rendered itself.
 *  - `/admin/:entity` and `/admin/:entity/:tab` are react-router CATCH-ALLS —
 *    the real per-entity pages they resolve to (`/admin/environments`, …) are
 *    generated into ROUTE_META from the same ENTITY_CONFIG_PAGES source that
 *    drives the catch-all itself (see the `adminEntityRoutes` comment above),
 *    so they are covered structurally rather than by a literal key here.
 */
const ALLOWED_WITHOUT_ROUTE_META = new Set(['/login', '/', '*', '/bookings', '/admin/:entity', '/admin/:entity/:tab']);

const ADMIN_BLOCK_RE = /<Route path="\/admin" element=\{<Outlet \/>\}>([\s\S]*?)<\/Route>/;

/**
 * Every route pathname App.tsx registers, resolved to the same absolute,
 * `:param`-style form ROUTE_META keys on. Every admin child route is declared
 * with a path RELATIVE to `/admin` (the only nested <Route> block in the
 * file); everything else is declared absolute already.
 */
function allAppRoutePaths(source: string): string[] {
  const adminBlockMatch = source.match(ADMIN_BLOCK_RE);
  if (!adminBlockMatch) {
    throw new Error('admin route block not found — App.tsx\'s <Route path="/admin"> shape changed');
  }
  const adminBlock = adminBlockMatch[1];
  const outsideAdminBlock = source.slice(0, adminBlockMatch.index) + source.slice(adminBlockMatch.index! + adminBlockMatch[0].length);

  const absolutePaths = [...outsideAdminBlock.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]);
  const adminChildPaths = [...adminBlock.matchAll(/<Route path="([^"]+)"/g)].map((m) => `/admin/${m[1]}`);
  const adminHasIndex = /<Route index /.test(adminBlock);

  return [...absolutePaths, ...(adminHasIndex ? ['/admin'] : []), ...adminChildPaths];
}

describe('ROUTE_META covers every route App.tsx registers', () => {
  const paths = allAppRoutePaths(appSource);

  // Non-vacuity: if the regex above ever stops matching anything (a JSX
  // reformat, an attribute-order change), the walk below would pass over an
  // empty list and prove nothing — exactly the failure mode that let a
  // regression through earlier in this branch (see the report).
  it('found a realistic number of routes to walk', () => {
    expect(paths.length).toBeGreaterThan(40);
  });

  it.each(paths.filter((p) => !ALLOWED_WITHOUT_ROUTE_META.has(p)))(
    '%s has a ROUTE_META entry',
    (path) => {
      expect(ROUTE_META[path], `${path} is missing from ROUTE_META (or add it to ALLOWED_WITHOUT_ROUTE_META, with a reason)`).toBeDefined();
    },
  );

  it('every allowlisted route is still one App.tsx actually registers', () => {
    // An allowlist entry for a route that stopped existing would keep passing
    // forever while checking nothing — this is the guard on the guard.
    for (const allowed of ALLOWED_WITHOUT_ROUTE_META) {
      expect(paths, `${allowed} is allowlisted but no longer a real route`).toContain(allowed);
    }
  });
});
