import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import TenantSettings from '../TenantSettings';
import tenantAdminReducer from '../../../store/tenantAdminSlice';
import { tenantAdminService } from '../../../services/tenantAdminService';

vi.mock('../../../services/tenantAdminService', () => ({
  tenantAdminService: { getSettings: vi.fn(), updateSettings: vi.fn() },
}));

describe('TenantSettings', () => {
  it('shows name and slug read-only, with the JSON editor collapsed under Advanced', async () => {
    vi.mocked(tenantAdminService.getSettings).mockResolvedValue({
      id: 1, name: 'Demo Org', slug: 'demo', settings: { flag: true },
    } as never);
    render(
      <Provider store={configureStore({ reducer: { tenantAdmin: tenantAdminReducer } })}>
        <TenantSettings />
      </Provider>
    );
    expect(await screen.findByLabelText('Name')).toHaveValue('Demo Org');
    expect(screen.getByLabelText('Name')).toHaveAttribute('readonly');
    expect(screen.getByLabelText('Slug')).toHaveValue('demo');
    expect(screen.queryByLabelText('Custom settings (JSON)')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /advanced/i }));
    expect(screen.getByLabelText('Custom settings (JSON)')).toHaveValue(JSON.stringify({ flag: true }, null, 2));
  });

  it('still saves the JSON document', async () => {
    vi.mocked(tenantAdminService.getSettings).mockResolvedValue({ id: 1, name: 'D', slug: 'd', settings: {} } as never);
    vi.mocked(tenantAdminService.updateSettings).mockResolvedValue({ id: 1, name: 'D', slug: 'd', settings: { a: 1 } } as never);
    render(
      <Provider store={configureStore({ reducer: { tenantAdmin: tenantAdminReducer } })}>
        <TenantSettings />
      </Provider>
    );
    await screen.findByLabelText('Name');
    await userEvent.click(screen.getByRole('button', { name: /advanced/i }));
    const editor = screen.getByLabelText('Custom settings (JSON)');
    await userEvent.clear(editor);
    await userEvent.type(editor, '{{"a": 1}');
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(tenantAdminService.updateSettings).toHaveBeenCalledWith({ a: 1 });
    expect(await screen.findByText('Settings saved')).toBeInTheDocument();
  });
});
