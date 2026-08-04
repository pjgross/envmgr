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
  const MS_PER_DAY = 24 * 60 * 60 * 1000;
  const e = new Date(iso);
  const n = new Date();
  // Calendar-day difference, not a floored millisecond difference: expiries
  // are always normalised to `T00:00:00Z`, and "now" is read at whatever
  // time of day the page happens to load. Flooring the raw ms delta made an
  // environment read as overdue for the entire day it actually expires
  // (delta is negative any time after 00:00Z) and "today" a day early
  // (readable only in the instant before midnight) — see expiry.test.ts.
  const days = Math.round(
    (Date.UTC(e.getUTCFullYear(), e.getUTCMonth(), e.getUTCDate()) -
      Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate())) /
      MS_PER_DAY
  );
  if (days === 0) return 'today';
  if (days > 0) return `in ${days} day${days === 1 ? '' : 's'}`;
  const overdue = Math.abs(days);
  return `overdue by ${overdue} day${overdue === 1 ? '' : 's'}`;
}
