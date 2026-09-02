import { configureStore } from '@reduxjs/toolkit';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AppLayout from '../AppLayout';
import authReducer from '../../store/authSlice';
import uiReducer from '../../store/uiSlice';

vi.mock('../../services/authService', () => ({ authService: { logout: vi.fn() } }));

function Probe() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <div>
      <div data-testid="path">{pathname}</div>
      <button onClick={() => navigate('/releases/calendar')}>go calendar</button>
      <button onClick={() => navigate('/admin/users')}>go admin users</button>
      <button onClick={() => navigate('/projects')}>go projects</button>
    </div>
  );
}

function renderAt(path: string, role = 'Admin', isMaster = false) {
  const store = configureStore({
    reducer: { auth: authReducer, ui: uiReducer },
    preloadedState: {
      auth: {
        user: { id: 1, username: 'admin', email: 'a@x', role, tenant_id: 1, is_master_admin: isMaster },
        token: 't', isAuthenticated: true, authInitialized: true,
        impersonationMode: false, impersonatingTenant: null, originalToken: null,
      },
    },
  });
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="*" element={<Probe />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </Provider>
  );
  return store;
}

describe('AppLayout', () => {
  beforeEach(() => {
    localStorage.clear();
    // jsdom implements no matchMedia at all; AppLayout's useMediaQuery(up('md'))
    // needs one so the drawer renders as the permanent desktop variant instead
    // of a closed, aria-hidden temporary one that hides every button below it.
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  it('opens the group containing the route on NAVIGATION, not only at mount', async () => {
    // The old layout computed open state once in a useState initialiser, so
    // arriving in a group later left it collapsed with nothing selected.
    // "Calendar" also labels a Bookings item, so scope to the Releases group's
    // own container rather than querying the whole drawer for the name.
    renderAt('/dashboard');
    const releasesHeader = screen.getByRole('button', { name: 'Releases', expanded: true });
    const releasesGroup = releasesHeader.parentElement as HTMLElement;
    await userEvent.click(releasesHeader); // collapse it
    expect(within(releasesGroup).queryByRole('button', { name: 'Calendar' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('go calendar'));
    expect(await within(releasesGroup).findByRole('button', { name: 'Calendar' })).toHaveClass('Mui-selected');
  });

  it('persists a collapsed group to localStorage', async () => {
    renderAt('/dashboard');
    await userEvent.click(screen.getByRole('button', { name: 'Catalogue', expanded: true }));
    expect(localStorage.getItem('ui.navOpenGroups')).toContain('"app:Catalogue":false');
  });

  it('swaps to the admin drawer under /admin and back returns to the last app route', async () => {
    renderAt('/projects');
    expect(screen.queryByText('Back to EnvManager')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('go admin users'));
    expect(await screen.findByText('Back to EnvManager')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Catalogue' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Users' })).toHaveClass('Mui-selected');
    await userEvent.click(screen.getByText('Back to EnvManager'));
    expect(screen.getByTestId('path')).toHaveTextContent('/projects');
  });

  it('shows a master-only admin just the Platform section', async () => {
    renderAt('/admin', 'Viewer', true);
    expect(await screen.findByRole('button', { name: 'Platform', expanded: true })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Organisation' })).not.toBeInTheDocument();
  });

  it('makes the app title a link to the dashboard', () => {
    renderAt('/projects');
    expect(screen.getByRole('link', { name: 'EnvManager' })).toHaveAttribute('href', '/dashboard');
  });
});
