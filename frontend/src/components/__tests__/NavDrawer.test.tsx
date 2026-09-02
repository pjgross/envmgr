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
    expect(screen.getByRole('button', { name: 'Releases', expanded: true })).not.toHaveClass('Mui-selected');
    await userEvent.click(calendar);
    expect(onNavigate).toHaveBeenCalledWith('/releases/calendar');
  });
});
