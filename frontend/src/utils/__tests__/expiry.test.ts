import { describe, expect, it, vi, afterEach } from 'vitest';

import { formatExpiry, isExpiryOverdue } from '../dates';

describe('formatExpiry', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('says how long is left rather than making the reader do the arithmetic', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:00Z'));
    expect(formatExpiry('2026-08-16T00:00:00Z')).toBe('in 12 days');
  });

  it('marks an expiry in the past as overdue', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:00Z'));
    expect(formatExpiry('2026-08-01T00:00:00Z')).toBe('overdue by 3 days');
  });

  it('distinguishes "no expiry planned" from "expires today"', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:00Z'));
    // A null expiry is a legitimate state — "no expiry planned" — not a
    // missing value, which is why it does not read as "Not set" and is not
    // what `governance_gap` looks for.
    expect(formatExpiry(null)).toBe('No expiry planned');
    expect(formatExpiry('2026-08-04T12:00:00Z')).toBe('today');
  });

  // The environment form always writes expiries normalised to `T00:00:00Z`.
  // Reading "now" at any time other than exact midnight, a millisecond-based
  // floor of the difference gets the calendar-day delta wrong by one in the
  // overdue direction — these three pin the UTC-calendar-day arithmetic that
  // replaces it, reading at midday rather than at midnight so a regression
  // back to the millisecond version fails them.
  it('reads an expiry of today, checked at midday, as "today"', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
    expect(formatExpiry('2026-08-04T00:00:00Z')).toBe('today');
  });

  it('reads an expiry of yesterday, checked at midday, as overdue by 1 day', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
    expect(formatExpiry('2026-08-03T00:00:00Z')).toBe('overdue by 1 day');
  });

  it('reads an expiry of tomorrow, checked at midday, as in 1 day', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
    expect(formatExpiry('2026-08-05T00:00:00Z')).toBe('in 1 day');
  });
});

describe('isExpiryOverdue', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // These pin the bug this function fixes: the overdue *colour* used to come
  // from a raw instant comparison (new Date(expires_at) < new Date()) while
  // the *label* (formatExpiry, above) used calendar-day arithmetic, so an
  // environment expiring today read "today" in black text while its cell was
  // already red from 00:00Z — label and colour disagreeing for a whole day.
  // isExpiryOverdue now drives both from the same day-delta.

  it('is not overdue on the day of expiry itself, checked right after midnight', () => {
    // The instant-comparison bug's exact failure mode: new Date(iso) < now
    // is already true seconds after 00:00Z on the expiry date.
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:05Z'));
    expect(isExpiryOverdue('2026-08-04T00:00:00Z')).toBe(false);
    expect(formatExpiry('2026-08-04T00:00:00Z')).toBe('today');
  });

  it('is not overdue on the day of expiry, checked at midday', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
    expect(isExpiryOverdue('2026-08-04T00:00:00Z')).toBe(false);
  });

  it('is overdue the day after expiry', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
    expect(isExpiryOverdue('2026-08-03T00:00:00Z')).toBe(true);
  });

  it('is not overdue for a future expiry', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
    expect(isExpiryOverdue('2026-08-05T00:00:00Z')).toBe(false);
  });

  it('is not overdue when there is no expiry — "no expiry planned" is not a governance gap', () => {
    expect(isExpiryOverdue(null)).toBe(false);
    expect(isExpiryOverdue(undefined)).toBe(false);
  });
});
