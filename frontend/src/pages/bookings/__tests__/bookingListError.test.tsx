import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingList from '../BookingList';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn(),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { bookingService } from '../../../services/bookingService';

function renderBookingList() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/bookings']}>
        <BookingList />
      </MemoryRouter>
    </Provider>
  );
}

describe('BookingList — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(bookingService.listBookings).mockRejectedValueOnce(
      new Error('Upstream is unavailable')
    );

    renderBookingList();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Upstream is unavailable')
    );
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No bookings match these filters.')).not.toBeInTheDocument();
  });
});
