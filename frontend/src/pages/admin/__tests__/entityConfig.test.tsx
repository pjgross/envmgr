import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import EntityConfig from '../EntityConfig';
import { EntityTabRedirect } from '../../../App';

// Panels own their own tests; here only the routing/tab wiring is under test.
vi.mock('../../../components/admin/CustomFieldDefinitionManager', () => ({
  default: ({ entityType }: { entityType: string }) => <div>fields:{entityType}</div>,
}));
vi.mock('../../../components/admin/LifecycleTemplatesPanel', () => ({
  default: ({ entityType }: { entityType: string }) => <div>lifecycle:{entityType}</div>,
}));
vi.mock('../../../components/admin/BookingTypesPanel', () => ({ default: () => <div>booking-types</div> }));
vi.mock('../../../components/admin/ReleaseEventTypesPanel', () => ({ default: () => <div>event-types</div> }));
vi.mock('../../../components/admin/GateTypesPanel', () => ({ default: () => <div>gate-types</div> }));
vi.mock('../../../components/admin/RollbackPolicyPanel', () => ({ default: () => <div>rollback-policy</div> }));
vi.mock('../../../components/admin/EnvironmentTiersPanel', () => ({ default: () => <div>tiers</div> }));
vi.mock('../../../components/admin/EnvironmentNamingPolicyPanel', () => ({ default: () => <div>naming-policy</div> }));
vi.mock('../../../components/admin/EnvironmentLifecyclePanel', () => ({ default: () => <div>lifecycle-policy</div> }));

// Full URL, not just pathname: the tab lives in `?tab=` (§6), so a test that
// only reads `.pathname` cannot tell "landed on the right tab" from "landed
// on the right page with the wrong tab" — exactly the distinction most of
// the cases below exist to make.
function Path() {
  const location = useLocation();
  return <div data-testid="path">{location.pathname + location.search}</div>;
}

// Mirrors App.tsx's real admin route pair, in the same order: the segment
// form is a REDIRECT (`EntityTabRedirect`, imported from App.tsx itself, not
// reimplemented here), and the query form renders the page.
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/:entity/:tab" element={<><EntityTabRedirect /><Path /></>} />
        <Route path="/admin/:entity" element={<><EntityConfig /><Path /></>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('EntityConfig', () => {
  it('renders the tab named in the URL', () => {
    renderAt('/admin/environments?tab=naming-policy');
    expect(screen.getByRole('tab', { name: 'Naming policy' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('naming-policy')).toBeInTheDocument();
  });

  it('renders the first tab when no ?tab= is present, without changing the URL', () => {
    // No redirect here (deliberately — `useUrlTab` already falls back, and a
    // redirect would fight it): the URL a bare entity path was requested at
    // is exactly the URL it stays at.
    renderAt('/admin/bookings');
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/admin\/bookings$/);
    expect(screen.getByRole('tab', { name: 'Booking types' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('booking-types')).toBeInTheDocument();
  });

  it('falls back to the first tab when ?tab= names an unknown tab, without rewriting the URL', () => {
    // Same fallback as above, this time with a `?tab=` value present but not
    // in the entity's vocabulary (e.g. a bookmark taken before a tab was
    // renamed). `useUrlTab` renders the default; it does not correct the URL.
    renderAt('/admin/releases?tab=nope');
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/admin\/releases\?tab=nope$/);
    expect(screen.getByRole('tab', { name: 'Gate types' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('gate-types')).toBeInTheDocument();
  });

  it('changes the URL when a tab is clicked', async () => {
    renderAt('/admin/releases?tab=fields');
    await userEvent.click(screen.getByRole('tab', { name: 'Gate types' }));
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/admin\/releases\?tab=gate-types$/);
    expect(screen.getByText('gate-types')).toBeInTheDocument();
  });

  it('the old /admin/:entity/:tab form redirects to the query form', () => {
    // The compatibility promise this PR makes: PR 1's segment URLs still
    // resolve, landing on the exact query-form URL `entityTabPath` would
    // have produced for the same entity and tab.
    renderAt('/admin/releases/fields');
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/admin\/releases\?tab=fields$/);
    expect(screen.getByText('fields:release')).toBeInTheDocument();
  });

  it('shows Booking types as its own tab, not stacked above Lifecycle', () => {
    renderAt('/admin/bookings?tab=types');
    expect(screen.getByText('booking-types')).toBeInTheDocument();
    expect(screen.queryByText('lifecycle:booking')).not.toBeInTheDocument();
  });

  it('renders not-found for an unknown entity', () => {
    renderAt('/admin/widgets?tab=fields');
    expect(screen.getByText(/not found/i)).toBeInTheDocument();
  });
});
