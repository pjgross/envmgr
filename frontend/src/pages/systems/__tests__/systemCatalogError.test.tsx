import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import SystemCatalog from '../SystemCatalog';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn(),
    deleteSystem: vi.fn(),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

import { systemService } from '../../../services/systemService';

function renderSystemCatalog() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/systems']}>
        <SystemCatalog />
      </MemoryRouter>
    </Provider>
  );
}

describe('SystemCatalog — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(systemService.listSystems).mockRejectedValueOnce(
      new Error('Upstream is unavailable')
    );

    renderSystemCatalog();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Upstream is unavailable')
    );
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No systems match these filters.')).not.toBeInTheDocument();
  });
});
