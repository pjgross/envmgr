/**
 * Small date helpers. HTML `<input type="date">` yields "YYYY-MM-DD" but many
 * FastAPI endpoints expect `Optional[datetime]` which Pydantic v2 only accepts
 * as a full ISO datetime. Use `toIsoDatetime` on submit and `toDateInputValue`
 * when pre-filling a date input from a backend-returned ISO string.
 */
export function toIsoDatetime(d: unknown): string | null {
  if (typeof d !== 'string') return null;
  const trimmed = d.trim();
  if (trimmed === '') return null;
  if (trimmed.includes('T')) return trimmed;
  return `${trimmed}T00:00:00Z`;
}

export function toDateInputValue(iso: string | null | undefined): string {
  if (!iso) return '';
  // Safe slice: handles both "2026-05-01" and "2026-05-01T00:00:00Z"
  return iso.slice(0, 10);
}

/**
 * The reader's own calendar day, as UTC midnight — the honest start for UTC
 * date arithmetic that begins at "today".
 *
 * `new Date()` is an INSTANT, and every date helper here counts in UTC, so
 * feeding one straight to `addWorkingDays` silently asks "what day is it in
 * UTC?" rather than "what day is it where the user is". At 09:00 in Auckland
 * (UTC+12) the UTC date is still yesterday, so a three-working-day default was
 * computed from the wrong start and the owner was handed one fewer working day
 * than the helper promises — invisible to tests that all pass UTC midnights.
 *
 * Deliberately NOT a conversion of the instant: it reads the LOCAL calendar
 * fields and rebuilds them as UTC midnight, which is exactly what a
 * `<input type="date">` shows and what `toIsoDatetime` then sends back as
 * `T00:00:00Z`. One notion of "the day" from the picker to the wire.
 */
export function localDayAsUtc(instant: Date): Date {
  return new Date(
    Date.UTC(instant.getFullYear(), instant.getMonth(), instant.getDate())
  );
}

/**
 * `days` working days after `from`, weekends skipped, in UTC.
 *
 * A4's escalation asks a named person to decide by a named date, and that date
 * defaults to three WORKING days ahead. Three CALENDAR days lands on a Saturday
 * for anything raised Wednesday, Thursday or Friday — more than half the week —
 * which hands the owner a deadline nobody is at work for and makes the
 * escalation read `expired` the moment they open it on Monday.
 *
 * UTC on both the arithmetic and the weekday, matching `expiryDayDelta` below:
 * a `<input type="date">` yields "YYYY-MM-DD" and this app writes deadlines at
 * `T00:00:00Z`, so reading the weekday in local time would shift the skip by a
 * day for anyone east or west of UTC.
 *
 * A weekend START is not itself skipped forward first — it does not need to be.
 * Counting only working days from Saturday reaches the same date as counting
 * from the Friday before it, which is the honest answer: no working day has
 * passed in between.
 *
 * Deliberately knows nothing about public holidays. There is no holiday
 * calendar in this product, and inventing one per tenant to compute a DEFAULT
 * the escalator can freely overwrite would be a table nobody asked for.
 */
export function addWorkingDays(from: Date, days: number): Date {
  const out = new Date(from.getTime());
  let remaining = days;
  while (remaining > 0) {
    out.setUTCDate(out.getUTCDate() + 1);
    const day = out.getUTCDay();
    if (day !== 0 && day !== 6) remaining -= 1;
  }
  return out;
}

/**
 * Whole-calendar-day delta between an ISO expiry and "now", both read in UTC.
 * Null when there is no expiry.
 *
 * Calendar-day difference, not a floored millisecond difference: expiries
 * are always normalised to `T00:00:00Z`, and "now" is read at whatever time
 * of day the page happens to load. Flooring the raw ms delta made an
 * environment read as overdue for the entire day it actually expires (delta
 * is negative any time after 00:00Z) and "today" a day early (readable only
 * in the instant before midnight) — see expiry.test.ts.
 *
 * Exported so `formatExpiry` (the label) and the overdue *colouring* next to
 * it are driven by the same arithmetic. Before this they weren't: the label
 * used this calendar-day delta while the colour was a raw instant comparison
 * (`new Date(expires_at) < new Date()`), so an environment expiring today
 * read "today" in the label while its cell was already red from 00:00Z —
 * label and colour disagreeing for a whole day.
 */
export function expiryDayDelta(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const MS_PER_DAY = 24 * 60 * 60 * 1000;
  const e = new Date(iso);
  const n = new Date();
  return Math.round(
    (Date.UTC(e.getUTCFullYear(), e.getUTCMonth(), e.getUTCDate()) -
      Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate())) /
      MS_PER_DAY
  );
}

/**
 * True only once the expiry's calendar day has actually passed — "today" is
 * not overdue, matching `formatExpiry`'s "today" (never "overdue by 0
 * days"). Use this for the red/error colouring beside `formatExpiry`'s
 * label rather than a separate instant comparison.
 */
export function isExpiryOverdue(iso: string | null | undefined): boolean {
  const delta = expiryDayDelta(iso);
  return delta !== null && delta < 0;
}

/**
 * Relative expiry copy.
 *
 * An absolute date alone makes the reader do the arithmetic the field exists
 * to prompt — "2026-11-02" does not read as urgent, "in 4 days" does.
 *
 * Null is "No expiry planned", never "today": no expiry and an expiry that
 * lands now are different facts, and a null expiry is a legitimate state
 * rather than a missing value (it is deliberately not what `governance_gap`
 * looks for — that is a missing owner or a missing operations group).
 */
export function formatExpiry(iso: string | null): string {
  if (!iso) return 'No expiry planned';
  const days = expiryDayDelta(iso) as number;
  if (days === 0) return 'today';
  if (days > 0) return `in ${days} day${days === 1 ? '' : 's'}`;
  const overdue = Math.abs(days);
  return `overdue by ${overdue} day${overdue === 1 ? '' : 's'}`;
}
