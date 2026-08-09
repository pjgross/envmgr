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
import { afterEach, describe, expect, it, vi } from 'vitest';
import { addWorkingDays, localDayAsUtc } from '../dates';

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

/**
 * THE START OF THE COUNT, which every test above supplies as a UTC midnight and
 * the real caller supplies as `new Date()` — an instant.
 *
 * These run under a real non-UTC timezone rather than a UTC one, because that
 * is the only condition in which the bug exists at all: with `TZ=UTC` the local
 * and UTC calendar dates are identical and the wrong reading passes.
 */
describe('localDayAsUtc', () => {
  // `vi.stubEnv` rather than assigning `process.env.TZ`: this is a browser-ish
  // test environment with no node types, and `vi.unstubAllEnvs` restores the
  // original whatever the test did. Node re-reads TZ on the next `Date`, which
  // is what makes a mid-run change take effect at all.
  const withTz = (tz: string, fn: () => void) => {
    vi.stubEnv('TZ', tz);
    try {
      fn();
    } finally {
      vi.unstubAllEnvs();
    }
  };

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it('reads the day the READER is in, not the day UTC is in', () => {
    // 20:00Z on the 11th is already 08:00 on the 12th in Auckland (UTC+12).
    withTz('Pacific/Auckland', () => {
      expect(iso(localDayAsUtc(new Date('2026-08-11T20:00:00Z')))).toBe('2026-08-12');
    });
    // …and 20:00Z on the 11th is still the 11th in Los Angeles (UTC-7).
    withTz('America/Los_Angeles', () => {
      expect(iso(localDayAsUtc(new Date('2026-08-11T20:00:00Z')))).toBe('2026-08-11');
    });
  });

  it('lands on UTC midnight, which is what the deadline is written as', () => {
    withTz('Pacific/Auckland', () => {
      const day = localDayAsUtc(new Date('2026-08-11T20:00:00Z'));
      expect(day.toISOString()).toBe('2026-08-12T00:00:00.000Z');
    });
  });

  it('gives the escalation default the three working days it promises', () => {
    // The end-to-end shape of the defect: a user in Auckland opening the
    // Escalate dialog on Wednesday morning had the count started from Tuesday
    // (UTC), and was offered a deadline one working day earlier than the
    // helper text says.
    withTz('Pacific/Auckland', () => {
      vi.useFakeTimers();
      // Wednesday 12 August, 08:00 local — Tuesday 11th, 20:00Z.
      vi.setSystemTime(new Date('2026-08-11T20:00:00Z'));

      const fromTheInstant = iso(addWorkingDays(new Date(), 3));
      const fromTheReadersDay = iso(addWorkingDays(localDayAsUtc(new Date()), 3));

      expect(fromTheReadersDay).toBe('2026-08-17'); // Thu, Fri, Mon
      expect(fromTheInstant).toBe('2026-08-14'); // the day the bug offered
    });
  });
});
