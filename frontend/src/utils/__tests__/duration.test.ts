import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { addDuration } from '../duration';

// Pinned here rather than in vitest.config.ts: only this file depends on the
// zone, and the DST case below is meaningless in UTC (Node re-reads
// process.env.TZ on each Date operation, verified on the runner rather than
// assumed). `vi.stubEnv` rather than assigning `process.env` directly — this
// package has no @types/node, so a bare `process` reference fails the build
// while the tests still pass, which is the worst of both.
beforeAll(() => {
  vi.stubEnv('TZ', 'Europe/London');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

describe('addDuration', () => {
  it('adds a sub-day duration as minutes', () => {
    const start = new Date('2026-09-01T09:00:00Z');
    expect(addDuration(start, 240).toISOString()).toBe('2026-09-01T13:00:00.000Z');
  });

  it('adds a whole-day multiple as CALENDAR days, so the wall clock holds across DST', () => {
    // Europe/London springs forward at 01:00 on 2026-03-29. Adding 20160
    // minutes as an instant offset would land an hour LATE on the wall clock
    // (the same instant reads 10:00 once the clocks have gone forward);
    // adding 14 calendar days keeps 09:00 at 09:00.
    //
    // This codebase has already paid twice for instant-vs-calendar
    // arithmetic: formatExpiry reported an environment "overdue by 1 day"
    // throughout the day it expired, and SP5a's utilization needed per-date
    // localization to be DST-correct.
    const start = new Date(2026, 2, 20, 9, 0, 0); // 20 Mar 2026, 09:00 local
    const end = addDuration(start, 20160); // 14 days
    expect(end.getHours()).toBe(9);
    expect(end.getDate()).toBe(3); // 3 April
    // And the guard that makes the assertion above mean something: an instant
    // offset lands at 10:00, so the two rules genuinely differ here and the
    // test is not passing on a zone where DST never fires.
    expect(new Date(start.getTime() + 20160 * 60_000).getHours()).toBe(10);
  });

  it('leaves the start untouched', () => {
    const start = new Date('2026-09-01T09:00:00Z');
    addDuration(start, 240);
    expect(start.toISOString()).toBe('2026-09-01T09:00:00.000Z');
  });
});
