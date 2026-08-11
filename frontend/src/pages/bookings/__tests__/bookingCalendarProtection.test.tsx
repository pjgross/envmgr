import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { bookingToEvent } from '../BookingCalendar';
import { PROTECTED_MARKER } from '../../../constants/protection';

import BookingScheduleGantt from '../../../components/BookingScheduleGantt';
import type { BookingResponse } from '../../../types/booking';

// PROTECTED_MARKER contains parentheses, which `new RegExp` would read as a
// capture group — /Protected (hard) reservation/ matches "Protected hard
// reservation" and nothing else. Escaped once, here.
const MARKER_RE = new RegExp(PROTECTED_MARKER.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');


/**
 * Both surfaces already spend colour on STATUS_COLORS, and a border alone is
 * not accessible — so the protected marker is paired with WORDS, and the words
 * are what these tests assert.
 *
 * FullCalendar's own DOM is not worth asserting against here: the calendar's
 * mapping is the whole behaviour, so `bookingToEvent` is exported and tested
 * directly. jsdom could not render A3's DataGrid gap column at all (a scratch
 * render gave 1 row, 3 cells, 0 icons); a test that silently asserts nothing is
 * worse than one that admits it tests the mapping.
 */

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn(),
  },
}));

import { bookingService } from '../../../services/bookingService';

const HARD_BOOKING = {
  id: 1,
  environment_id: 10,
  environment_name: 'SIT',
  project_name: 'Release 24.4',
  start_date: '2026-09-01T09:00:00Z',
  end_date: '2026-09-05T17:00:00Z',
  status: 'approved',
  protection_level: 'hard',
} as unknown as BookingResponse;

const SOFT_BOOKING = {
  ...HARD_BOOKING,
  id: 2,
  protection_level: 'soft',
} as unknown as BookingResponse;

describe('BookingCalendar — protected bookings', () => {
  it('marks a protected booking with text, not colour alone', () => {
    const event = bookingToEvent(HARD_BOOKING);
    expect(event.title).toContain(PROTECTED_MARKER);
    expect(event.classNames).toContain('booking-protected');
    // The status colour is untouched — the marker is additive, not a
    // recolouring that would collide with the status legend.
    expect(event.backgroundColor).toBe('#4caf50');
  });

  it('leaves a soft booking unmarked', () => {
    const event = bookingToEvent(SOFT_BOOKING);
    expect(event.title).not.toContain(PROTECTED_MARKER);
    expect(event.classNames ?? []).not.toContain('booking-protected');
  });

  it('leaves a booking whose level the response did not carry unmarked', () => {
    // `protection_level` is optional on BookingResponse; absent means "not
    // said", and marking it protected would be a guess in the direction that
    // matters most.
    const event = bookingToEvent({ ...HARD_BOOKING, protection_level: undefined });
    expect(event.title).not.toContain(PROTECTED_MARKER);
  });
});

describe('BookingScheduleGantt — protected bookings', () => {
  const ENVS = [{ id: 10, name: 'SIT' }];

  it('labels a protected bar in words', async () => {
    vi.mocked(bookingService.listBookings).mockResolvedValue({
      rows: [HARD_BOOKING],
      total: 1,
    });
    render(<BookingScheduleGantt envs={ENVS} scheduledStart={new Date('2026-09-02T09:00:00Z')} />);

    // The bar carries the words as its accessible name: MUI's Tooltip renders
    // its title only on hover, so a tooltip-only marker is invisible to a
    // screen reader and to this test alike.
    await waitFor(() =>
      expect(screen.getByLabelText(MARKER_RE)).toBeInTheDocument()
    );
  });

  it('leaves a soft bar unlabelled', async () => {
    vi.mocked(bookingService.listBookings).mockResolvedValue({
      rows: [SOFT_BOOKING],
      total: 1,
    });
    render(<BookingScheduleGantt envs={ENVS} scheduledStart={new Date('2026-09-02T09:00:00Z')} />);

    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    expect(screen.queryByLabelText(MARKER_RE)).toBeNull();
  });
});
