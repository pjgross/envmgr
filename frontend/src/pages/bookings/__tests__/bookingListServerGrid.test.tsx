import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingList, { bookingColumns } from '../BookingList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
  },
}));

// Also unmocked-network-free: BookingList fetches custom field definitions on
// mount alongside the booking page itself.
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

import { bookingService } from '../../../services/bookingService';

function renderBookingList(url = '/bookings') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <BookingList />
      </MemoryRouter>
    </Provider>
  );
}

function lastListParams() {
  const calls = vi.mocked(bookingService.listBookings).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('BookingList server-side grid', () => {
  it('sends paging, sorting and the wire-named status filter', async () => {
    renderBookingList('/bookings?page=2&sort_by=end_date&sort_dir=desc&booking_status=approved');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved',
    }));
  });

  it('marks joined and computed columns unsortable', () => {
    // GET /bookings/ whitelists start_date, end_date and status only.
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));

    expect(byField.start_date.sortable).not.toBe(false);
    expect(byField.end_date.sortable).not.toBe(false);
    expect(byField.status.sortable).not.toBe(false);

    ['project_name', 'environment_name', 'booked_by_username', 'booking_type_id', 'conflicts', 'actions']
      .forEach((field) => expect(byField[field].sortable).toBe(false));
  });

  it('disables the column filter, which would filter only the loaded page', async () => {
    // Raw DataGrid gates the column-menu Filter item on this prop alone, not
    // on whether a toolbar is rendered. Without it the menu filters the 25
    // loaded rows while the footer shows the server total.
    //
    // The menu-icon button is only revealed by CSS on hover in a real
    // browser, so jsdom's computed style hides it from `getAllByRole`'s
    // accessible-name matching (an element the name algorithm treats as
    // hidden resolves to an empty accessible name, which a `name` matcher
    // can never match) even with `hidden: true`. Find it by its `aria-label`
    // attribute directly instead — `hidden: true` still gets it into the
    // query's search space at all, which is what matters here.
    renderBookingList();
    await waitFor(() => expect(lastListParams()).toBeDefined());

    const menuButtons = screen
      .getAllByRole('button', { hidden: true })
      .filter((b) => b.getAttribute('aria-label') === 'Menu');
    expect(menuButtons.length).toBeGreaterThan(0);
    fireEvent.click(menuButtons[0]);

    const menu = await screen.findByRole('menu', { hidden: true });
    const filterItem = within(menu)
      .getAllByRole('menuitem', { hidden: true })
      .find((item) => /filter/i.test(item.textContent ?? ''));
    expect(filterItem).toBeUndefined();
  });
});
