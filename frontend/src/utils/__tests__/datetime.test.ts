import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { formatBookingDateTime, toDateTimeLocal } from '../datetime';

// Both helpers render LOCAL time, so the zone has to be pinned or the
// expectations below drift with the runner. UTC keeps `09:00:00Z` readable.
beforeAll(() => {
  vi.stubEnv('TZ', 'UTC');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

describe('toDateTimeLocal', () => {
  it('renders an ISO instant as a datetime-local value in local time', () => {
    expect(toDateTimeLocal('2026-09-01T09:00:00Z')).toBe('2026-09-01T09:00');
  });

  it('pads single-digit months, days, hours and minutes', () => {
    expect(toDateTimeLocal('2026-01-02T03:04:00Z')).toBe('2026-01-02T03:04');
  });

  it('renders an unparseable value as empty rather than "NaN"', () => {
    expect(toDateTimeLocal('not a date')).toBe('');
  });
});

describe('formatBookingDateTime', () => {
  it('shows the time of day for a booking that does not start at midnight', () => {
    // The half-day case B4 makes ordinary: without the time, a 09:00–13:00
    // booking reads as "01/09/2026 → 01/09/2026" — indistinguishable from an
    // all-day booking, and from the zero-length one the edit path used to
    // save.
    const rendered = formatBookingDateTime('2026-09-01T09:00:00Z');
    expect(rendered).toMatch(/09:00/);
    expect(rendered).toMatch(/2026/);
  });

  it('omits a midnight time, so day-scale bookings read as they always have', () => {
    // Every booking made before B4 sits at 00:00, and appending ", 00:00" to
    // all of them is noise that says nothing.
    expect(formatBookingDateTime('2026-09-01T00:00:00Z')).toBe(
      new Date('2026-09-01T00:00:00Z').toLocaleDateString()
    );
  });

  it('renders an unparseable value as an em dash, never "Invalid Date"', () => {
    expect(formatBookingDateTime('not a date')).toBe('—');
  });
});
