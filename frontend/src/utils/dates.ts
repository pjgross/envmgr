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
 * looks for — that is a missing owner).
 */
export function formatExpiry(iso: string | null): string {
  if (!iso) return 'No expiry planned';
  const days = expiryDayDelta(iso) as number;
  if (days === 0) return 'today';
  if (days > 0) return `in ${days} day${days === 1 ? '' : 's'}`;
  const overdue = Math.abs(days);
  return `overdue by ${overdue} day${overdue === 1 ? '' : 's'}`;
}
