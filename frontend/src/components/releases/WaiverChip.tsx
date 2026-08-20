/**
 * WaiverChip — a small, honest expiry preview. Null reads as "No expiry
 * (permanent)", never "today" — a permanent waiver and one expiring right
 * now are different facts (see `formatExpiry`'s own doc comment).
 *
 * Colouring and the label are driven from the SAME calendar-day delta
 * (`isExpiryOverdue` / `formatExpiry`, both in utils/dates.ts) rather than a
 * separate instant comparison — the exact class of bug `formatExpiry`'s own
 * history warns about: label and colour disagreeing about whether "today"
 * is overdue.
 */
import { Chip } from '@mui/material';
import { formatExpiry, isExpiryOverdue } from '../../utils/dates';

interface Props {
  expiresAt: string | null;
}

export default function WaiverChip({ expiresAt }: Props) {
  if (!expiresAt) {
    return <Chip size="small" variant="outlined" label="No expiry (permanent)" />;
  }
  const overdue = isExpiryOverdue(expiresAt);
  return (
    <Chip
      size="small"
      color={overdue ? 'error' : 'default'}
      variant={overdue ? 'filled' : 'outlined'}
      label={`Expires ${formatExpiry(expiresAt)}`}
    />
  );
}
