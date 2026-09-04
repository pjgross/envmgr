import { describe, expect, it } from 'vitest';
import { adminNav, visibleAdminNav } from '../adminNavConfig';
import { ENTITY_CONFIG_PAGES, entityConfigPage, entityTabPath, type AdminEntity } from '../../pages/admin/entityConfigTabs';
import type { NavUser } from '../navConfig';

const regular: NavUser = { role: 'Developer', is_master_admin: false };
const admin: NavUser = { role: 'Admin', is_master_admin: false };
const masterOnly: NavUser = { role: 'Viewer', is_master_admin: true };

const sections = (u: NavUser | null) => visibleAdminNav(u).map((s) => s.label);
const items = (u: NavUser | null, section: string) =>
  visibleAdminNav(u).find((s) => s.label === section)?.children.map((c) => c.label) ?? [];

describe('adminNav', () => {
  it('shows every section but Platform to an Admin', () => {
    expect(sections(admin)).toEqual([
      'Organisation', 'Environments', 'Bookings', 'Releases', 'Delivery', 'Integrations',
    ]);
  });

  it('shows only Platform to a master admin who is not role Admin', () => {
    expect(sections(masterOnly)).toEqual(['Platform']);
    expect(items(masterOnly, 'Platform')).toEqual(['Tenants']);
  });

  it('keeps User groups readable by a regular user — the page was never Admin-gated', () => {
    // B3a: reads are open to any tenant member; only writes are Admin. A
    // Developer following a group link from a project must still land somewhere.
    expect(sections(regular)).toEqual(['Organisation']);
    expect(items(regular, 'Organisation')).toEqual(['User groups']);
  });

  it('lists the Environments section with its own tabs first, then the Environment requests page', () => {
    expect(items(admin, 'Environments')).toEqual([
      'Tiers', 'Naming policy', 'Decommissioning', 'Custom fields', 'Environment requests',
    ]);
  });

  it('lists the Bookings section in ENTITY_CONFIG_PAGES order', () => {
    expect(items(admin, 'Bookings')).toEqual(['Booking types', 'Lifecycle', 'Custom fields']);
  });

  it('lists the Releases section in the agreed order with Templates first', () => {
    expect(items(admin, 'Releases')).toEqual([
      'Templates', 'Gate types', 'Rollback policy', 'Event types', 'Lifecycle', 'Custom fields',
      'Scope-change rules', 'RAID settings', 'Release scope items',
    ]);
  });

  it('lists the Delivery section as one page item per entity, then Component types', () => {
    expect(items(admin, 'Delivery')).toEqual([
      'Change requests', 'Builds', 'Deployments', 'Incidents', 'Systems', 'Subsystems', 'Component types',
    ]);
  });

  it('points every entity-tab item at a tab that exists in ENTITY_CONFIG_PAGES', () => {
    const known = new Set(
      ENTITY_CONFIG_PAGES.flatMap((p) => p.tabs.map((t) => entityTabPath(p.entity, t.key)))
    );
    const standalone = new Set([
      '/admin/releases/templates', '/admin/releases/scope-change-rules', '/admin/releases/raid',
    ]);
    // Query form, not `/admin/<entity>/<tab>` (§6: the tab is a query param,
    // not a path segment) — `entityTabPath` emits `?tab=`.
    const entityPaths = adminNav
      .flatMap((s) => s.children)
      .map((c) => c.path)
      .filter((p) => /^\/admin\/[a-z-]+\?tab=[a-z-]+$/.test(p) && !standalone.has(p));
    // Keep this guard. Without it, a regex that matches nothing (as the old
    // segment-form pattern now does) makes `entityPaths` empty, the loop
    // below runs zero times, and the test passes vacuously — exactly how
    // this went unnoticed for two review rounds. A test that can pass by
    // checking nothing is worse than no test.
    expect(entityPaths.length).toBeGreaterThan(10);
    for (const p of entityPaths) expect(known.has(p), p).toBe(true);
  });

  it('gives every item a description for the hub', () => {
    for (const s of adminNav) for (const c of s.children) expect(c.description, c.label).toBeTruthy();
  });

  it('has no duplicate paths', () => {
    const paths = adminNav.flatMap((s) => s.children.map((c) => c.path));
    expect(new Set(paths).size).toBe(paths.length);
  });

  // The defect this branch fixes: the drawer hand-wrote its own labels/order
  // for a section's tabs, and it drifted from ENTITY_CONFIG_PAGES — wrong
  // label ("Lifecycle & decommissioning" vs "Decommissioning"), wrong order,
  // and one entity's tabs split across two sections. Both of the tests below
  // fail against the pre-fix, hand-written adminNav (see the report for
  // proof) and pass now that the drawer is generated from the table.
  describe('sections built from an entity\'s tabs equal ENTITY_CONFIG_PAGES for that entity', () => {
    const cases: { section: string; entity: AdminEntity }[] = [
      { section: 'Environments', entity: 'environments' },
      { section: 'Bookings', entity: 'bookings' },
      { section: 'Releases', entity: 'releases' },
    ];

    it.each(cases)('$section matches the $entity tab table exactly', ({ section, entity }) => {
      const page = entityConfigPage(entity)!;
      const expectedPaths = page.tabs.map((t) => entityTabPath(entity, t.key));
      const expectedLabels = page.tabs.map((t) => t.label);
      const expectedDescriptions = page.tabs.map((t) => t.description);

      const sectionChildren = visibleAdminNav(admin).find((s) => s.label === section)!.children;
      const entityChildren = sectionChildren.filter((c) => expectedPaths.includes(c.path));

      expect(entityChildren.map((c) => c.path)).toEqual(expectedPaths);
      expect(entityChildren.map((c) => c.label)).toEqual(expectedLabels);
      expect(entityChildren.map((c) => c.description)).toEqual(expectedDescriptions);
    });
  });

  it('never splits one entity\'s configuration tabs across two drawer sections', () => {
    for (const page of ENTITY_CONFIG_PAGES) {
      const paths = new Set(page.tabs.map((t) => entityTabPath(page.entity, t.key)));
      const sectionsContainingIt = adminNav.filter((s) => s.children.some((c) => paths.has(c.path)));
      expect(sectionsContainingIt.length, `${page.entity}: ${sectionsContainingIt.map((s) => s.label).join(', ')}`).toBeLessThanOrEqual(1);
    }
  });
});
