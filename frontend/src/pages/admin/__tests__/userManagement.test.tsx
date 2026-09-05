/**
 * Frontend IA PR 5 — measured at 1024px: this table fits with the dev
 * tenant's `admin@demo.com` and overflows the page by 112px with
 * `christopher.fetherstonhaugh@global-payments-platform.example.com`. An
 * email address is a single unbreakable token, so the table cannot shrink
 * below it and, with no scroll container, the DOCUMENT widens instead.
 * jsdom performs no layout, so this asserts the structure that confines it.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UserManagement from '../UserManagement';
import tenantAdminReducer from '../../../store/tenantAdminSlice';
import { tenantAdminService } from '../../../services/tenantAdminService';
import type { UserResponse } from '../../../types';

vi.mock('../../../services/tenantAdminService', () => ({
  tenantAdminService: { listUsers: vi.fn() },
}));

const user = (id: number, username: string, email: string): UserResponse => ({
  id,
  username,
  email,
  role: 'Developer',
  tenant_id: 1,
  is_active: true,
  is_master_admin: false,
  created_at: '2026-09-05T00:00:00Z',
  notification_preferences: null,
});

// One ordinary corporate address — the value is the point of the test, not
// decoration. This is the string that produced the measured 112px overflow.
const users = [
  user(1, 'admin', 'admin@demo.com'),
  user(
    2,
    'christopher.fetherstonhaugh',
    'christopher.fetherstonhaugh@global-payments-platform.example.com',
  ),
];

const renderUserManagement = () => {
  const store = configureStore({
    reducer: { tenantAdmin: tenantAdminReducer },
    preloadedState: {
      tenantAdmin: { users, usersTotal: users.length, settings: null, loading: false, error: null },
    },
  } as Parameters<typeof configureStore>[0]);
  return render(
    <Provider store={store}>
      <SnackbarProvider>
        <MemoryRouter initialEntries={['/admin/users']}>
          <UserManagement />
        </MemoryRouter>
      </SnackbarProvider>
    </Provider>,
  );
};

describe('UserManagement scrolls inside itself', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // The mount-time fetch must resolve, or its rejection replaces the
    // preloaded rows with an error state and the table never renders.
    vi.mocked(tenantAdminService.listUsers).mockResolvedValue({
      rows: users,
      total: users.length,
    } as Awaited<ReturnType<typeof tenantAdminService.listUsers>>);
  });

  it('renders its table inside a TableContainer, so a long email scrolls the table and not the page', async () => {
    renderUserManagement();

    const table = await screen.findByRole('table');
    expect(
      table.closest('.MuiTableContainer-root'),
      'the users table has no scroll container: one ordinary corporate email address widens the DOCUMENT, ' +
        'and the fixed drawer then covers the Username column',
    ).not.toBeNull();
  });

  it('still renders every user', async () => {
    renderUserManagement();

    expect(await screen.findByText('admin')).toBeInTheDocument();
    expect(screen.getByText('christopher.fetherstonhaugh')).toBeInTheDocument();
  });
});
