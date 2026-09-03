import { describe, expect, it } from 'vitest';
import { appNav, isNavGroup, visibleAppNav, type NavUser } from '../navConfig';

const regular: NavUser = { role: 'Developer', is_master_admin: false };
const admin: NavUser = { role: 'Admin', is_master_admin: false };
const masterOnly: NavUser = { role: 'Viewer', is_master_admin: true };

const topLabels = (u: NavUser | null) => visibleAppNav(u).map((e) => e.label);
const children = (u: NavUser | null, group: string) => {
  const g = visibleAppNav(u).find((e) => e.label === group);
  return g && isNavGroup(g) ? g.children.map((c) => c.label) : [];
};

describe('appNav', () => {
  it('shows Dashboard then the four workflow groups to a regular user, no Administration', () => {
    expect(topLabels(regular)).toEqual(['Dashboard', 'Catalogue', 'Bookings', 'Releases', 'Insights']);
  });

  it('files Projects and Environment groups under Bookings for every role', () => {
    // Both are readable by any tenant member and used when booking — they are
    // not administration, whatever directory their page components once lived in.
    expect(children(regular, 'Bookings')).toEqual([
      'Calendar', 'List', 'Environment requests', 'Change requests', 'Projects',
      'Environment groups', 'Contentions', 'Decommissions',
    ]);
  });

  it('lists the catalogue and release groups in the agreed order', () => {
    expect(children(regular, 'Catalogue')).toEqual([
      'Systems', 'Environments', 'Hosts', 'Compare environments', 'Import',
    ]);
    expect(children(regular, 'Releases')).toEqual([
      'List', 'Calendar', 'Timeline', 'Scope windows', 'Analytics', 'Builds',
      'Deployments', 'Incidents', 'PIR actions',
    ]);
    expect(children(regular, 'Insights')).toEqual(['DORA metrics', 'Environment health']);
  });

  it('never lists Release templates in the app tree — it is admin configuration', () => {
    const all = appNav.flatMap((e) => (isNavGroup(e) ? e.children : [e])).map((i) => i.label);
    expect(all).not.toContain('Release templates');
  });

  it('shows the Administration entry to an Admin and to a master admin, not to a regular user', () => {
    expect(topLabels(admin)).toContain('Administration');
    expect(topLabels(masterOnly)).toContain('Administration');
    expect(topLabels(regular)).not.toContain('Administration');
    expect(topLabels(null)).not.toContain('Administration');
  });

  it('points Administration at /admin', () => {
    const entry = visibleAppNav(admin).find((e) => e.label === 'Administration');
    expect(entry && !isNavGroup(entry) ? entry.path : undefined).toBe('/admin');
  });

  it('uses sentence case and no group-prefixed labels', () => {
    for (const entry of appNav) {
      const labels = isNavGroup(entry) ? entry.children.map((c) => c.label) : [entry.label];
      for (const label of labels) {
        expect(label).not.toMatch(/—/);
        // second word onward is lower case unless it is an acronym (DORA, PIR)
        const words = label.split(' ').slice(1);
        for (const w of words) expect(w === w.toUpperCase() || w === w.toLowerCase()).toBe(true);
      }
    }
  });
});
