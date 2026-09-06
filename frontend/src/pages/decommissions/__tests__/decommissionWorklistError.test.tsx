import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import DecommissionWorklist from '../DecommissionWorklist';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/decommissionService', () => ({
  decommissionService: {
    getForEnvironment: vi.fn(),
    initiate: vi.fn(),
    requestExtension: vi.fn(),
    decideExtension: vi.fn(),
    signAttestation: vi.fn(),
    tearDown: vi.fn(),
    cancel: vi.fn(),
    listSteps: vi.fn(),
    listWorklist: vi.fn(),
  },
}));

import { decommissionService } from '../../../services/decommissionService';

function renderDecommissionWorklist() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/decommissions']}>
        <DecommissionWorklist />
      </MemoryRouter>
    </Provider>
  );
}

describe('DecommissionWorklist — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(decommissionService.listWorklist).mockRejectedValueOnce(
      new Error('Upstream is unavailable')
    );

    renderDecommissionWorklist();

    // getByRole('alert') is ambiguous here — the page also renders a
    // permanent informational advisory with role="alert".
    await waitFor(() => expect(screen.getByText('Upstream is unavailable')).toBeInTheDocument());
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No decommissions match these filters.')).not.toBeInTheDocument();
  });
});
