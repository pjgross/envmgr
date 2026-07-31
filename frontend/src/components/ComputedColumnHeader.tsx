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
 */
export default function ComputedColumnHeader({ label }: { label: string }) {
  return (
    <Tooltip title="Computed after the page is fetched — not sortable across all results.">
      <Typography variant="body2" fontWeight={500} component="span">
        {label}
      </Typography>
    </Tooltip>
  );
}
