import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import EnvironmentRequestList from '../EnvironmentRequestList';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/environmentRequestService', () => ({
  environmentRequestService: {
    listRequests: vi.fn(),
  },
}));

import { environmentRequestService } from '../../../services/environmentRequestService';

function renderEnvironmentRequestList() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/environment-requests']}>
        <EnvironmentRequestList />
      </MemoryRouter>
    </Provider>
  );
}

describe('EnvironmentRequestList — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(environmentRequestService.listRequests).mockRejectedValueOnce(
      new Error('Upstream is unavailable')
    );

    renderEnvironmentRequestList();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Upstream is unavailable')
    );
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(
      screen.queryByText('No environment requests match these filters.')
    ).not.toBeInTheDocument();
  });
});
