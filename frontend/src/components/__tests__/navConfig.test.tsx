import { describe, expect, it } from 'vitest';
import { visibleNavGroups, type NavUser } from '../navConfig';

const regular: NavUser = { role: 'User', is_master_admin: false };
const admin: NavUser = { role: 'Admin', is_master_admin: false };
const masterOnly: NavUser = { role: 'User', is_master_admin: true };

const labels = (user: NavUser) => visibleNavGroups(user).map((g) => g.label);
const childLabels = (user: NavUser, group: string) =>
  visibleNavGroups(user).find((g) => g.label === group)?.children?.map((c) => c.label) ?? [];

describe('visibleNavGroups', () => {
  it('shows the four workflow groups to a regular user, no Administration', () => {
    expect(labels(regular)).toEqual([
      'Insights',
      'Environment Definition',
      'Environment Management',
      'Release Management',
    ]);
  });

  it('shows the contention worklist to a regular user', () => {
    // The worklist is readable by any tenant member, deliberately: a decider
    // needs to see the queue they are in, and everyone else needs to see that a
    // clash they are party to has been put to someone. Who may ANSWER one is a
    // different question, settled on the row.
    expect(childLabels(regular, 'Environment Management')).toContain(
      'Contention Escalations'
    );
  });

  it('hides Release Templates from a regular user', () => {
    expect(childLabels(regular, 'Release Management')).not.toContain('Release Templates');
  });

  it('shows Administration (without Platform Admin) to an Admin, plus Release Templates', () => {
    expect(labels(admin)).toContain('Administration');
    expect(childLabels(admin, 'Release Management')).toContain('Release Templates');
    const adminChildren = childLabels(admin, 'Administration');
    expect(adminChildren).toContain('Users');
    expect(adminChildren).toContain('API Keys');
    expect(adminChildren).not.toContain('Platform Admin');
  });

  it('shows Administration with only Platform Admin to a master-admin who is not role Admin', () => {
    expect(childLabels(masterOnly, 'Administration')).toEqual(['Platform Admin']);
  });

  it('marks Insights as default-open', () => {
    const insights = visibleNavGroups(regular).find((g) => g.label === 'Insights');
    expect(insights?.defaultOpen).toBe(true);
  });

  it('handles a null user by showing only non-privileged groups', () => {
    expect(visibleNavGroups(null).map((g) => g.label)).not.toContain('Administration');
  });
});
