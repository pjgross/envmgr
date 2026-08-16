const MINUTES_PER_DAY = 1440;

/**
 * `start` plus `minutes`, applied by rule rather than by arithmetic.
 *
 * A whole multiple of a day is added as CALENDAR days; anything else as
 * minutes. So "sprint = 14 days" from 09:00 lands on 09:00 across a
 * spring-forward, while "half-day = 240" from 09:00 lands on 13:00.
 *
 * Returns a new Date; never mutates `start`.
 */
export function addDuration(start: Date, minutes: number): Date {
  const out = new Date(start.getTime());
  if (minutes > 0 && minutes % MINUTES_PER_DAY === 0) {
    out.setDate(out.getDate() + minutes / MINUTES_PER_DAY);
    return out;
  }
  out.setTime(out.getTime() + minutes * 60_000);
  return out;
}
