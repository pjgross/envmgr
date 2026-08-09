/**
 * `addWorkingDays` — the default response window on a contention escalation.
 *
 * A4's escalation names a person AND a deadline, and the deadline defaults to
 * three WORKING days ahead. Three calendar days would land on a Saturday for
 * every contention raised on a Wednesday, Thursday or Friday — i.e. more than
 * half the week — and hand the named owner a deadline nobody is at work for.
 *
 * UTC throughout, matching `expiryDayDelta`: the date input the default feeds
 * yields "YYYY-MM-DD", the app writes deadlines at `T00:00:00Z`, and reading
 * the weekday in local time would shift the skip by a day either side of UTC.
 */
import { describe, expect, it } from 'vitest';
import { addWorkingDays } from '../dates';

const utc = (iso: string) => new Date(`${iso}T00:00:00Z`);
const iso = (d: Date) => d.toISOString().slice(0, 10);

describe('addWorkingDays', () => {
  it('skips the weekend when three days would cross it', () => {
    // Wednesday + 3 working days = Thu, Fri, Mon.
    expect(iso(addWorkingDays(utc('2026-08-05'), 3))).toBe('2026-08-10');
  });

  it('counts plain weekdays without skipping anything', () => {
    // Monday + 3 = Thursday, no weekend in the way.
    expect(iso(addWorkingDays(utc('2026-08-10'), 3))).toBe('2026-08-13');
  });

  it('starts counting from the next working day when asked on a Friday', () => {
    // Friday + 3 = Mon, Tue, Wed.
    expect(iso(addWorkingDays(utc('2026-08-07'), 3))).toBe('2026-08-12');
  });

  it('gives a Saturday and a Sunday the same answer as the Friday before them', () => {
    // Nobody is at work over the weekend, so a contention raised on Saturday
    // has exactly as many working days ahead of it as one raised on Friday.
    const friday = iso(addWorkingDays(utc('2026-08-07'), 3));
    expect(iso(addWorkingDays(utc('2026-08-08'), 3))).toBe(friday);
    expect(iso(addWorkingDays(utc('2026-08-09'), 3))).toBe(friday);
  });

  it('never lands on a weekend, whichever day of the week it starts from', () => {
    // The property, not seven more examples: the whole point of the helper is
    // that its answer is a working day.
    for (let offset = 0; offset < 14; offset += 1) {
      const start = new Date(Date.UTC(2026, 7, 1 + offset));
      const day = addWorkingDays(start, 3).getUTCDay();
      expect(day).not.toBe(0);
      expect(day).not.toBe(6);
    }
  });

  it('does not mutate the date it was given', () => {
    const start = utc('2026-08-05');
    addWorkingDays(start, 3);
    expect(iso(start)).toBe('2026-08-05');
  });
});
