import { describe, expect, it, vi, afterEach } from 'vitest';

import { formatExpiry } from '../dates';

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
});
