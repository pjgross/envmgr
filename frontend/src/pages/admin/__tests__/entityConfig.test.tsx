import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import EntityConfig from '../EntityConfig';

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

function Path() {
  return <div data-testid="path">{useLocation().pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/:entity/:tab" element={<><EntityConfig /><Path /></>} />
        <Route path="/admin/:entity" element={<><EntityConfig /><Path /></>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('EntityConfig', () => {
  it('renders the tab named in the URL', () => {
    renderAt('/admin/environments/naming-policy');
    expect(screen.getByRole('tab', { name: 'Naming policy' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('naming-policy')).toBeInTheDocument();
  });

  it('redirects a bare entity path to its first tab', () => {
    renderAt('/admin/bookings');
    expect(screen.getByTestId('path')).toHaveTextContent('/admin/bookings/fields');
    expect(screen.getByText('fields:booking')).toBeInTheDocument();
  });

  it('redirects an unknown tab to the first tab', () => {
    renderAt('/admin/releases/nope');
    expect(screen.getByTestId('path')).toHaveTextContent('/admin/releases/fields');
  });

  it('changes the URL when a tab is clicked', async () => {
    renderAt('/admin/releases/fields');
    await userEvent.click(screen.getByRole('tab', { name: 'Gate types' }));
    expect(screen.getByTestId('path')).toHaveTextContent('/admin/releases/gate-types');
    expect(screen.getByText('gate-types')).toBeInTheDocument();
  });

  it('shows Booking types as its own tab, not stacked above Lifecycle', () => {
    renderAt('/admin/bookings/types');
    expect(screen.getByText('booking-types')).toBeInTheDocument();
    expect(screen.queryByText('lifecycle:booking')).not.toBeInTheDocument();
  });

  it('renders not-found for an unknown entity', () => {
    renderAt('/admin/widgets/fields');
    expect(screen.getByText(/not found/i)).toBeInTheDocument();
  });
});
