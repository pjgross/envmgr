import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BuildList from '../BuildList';

vi.mock('../../../services/buildService', () => ({
  buildService: { list: vi.fn() },
}));

import { buildService } from '../../../services/buildService';

function renderBuildList() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/builds']}>
        <BuildList />
      </MemoryRouter>
    </Provider>
  );
}

describe('BuildList — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    // RTK's miniSerializeError keeps only name/message/stack/code, and an
    // Axios error's `.message` is the generic "Request failed with status
    // code 500" — `response.data.detail` is dropped unless the thunk formats
    // it before rejecting. Rejecting with a plain Error carrying the final
    // text would pass while the app is broken, so this mocks an Axios error
    // SHAPE and asserts the DETAIL reaches the page.
    vi.mocked(buildService.list).mockRejectedValueOnce(
      Object.assign(new Error('Request failed with status code 500'), {
        isAxiosError: true,
        response: { data: { detail: 'Upstream CI is unavailable' } },
      })
    );

    renderBuildList();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Upstream CI is unavailable')
    );
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No builds match these filters.')).not.toBeInTheDocument();
  });
});
