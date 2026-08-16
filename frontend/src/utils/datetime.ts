/**
 * A `Date` as an `<input type="datetime-local">` value: `YYYY-MM-DDTHH:mm` in
 * LOCAL time.
 *
 * Not a string slice of `toISOString()` — that yields UTC, so a 09:00 local
 * booking renders as 08:00 in British Summer Time and saves an hour early.
 * One helper rather than a formatting expression per field: four copies is how
 * two halves of the same dialog drift apart.
 */
/**
 * A booking bound for READING: the date, plus the time of day when there is
 * one.
 *
 * A booking that starts and ends at midnight is rendered as a plain date, the
 * way every booking was before B4 — appending ", 00:00" to the whole existing
 * estate is noise. A booking with a real time of day renders it, because
 * without it a 09:00–13:00 half day reads as "01/09/2026 → 01/09/2026": an
 * all-day booking, or the zero-length one the edit path used to save. B4's
 * duration presets are what make sub-day bookings ordinary.
 */
export function formatBookingDateTime(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const atMidnight = date.getHours() === 0 && date.getMinutes() === 0;
  if (atMidnight) return date.toLocaleDateString();
  return `${date.toLocaleDateString()}, ${date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })}`;
}

export function toDateTimeLocal(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}
