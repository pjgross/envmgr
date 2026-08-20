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
 *
 * `state`, when supplied, is the SERVER's own verdict
 * (`gate_waiver_service.waiver_state`, computed from one clock for the
 * whole response) and takes priority over the client-side day-delta — used
 * for rendering an EXISTING waiver read back from the API. Omit it for the
 * WaiverDialog's live in-progress preview of a date the user is still
 * typing, which the server has never seen.
 */
import { Chip } from '@mui/material';
import { formatExpiry, isExpiryOverdue } from '../../utils/dates';

interface Props {
  expiresAt: string | null;
  state?: 'live' | 'expired';
}

export default function WaiverChip({ expiresAt, state }: Props) {
  if (!expiresAt) {
    return <Chip size="small" variant="outlined" label="No expiry (permanent)" />;
  }
  const overdue = state ? state === 'expired' : isExpiryOverdue(expiresAt);
  return (
    <Chip
      size="small"
      color={overdue ? 'error' : 'default'}
      variant={overdue ? 'filled' : 'outlined'}
      label={overdue ? `Expired ${formatExpiry(expiresAt)}` : `Expires ${formatExpiry(expiresAt)}`}
    />
  );
}
