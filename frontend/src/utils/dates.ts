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
