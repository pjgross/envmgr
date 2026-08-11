import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingList, { apiProtection, bookingColumns, buildCustomFieldColumns } from '../BookingList';
import { PROTECTION_FILTER_NONE } from '../../../constants/protection';
import sortWhitelists from '../../../constants/sortWhitelists.json';
import type { CustomFieldDefinition } from '../../../types/customField';

// Same no-HTTP wiring as bookingListServerGrid.test.tsx: this file is about
// the protection filter, column and sort key, not about server responses.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
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

describe('BookingList — B4 protection filter', () => {
  it('omits the key entirely for no selection', () => {
    expect(apiProtection('any')).toBeUndefined();
    expect(apiProtection(undefined)).toBeUndefined();
    expect(apiProtection('all')).toBeUndefined(); // hand-edited URL
    expect(apiProtection('')).toBeUndefined(); // never emit ?protection=
  });

  it('passes the two real values through', () => {
    expect(apiProtection('soft')).toBe('soft');
    expect(apiProtection('hard')).toBe('hard');
  });

  it('does not use `all` anywhere in its vocabulary', () => {
    // buildParams' own sentinel. Two toggle states building byte-identical
    // params is the bug that stopped ScopeWindowsTable ever refetching.
    expect(PROTECTION_FILTER_NONE).toBe('any');
  });

  it('refetches when the filter changes between its two real values', async () => {
    // Mount-only is not enough: the bug this guards against is two states
    // collapsing to one request, which only a SECOND request can disprove.
    renderBookingList('/bookings?protection=soft');
    await waitFor(() => expect(lastListParams()?.protection).toBe('soft'));
    vi.mocked(bookingService.listBookings).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Protection' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Protected' }));

    await waitFor(() => expect(lastListParams()).toMatchObject({ protection: 'hard', offset: 0 }));
  });

  it('drops the key and refetches when the filter is cleared', async () => {
    renderBookingList('/bookings?protection=hard');
    await waitFor(() => expect(lastListParams()?.protection).toBe('hard'));
    vi.mocked(bookingService.listBookings).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Protection' }));
    const noSelection = await screen.findByRole('option', { name: 'All bookings' });
    // The no-selection option's value is `any` on the wire's own terms — an
    // `all` here would be dropped by buildParams before a request was built,
    // making both toggle states byte-identical.
    expect(noSelection).toHaveAttribute('data-value', 'any');
    await userEvent.click(noSelection);

    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    expect(lastListParams()?.protection).toBeUndefined();
    // And the select shows the cleared state rather than going blank.
    expect(screen.getByRole('combobox', { name: 'Protection' })).toHaveTextContent('All bookings');
  });

  it('reads an unparseable protection value in the URL as no filter', async () => {
    renderBookingList('/bookings?protection=medium');
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    expect(lastListParams()?.protection).toBeUndefined();
    expect(screen.getByRole('combobox', { name: 'Protection' })).toHaveTextContent('All bookings');
  });
});

describe('BookingList — B4 protection column', () => {
  const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));

  it('renders the level by its label, not its wire value', () => {
    const cell = byField.protection_level.renderCell?.({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      row: { protection_level: 'hard' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any) as any;
    expect(cell.props.label).toBe('Protected');
  });

  it('renders nothing rather than guessing when the level is absent', () => {
    // `protection_level` is optional on BookingResponse (the backend defaults
    // it to None because a Booking has no such attribute). Rendering
    // "Preemptible" for an absent value would state as fact something the
    // response never said.
    const cell = byField.protection_level.renderCell?.({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      row: {},
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any) as any;
    expect(cell).toBeNull();
  });

  it('is sortable, and the sort key it uses is whitelisted on both sides', () => {
    // Unlike every other computed-looking column here, this one IS backed by a
    // single column (booking_request.protection_level) and the backend
    // whitelists it. The two whitelists must agree or the sort is a 422.
    expect(byField.protection_level.sortable).not.toBe(false);
    expect(sortWhitelists.bookings.sortable).toContain('protection_level');
  });

  it('has no custom-field column whose field collides with protection_level', () => {
    // The `cf_` namespacing rule — BookingList was namespaced on 2026-08-04
    // precisely because a tenant custom field keyed like a static column
    // silently hid the real one via a persisted visibility entry.
    const defs = [
      { id: 1, field_key: 'protection_level', label: 'Protection level', field_type: 'text' },
    ] as unknown as CustomFieldDefinition[];
    const cfFields = buildCustomFieldColumns(defs).map((c) => c.field);
    const staticFields = bookingColumns.map((c) => c.field);
    expect(cfFields.some((f) => staticFields.includes(f))).toBe(false);
  });
});
