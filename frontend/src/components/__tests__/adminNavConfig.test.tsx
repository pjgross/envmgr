import { describe, expect, it } from 'vitest';
import { adminNav, visibleAdminNav } from '../adminNavConfig';
import { ENTITY_CONFIG_PAGES, entityTabPath } from '../../pages/admin/entityConfigTabs';
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

  it('lists the Releases section in the agreed order with Templates first', () => {
    expect(items(admin, 'Releases')).toEqual([
      'Templates', 'Gate types', 'Rollback policy', 'Event types', 'Lifecycle',
      'Scope-change rules', 'RAID settings', 'Custom fields', 'Scope item fields',
    ]);
  });

  it('points every entity-tab item at a tab that exists in ENTITY_CONFIG_PAGES', () => {
    const known = new Set(
      ENTITY_CONFIG_PAGES.flatMap((p) => p.tabs.map((t) => entityTabPath(p.entity, t.key)))
    );
    const standalone = new Set([
      '/admin/releases/templates', '/admin/releases/scope-change-rules', '/admin/releases/raid',
    ]);
    const entityPaths = adminNav
      .flatMap((s) => s.children)
      .map((c) => c.path)
      .filter((p) => /^\/admin\/[a-z-]+\/[a-z-]+$/.test(p) && !standalone.has(p));
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
});
