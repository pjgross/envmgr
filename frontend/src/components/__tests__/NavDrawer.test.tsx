import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import NavDrawer, { activeItemPath, groupContaining, isPathActive } from '../NavDrawer';
import type { NavEntry } from '../navConfig';

const tree: NavEntry[] = [
  { label: 'Dashboard', path: '/dashboard' },
  {
    label: 'Releases',
    icon: <span />,
    children: [
      { label: 'Releases', path: '/releases' },
      { label: 'Calendar', path: '/releases/calendar' },
    ],
  },
];

describe('path helpers', () => {
  it('matches exact and nested paths, not prefixes of a longer segment', () => {
    expect(isPathActive('/releases', '/releases')).toBe(true);
    expect(isPathActive('/releases/7', '/releases')).toBe(true);
    expect(isPathActive('/releases-archive', '/releases')).toBe(false);
  });

  it('picks the longest matching item so siblings do not both light up', () => {
    expect(activeItemPath(tree, '/releases/calendar')).toBe('/releases/calendar');
    expect(activeItemPath(tree, '/releases/7')).toBe('/releases');
    expect(activeItemPath(tree, '/nowhere')).toBeUndefined();
  });

  it('names the group holding the active item', () => {
    expect(groupContaining(tree, '/releases/calendar')).toBe('Releases');
    expect(groupContaining(tree, '/dashboard')).toBeUndefined();
  });

  // An admin entity-config item's own path carries `?tab=<key>` (§6) — the
  // three behaviours a QUERY-SUBSET match must give, all found the hard way:
  // NavDrawer never highlighted any admin entity-config item, and never
  // auto-opened a collapsed group containing one, because `isPathActive` was
  // a plain string comparison with no notion of a query string at all.
  describe('query-subset matching', () => {
    it('matches an item whose own path has a query when current carries the same param and value', () => {
      expect(isPathActive('/admin/releases?tab=gate-types', '/admin/releases?tab=gate-types')).toBe(
        true
      );
    });

    it('does NOT match the same item when current names a different tab — a different tab is a different item', () => {
      expect(isPathActive('/admin/releases?tab=fields', '/admin/releases?tab=gate-types')).toBe(
        false
      );
    });

    it('matches a plain item (no query in its own path) even when current carries an UNRELATED param', () => {
      // EnvironmentRequestList writes its own resolved default sort back into
      // the URL on mount (`?sort_by=...&sort_dir=...`) — nothing to do with
      // navigation. Full-URL equality would mean its drawer item can never
      // highlight; a subset match correctly ignores a param the item itself
      // never declared.
      expect(
        isPathActive('/environment-requests?sort_by=created_at&sort_dir=desc', '/environment-requests')
      ).toBe(true);
    });

    it('the longest-match tiebreak still prefers the more specific (query-bearing) item when both match', () => {
      const withQueryTiebreak: NavEntry[] = [
        { label: 'Environment requests', path: '/environment-requests' },
        { label: 'Environment requests (details)', path: '/environment-requests?tab=details' },
      ];
      // Only the plain item's pathname-only match applies: the query-bearing
      // sibling requires ?tab=details, which is absent.
      expect(activeItemPath(withQueryTiebreak, '/environment-requests?sort_by=created_at')).toBe(
        '/environment-requests'
      );
      // Both match once the URL actually carries tab=details — the longer,
      // more specific string wins, exactly as `/releases/calendar` wins over
      // `/releases` today.
      expect(activeItemPath(withQueryTiebreak, '/environment-requests?tab=details')).toBe(
        '/environment-requests?tab=details'
      );
    });
  });
});

describe('NavDrawer', () => {
  it('renders items, hides children of a closed group, and toggles', async () => {
    const onToggleGroup = vi.fn();
    const onNavigate = vi.fn();
    const { rerender } = render(
      <NavDrawer
        entries={tree}
        currentPath="/dashboard"
        isGroupOpen={() => false}
        onToggleGroup={onToggleGroup}
        onNavigate={onNavigate}
      />
    );
    expect(screen.getByRole('button', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Calendar' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Releases', expanded: false }));
    expect(onToggleGroup).toHaveBeenCalledWith('Releases');

    rerender(
      <NavDrawer
        entries={tree}
        currentPath="/releases/calendar"
        isGroupOpen={() => true}
        onToggleGroup={onToggleGroup}
        onNavigate={onNavigate}
      />
    );
    const calendar = screen.getByRole('button', { name: 'Calendar' });
    expect(calendar).toHaveClass('Mui-selected');
    // Two buttons are named "Releases": the group header (carries aria-expanded)
    // and the sibling child item at /releases (does not) — the latter is the one
    // this assertion is about: proving the longest-match rule keeps it unselected
    // while /releases/calendar is active.
    const releasesButtons = screen.getAllByRole('button', { name: 'Releases' });
    const releasesChild = releasesButtons.find((b) => !b.hasAttribute('aria-expanded'));
    expect(releasesChild).toBeDefined();
    expect(releasesChild).not.toHaveClass('Mui-selected');
    await userEvent.click(calendar);
    expect(onNavigate).toHaveBeenCalledWith('/releases/calendar');
  });
});
