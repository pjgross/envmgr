/**
 * A `Date` as an `<input type="datetime-local">` value: `YYYY-MM-DDTHH:mm` in
 * LOCAL time.
 *
 * Not a string slice of `toISOString()` — that yields UTC, so a 09:00 local
 * booking renders as 08:00 in British Summer Time and saves an hour early.
 * One helper rather than a formatting expression per field: four copies is how
 * two halves of the same dialog drift apart.
 */
export function toDateTimeLocal(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}
