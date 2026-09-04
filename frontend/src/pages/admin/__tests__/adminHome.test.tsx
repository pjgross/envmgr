import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import AdminHome from '../AdminHome';
import authReducer from '../../../store/authSlice';

function renderAs(role: string, isMaster = false) {
  const store = configureStore({
    reducer: { auth: authReducer },
    preloadedState: {
      auth: {
        user: { id: 1, username: 'u', email: 'u@x', role, tenant_id: 1, is_master_admin: isMaster },
        token: 't', isAuthenticated: true, authInitialized: true,
        impersonationMode: false, impersonatingTenant: null, originalToken: null,
      },
    },
  });
  render(<Provider store={store}><MemoryRouter><AdminHome /></MemoryRouter></Provider>);
}

describe('AdminHome', () => {
  it('renders a card per visible section with links to every item', () => {
    renderAs('Admin');
    expect(screen.getByRole('heading', { name: 'Releases' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Naming policy/ })).toHaveAttribute(
      'href', '/admin/environments?tab=naming-policy'
    );
    expect(screen.getByText('Name pattern, required attributes and quarantine grace.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Platform' })).not.toBeInTheDocument();
  });

  it('shows only Platform to a master-only admin', () => {
    renderAs('Viewer', true);
    expect(screen.getByRole('heading', { name: 'Platform' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Organisation' })).not.toBeInTheDocument();
  });
});
