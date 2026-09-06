import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import PirActionList from '../PirActionList';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/pirService', () => ({ pirService: { listActions: vi.fn() } }));

import { pirService } from '../../../services/pirService';

function renderPirActionList() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/pir-actions']}>
        <PirActionList />
      </MemoryRouter>
    </Provider>
  );
}

describe('PirActionList — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(pirService.listActions).mockRejectedValueOnce(new Error('Upstream is unavailable'));

    renderPirActionList();

    // getByRole('alert') is ambiguous here — the page also renders a
    // permanent informational advisory with role="alert".
    await waitFor(() => expect(screen.getByText('Upstream is unavailable')).toBeInTheDocument());
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No PIR actions match these filters.')).not.toBeInTheDocument();
  });
});
