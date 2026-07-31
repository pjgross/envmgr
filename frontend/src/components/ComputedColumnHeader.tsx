import { Tooltip, Typography } from '@mui/material';

/**
 * Header for a column computed after the page is fetched.
 *
 * Twelve such columns exist across the list pages — counts and roll-ups built in
 * Python from batch queries keyed on the page's row ids, or in the browser from a
 * JSON field. None is backed by a column the database could order by, so none can
 * be sorted server-side.
 *
 * Users could sort these before server-side paging arrived, but only within the
 * truncated page they happened to hold — a sort of the wrong set. The capability
 * genuinely goes away, so it is explained rather than left as a dead header.
 *
 * The label span is given `tabIndex={0}` so keyboard users can Tab to it and
 * trigger MUI's focus-triggered tooltip (Tooltip only wires up focus/blur
 * handlers, it doesn't make an inert span focusable). `describeChild` makes
 * MUI associate the explanation via `aria-describedby` instead of clobbering
 * the span's accessible name with the tooltip text — screen readers still
 * announce the column label first, then the explanation, consistent with
 * docs/ui-audit.md finding A1's "Tooltip alone isn't enough" guidance.
 */
export default function ComputedColumnHeader({ label }: { label: string }) {
  return (
    <Tooltip
      describeChild
      title="Computed after the page is fetched — not sortable across all results."
    >
      <Typography variant="body2" fontWeight={500} component="span" tabIndex={0}>
        {label}
      </Typography>
    </Tooltip>
  );
}
