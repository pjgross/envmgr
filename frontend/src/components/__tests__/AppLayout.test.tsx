import { configureStore } from '@reduxjs/toolkit';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AppLayout from '../AppLayout';
import { EntityTabRedirect } from '../../App';
import authReducer, { setCredentials } from '../../store/authSlice';
import uiReducer from '../../store/uiSlice';
import myWorkReducer from '../../store/myWorkSlice';

vi.mock('../../services/authService', () => ({ authService: { logout: vi.fn() } }));
// AppLayout now calls useMyWork() on every render (Task 7's nav badge) — an
// unmocked call would hit the real axios instance from inside jsdom. Resolve
// with an all-empty, non-failed response: none of this file's assertions are
// about the badge, so the quietest possible answer (no badge rendered at
// all) is the right one here.
vi.mock('../../services/myWorkService', () => ({
  myWorkService: {
    getMyWork: vi.fn().mockResolvedValue({
      as_of: '2026-09-04T00:00:00Z',
      queues: {
        environment_requests: { count: 0, items: [], failed: false },
        contentions: { count: 0, items: [], failed: false },
        decommissions: { count: 0, items: [], failed: false },
        pir_actions: { count: 0, items: [], failed: false },
        incidents: { count: 0, items: [], failed: false },
      },
    }),
  },
}));

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
    reducer: { auth: authReducer, ui: uiReducer, myWork: myWorkReducer },
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

  it('lets the Administration heading navigate back to the admin hub, by keyboard', async () => {
    renderAt('/admin/users');
    const heading = screen.getByRole('link', { name: 'Administration' });
    heading.focus();
    expect(heading).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByTestId('path')).toHaveTextContent('/admin');
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

  it('opens a pre-collapsed group on an admin deep link once the user arrives after mount', async () => {
    // On a hard reload the store hydrates with user: null while auth resolves
    // (authInitialized: false). entries — and so which group holds the current
    // route — depends on `user`; visibleAdminNav(null) has no Releases group at
    // all, so the first pass of the group-opening effect cannot open anything.
    // It must re-run once the real user lands, or a group the admin had
    // collapsed earlier stays collapsed forever on this route.
    //
    // The collapsed state is seeded directly into the store's preloadedState,
    // not via localStorage — uiSlice's initialState is built once at module
    // load (see uiSlice.test.ts), so writing localStorage from inside a test
    // body never reaches a reducer whose initial state was already computed.
    const store = configureStore({
      reducer: { auth: authReducer, ui: uiReducer, myWork: myWorkReducer },
      preloadedState: {
        auth: {
          user: null,
          token: 't',
          isAuthenticated: true,
          authInitialized: false,
          impersonationMode: false,
          impersonatingTenant: null,
          originalToken: null,
        },
        ui: {
          themeMode: 'system' as const,
          navOpenGroups: { 'admin:Releases': false },
          lastAppRoute: '/dashboard',
        },
      },
    });
    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/admin/releases/gate-types']}>
          <Routes>
            <Route element={<AppLayout />}>
              {/* The real redirect (App.tsx), nested exactly where App.tsx
                  nests it: inside AppLayout, ahead of the catch-all. Without
                  it this deep link — the pre-Task-2 segment form — is a URL
                  the real app would never actually show AppLayout at, since
                  it redirects to the query form before AppLayout's own
                  group-opening logic ever sees it. */}
              <Route path="/admin/:entity/:tab" element={<EntityTabRedirect />} />
              <Route path="*" element={<Probe />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </Provider>
    );
    expect(screen.queryByRole('button', { name: 'Gate types' })).not.toBeInTheDocument();

    store.dispatch(
      setCredentials({
        user: { id: 1, username: 'admin', email: 'a@x', role: 'Admin', tenant_id: 1, is_master_admin: false },
        token: 't',
      })
    );

    expect(await screen.findByRole('button', { name: 'Gate types' })).toBeInTheDocument();
  });
});
