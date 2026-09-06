import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import InfrastructureComponentList from '../InfrastructureComponentList';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/infrastructureComponentService', () => ({
  infrastructureComponentService: {
    listComponents: vi.fn(),
    deleteComponent: vi.fn(),
  },
}));

import { infrastructureComponentService } from '../../../services/infrastructureComponentService';

function renderInfrastructureComponentList() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/infrastructure']}>
        <InfrastructureComponentList />
      </MemoryRouter>
    </Provider>
  );
}

describe('InfrastructureComponentList — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(infrastructureComponentService.listComponents).mockRejectedValueOnce(
      new Error('Upstream is unavailable')
    );

    renderInfrastructureComponentList();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Upstream is unavailable')
    );
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No hosts match these filters.')).not.toBeInTheDocument();
  });
});
