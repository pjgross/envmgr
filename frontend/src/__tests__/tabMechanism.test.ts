import { describe, expect, it } from 'vitest';
import { entityTabPath } from '../pages/admin/entityConfigTabs';

// The REAL files, as text. `?raw` is Vite's own primitive (typed by
// `vite/client`) — deliberately NOT `node:fs` + `__dirname`, which work at
// runtime but are untyped in this package's tsconfig (no `@types/node`,
// `lib: ES2020`) and fail `tsc --noEmit`. The same note is on
// `src/pages/projects/__tests__/projectDetailGapLink.test.tsx`, which is
// where this pattern is established.
import appSource from '../App.tsx?raw';
import releaseDetailSource from '../pages/releases/ReleaseDetail.tsx?raw';
import environmentDetailSource from '../pages/environments/EnvironmentDetail.tsx?raw';
import systemDetailSource from '../pages/systems/SystemDetail.tsx?raw';
import enterpriseTabsSource from '../pages/releases/enterprise/EnterpriseTabs.tsx?raw';
import entityConfigSource from '../pages/admin/EntityConfig.tsx?raw';

/**
 * §6: the tab is a query param, everywhere. PR 1 shipped the admin config tab
 * as a route segment; converting it left the segment form reachable as a
 * redirect, so a page could quietly go back to addressing tabs that way and
 * every behavioural test would stay green. Hence a structural sweep.
 */
describe('one tab mechanism', () => {
  it('entityTabPath emits a query param, not a path segment', () => {
    expect(entityTabPath('environments', 'naming-policy')).toBe(
      '/admin/environments?tab=naming-policy',
    );
  });

  it('every tab strip with more than six tabs is scrollable', () => {
    // §6. ReleaseDetail rendered an eleventh tab entirely off-screen until C4
    // caught it, and only a synthetic click could reach it — automation
    // scrolls its target into view, so no test noticed and no mouse could.
    const strips: Array<[string, string]> = [
      ['ReleaseDetail', releaseDetailSource],
      ['EnvironmentDetail', environmentDetailSource],
      ['SystemDetail', systemDetailSource],
      ['EnterpriseTabs', enterpriseTabsSource],
      ['EntityConfig', entityConfigSource],
    ];
    for (const [name, src] of strips) {
      expect(src, `${name} renders a tab strip that cannot scroll`).toMatch(
        /variant="scrollable"/,
      );
    }
  });

  it('no route pattern addresses a tab as a path segment', () => {
    // Every `path="…"` that ends in a :tab segment, EXCEPT the one that renders
    // a redirect. Matching on the file is deliberate: this is a rule about the
    // route table's shape, which no rendered assertion can observe.
    const tabSegmentRoutes = [...appSource.matchAll(/path="([^"]*:tab)"/g)].map((m) => m[1]);
    expect(tabSegmentRoutes).toEqual([':entity/:tab']);
    // …and that one must be a redirect, not a page. The redirect itself is a
    // named `EntityTabRedirect` component (it needs `useParams` to build the
    // query-form target, which an inline `<Navigate>` on this line can't
    // read), so the route-registration line names the REDIRECT component,
    // never the page component — matching on "Redirect" rather than
    // "Navigate" for that reason.
    const redirectLine = appSource
      .split('\n')
      .find((l) => l.includes('path=":entity/:tab"'));
    expect(redirectLine).toMatch(/Redirect/);
    expect(redirectLine).not.toMatch(/EntityConfig/);
  });
});
