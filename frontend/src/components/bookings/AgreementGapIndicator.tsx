import { Tooltip } from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

type Props = {
  /** The server's message, or null when this booking is covered. */
  gap: string | null;
  hasUnacknowledgedGap: boolean;
};

/**
 * One list row's usage-agreement gap (Phase 7 A3), as a single cell.
 *
 * A3 WARNS, IT NEVER BLOCKS. This is an indicator and nothing else — it gates
 * no action, disables no control and changes no row.
 *
 * ACKNOWLEDGING IS NOT RESOLVING, so the two states are shown DIFFERENTLY
 * rather than one of them being shown as nothing. The gap is recomputed from
 * `usage_agreement` on every read and is cleared only by recording the missing
 * agreement; an acknowledged booking is still in gap, and `?agreement_gap=true`
 * still returns it. An indicator that disappeared on acknowledgement would
 * leave that filter rendering a page of blank cells — information lost, not
 * merely hidden (docs/pagination.md). The difference is carried by the
 * accessible name as well as by colour, so it is not colour-only.
 *
 * The message is the SERVER's, verbatim: `agreement_gap_service` already names
 * the project and the environment, so nothing here composes a label and nothing
 * here can render `#12` or `env #3`. There is deliberately no fallback text for
 * a missing message either — a null `gap` means "no gap", full stop.
 *
 * Deliberately not keyboard-focusable, matching its sibling `ConflictIndicator`:
 * the full message is on the booking detail page's `AgreementGapPanel`, in
 * ordinary body text rather than behind a hover, and this cell is a pointer to
 * that page.
 */
export default function AgreementGapIndicator({ gap, hasUnacknowledgedGap }: Props) {
  if (gap == null) return null;

  const acknowledged = !hasUnacknowledgedGap;
  return (
    <Tooltip describeChild title={acknowledged ? `Acknowledged — ${gap}` : gap}>
      <WarningAmberIcon
        fontSize="small"
        color={acknowledged ? 'disabled' : 'warning'}
        role="img"
        aria-label={acknowledged ? 'Usage agreement gap, acknowledged' : 'Usage agreement gap'}
      />
    </Tooltip>
  );
}
