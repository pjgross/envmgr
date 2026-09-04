import { describe, expect, it } from 'vitest';
import { ROUTE_META, breadcrumbsFor } from '../routeMeta';

describe('breadcrumbsFor', () => {
  it('walks parents to the root', () => {
    expect(breadcrumbsFor('/admin/environments')).toEqual([
      { label: 'Administration', to: '/admin' },
      { label: 'Environments' },
    ]);
  });

  it('leaves the last crumb unlinked', () => {
    const crumbs = breadcrumbsFor('/environments');
    expect(crumbs[crumbs.length - 1].to).toBeUndefined();
  });

  it('matches a dynamic segment against its pattern', () => {
    expect(breadcrumbsFor('/environments/42').map((c) => c.label)).toEqual([
      'Environments',
      'Environment',
    ]);
  });

  it('returns nothing for a path it does not know', () => {
    // A breadcrumb trail that guesses is worse than none: it would state a
    // parent that may not exist.
    expect(breadcrumbsFor('/nonsense/path')).toEqual([]);
  });

  it('prefers a literal route over a colliding dynamic one', () => {
    // /environments/:id would otherwise match "compare" as an :id.
    expect(breadcrumbsFor('/environments/compare').map((c) => c.label)).toEqual([
      'Compare environments',
    ]);
    // /releases/:id would otherwise match "new" as an :id.
    expect(breadcrumbsFor('/releases/new').map((c) => c.label)).toEqual(['Releases', 'New release']);
  });

  it('resolves a DYNAMIC parent against the concrete pathname, not the raw pattern', () => {
    // /incidents/:id/edit's parent is /incidents/:id — the only dynamic
    // `parent` in the table. A crumb linking to the literal pattern string
    // would navigate to `/incidents/:id`, whose detail page then fetches
    // `id === ':id'` → NaN.
    expect(breadcrumbsFor('/incidents/5/edit')).toEqual([
      { label: 'Incidents', to: '/incidents' },
      { label: 'Incident', to: '/incidents/5' },
      { label: 'Edit incident' },
    ]);
  });
});

describe('ROUTE_META', () => {
  it('every parent is itself a known pattern', () => {
    for (const [pattern, meta] of Object.entries(ROUTE_META)) {
      if (meta.parent) {
        expect(ROUTE_META[meta.parent], `${pattern}'s parent ${meta.parent}`).toBeDefined();
      }
    }
  });

  it('holds no dynamic data', () => {
    // §6: the map is static. A label containing a template placeholder would
    // mean someone started resolving entity names in here.
    for (const meta of Object.values(ROUTE_META)) {
      expect(meta.label).not.toMatch(/[${}]/);
    }
  });
});
