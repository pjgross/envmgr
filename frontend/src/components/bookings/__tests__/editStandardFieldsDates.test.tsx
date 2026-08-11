import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import EditStandardFieldsDialog from '../EditStandardFieldsDialog';
import type { BookingResponse } from '../../../types/booking';

/**
 * BEFORE B4 both fields were `type="date"`, so a 09:00–13:00 booking rendered
 * as "2026-09-01" twice and saving sent 00:00–00:00 — a ZERO-LENGTH booking,
 * which then conflicts with nothing at all, because overlap is
 * `start < end AND end > start` and a zero-length interval satisfies neither.
 * Rare while bookings are day-scale by habit; routine the moment B4 ships
 * half-day presets.
 */

vi.mock('../../../hooks/useAllProjects', () => ({
  useAllProjects: () => ({ projects: [], truncated: false }),
}));

// The rendered value is LOCAL time, so the expectations below are only stable
// with the zone pinned. UTC keeps the fixture's `09:00:00Z` readable as 09:00.
beforeAll(() => {
  vi.stubEnv('TZ', 'UTC');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const saver = vi.fn();
const onSaved = vi.fn();

const BOOKING = {
  id: 9101,
  environment_id: 9201,
  environment_name: 'SIT',
  project_name: 'Regression sweep',
  project_id: null,
  project_name_link: null,
  booking_type_id: 5,
  booking_request_id: 9301,
  start_date: '2026-09-01T09:00:00Z',
  end_date: '2026-09-01T13:00:00Z',
  status: 'draft',
  notes: null,
  exclusive_use: false,
  context_tag: 'none',
  custom_fields: null,
  // Every field this dialog can send must be editable, or `handleSave` drops
  // it from the payload and the second test asserts nothing.
  standard_field_permissions: {
    project_name: { editable: true },
    start_date: { editable: true },
    end_date: { editable: true },
    booking_type: { editable: true },
    notes: { editable: true },
    exclusive_use: { editable: true },
    context_tag: { editable: true },
  },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any as BookingResponse;

function renderDialog() {
  return render(
    <Provider store={store}>
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[{ id: 5, name: 'Standard' }]}
        onClose={vi.fn()}
        onSaved={onSaved}
        saver={saver}
      />
    </Provider>
  );
}

describe('EditStandardFieldsDialog — booking times', () => {
  beforeEach(() => {
    saver.mockReset().mockResolvedValue(BOOKING);
    onSaved.mockReset();
  });

  it('renders the time of day, not just the date', async () => {
    renderDialog();
    expect(screen.getByLabelText(/start date/i)).toHaveValue('2026-09-01T09:00');
    expect(screen.getByLabelText(/end date/i)).toHaveValue('2026-09-01T13:00');
  });

  it('saves a window that is not zero-length', async () => {
    renderDialog();
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(saver).toHaveBeenCalled());
    const payload = saver.mock.calls[0][0] as { start_date: string; end_date: string };
    expect(payload.start_date).not.toBe(payload.end_date);
    expect(new Date(payload.end_date).getTime()).toBeGreaterThan(
      new Date(payload.start_date).getTime()
    );
    // And the exact instants, not merely "end after start": truncating to
    // midnight would also satisfy the inequality above if only one of the two
    // dates moved.
    expect(payload.start_date).toBe('2026-09-01T09:00:00.000Z');
    expect(payload.end_date).toBe('2026-09-01T13:00:00.000Z');
  });
});
