import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import EscalationWorklist from '../EscalationWorklist';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/contentionService', () => ({
  contentionService: { list: vi.fn(), decide: vi.fn(), escalate: vi.fn() },
}));

import { contentionService } from '../../../services/contentionService';

function renderEscalationWorklist() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/contentions']}>
        <EscalationWorklist />
      </MemoryRouter>
    </Provider>
  );
}

describe('EscalationWorklist — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(contentionService.list).mockRejectedValueOnce(new Error('Upstream is unavailable'));

    renderEscalationWorklist();

    // getByRole('alert') is ambiguous here — the page also renders a
    // permanent informational advisory with role="alert".
    await waitFor(() => expect(screen.getByText('Upstream is unavailable')).toBeInTheDocument());
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No contentions match these filters.')).not.toBeInTheDocument();
  });
});
