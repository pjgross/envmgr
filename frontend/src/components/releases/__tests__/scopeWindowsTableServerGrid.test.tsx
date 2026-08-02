import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import ScopeWindowsTable, { scopeWindowColumns } from '../ScopeWindowsTable';

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    list: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn().mockResolvedValue({ rows: [{ id: 7, name: 'Payments' }], total: 1 }),
  },
}));

import { releaseService } from '../../../services/releaseService';

function renderTable(initialEntry = '/releases/scope-windows') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ScopeWindowsTable showSystemFilter />
      </MemoryRouter>
    </Provider>
  );
}

function lastListParams() {
  const calls = vi.mocked(releaseService.list).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('ScopeWindowsTable server-side wiring', () => {
  it('opens on cutoff-ascending with the actionable filter, without the URL saying so', async () => {
    // GET /releases declares created_at/desc; this table declares its own
    // default. Nothing in the URL says either.
    renderTable();
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({
        limit: 25,
        offset: 0,
        sort_by: 'scope_deadline',
        sort_dir: 'asc',
        scope_window: 'actionable',
      })
    );
  });

  it('sends scope_window=all when the toggle is switched', async () => {
    renderTable();
    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    // Both toggle groups have an "All" button, so scope to this one.
    const group = screen.getByRole('group', { name: 'Window filter' });
    await userEvent.click(within(group).getByRole('button', { name: 'All' }));

    await waitFor(() => expect(lastListParams()).toMatchObject({ scope_window: 'all' }));
  });

  it('keeps the sortable cutoff ordering on scope_deadline and marks the computed columns unsortable', () => {
    const byField = Object.fromEntries(scopeWindowColumns.map((c) => [c.field, c]));
    // GET /releases whitelists scope_deadline. Both window_status and
    // days_to_cutoff are computed in Python after the query, so neither is
    // backed by a column the database could order by. A column left sortable
    // on a non-whitelisted field would resolve to the endpoint default
    // *silently* — the header would look live and quietly return created_at.
    expect(byField.scope_deadline).toBeDefined();
    expect(byField.scope_deadline.sortable).not.toBe(false);
    expect(byField.window_status.sortable).toBe(false);
    expect(byField.window_status.renderHeader).toBeDefined();
    expect(byField.days_to_cutoff.sortable).toBe(false);
    expect(byField.days_to_cutoff.renderHeader).toBeDefined();
  });

  it('renders the day count in the days-to-cutoff column', () => {
    const col = scopeWindowColumns.find((c) => c.field === 'days_to_cutoff');
    const cell = col!.renderCell!({ row: { days_to_cutoff: -3 } } as never);
    render(<>{cell}</>);
    expect(screen.getByText('-3')).toBeInTheDocument();
  });

  it('sends the kind filter to the server rather than filtering in the browser', async () => {
    renderTable();
    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    const group = screen.getByRole('group', { name: 'Release kind filter' });
    await userEvent.click(within(group).getByRole('button', { name: 'Enterprise' }));

    await waitFor(() => expect(lastListParams()).toMatchObject({ release_kind: 'enterprise' }));
  });

  it('pins the table to a fixed systemId without exposing the picker', async () => {
    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/systems/7']}>
          <ScopeWindowsTable systemId={7} showSystemFilter />
        </MemoryRouter>
      </Provider>
    );

    await waitFor(() => expect(lastListParams()).toMatchObject({ system_id: 7 }));
    expect(screen.queryByRole('combobox', { name: 'System' })).not.toBeInTheDocument();
  });
});
