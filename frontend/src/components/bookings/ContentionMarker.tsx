import { Box, Typography } from '@mui/material';
import type { SvgIconComponent } from '@mui/icons-material';
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined';
import HourglassEmptyOutlinedIcon from '@mui/icons-material/HourglassEmptyOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';

import type { ContentionState } from '../../types/contentionForecast';

export interface ContentionMarkerProps {
  state: ContentionState;
}

interface StateConfig {
  label: string;
  Icon: SvgIconComponent;
  color: 'error.main' | 'warning.main' | 'success.main';
}

// THE ONE PLACE A CONTENTION STATE BECOMES A LABEL OR A COLOUR. B5 shipped
// three independent copies of a state->label map across three files, and
// nothing caught a future edit to one and not the others (see CLAUDE.md).
// Tasks 6 (the bookings list) and 7 (the calendar) both render a state
// through THIS component, never through their own switch statement, so the
// two surfaces cannot drift apart.
//
// Each state carries a DIFFERENT icon shape as well as a different word —
// not colour alone. This repo's completed a11y audit flags colour-only
// state encoding, and a reader who cannot distinguish `error`/`warning`/
// `success` still sees a different glyph and a different label per state.
const STATE_CONFIG: Record<ContentionState, StateConfig> = {
  unowned: {
    label: 'Contention — needs escalating',
    Icon: ReportProblemOutlinedIcon,
    color: 'error.main',
  },
  owned: {
    label: 'Contention — awaiting a decision',
    Icon: HourglassEmptyOutlinedIcon,
    color: 'warning.main',
  },
  decided: {
    label: 'Contention — decided',
    Icon: CheckCircleOutlineIcon,
    color: 'success.main',
  },
};

/**
 * B6's forward-contention marker for one booking. `state` is
 * `Booking.contention_state` — a caller must not render this at all when
 * that value is `null` (no contention is a real, common value, not a
 * missing one; rendering an empty chip for it would read as a state of its
 * own). This component itself has no "none" branch for exactly that reason:
 * every prop value it accepts is a real, actionable state.
 *
 * The icon is `aria-hidden` and decorative; the visible `Typography` text
 * beside it is the accessible name a screen reader announces. The icon
 * still carries its own state-specific `aria-label` so a marker rendered
 * without its text (e.g. a future icon-only calendar chip) is not silently
 * left with no accessible name at all.
 */
export function ContentionMarker({ state }: ContentionMarkerProps) {
  const { label, Icon, color } = STATE_CONFIG[state];
  return (
    <Box
      component="span"
      sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color }}
    >
      <Icon fontSize="small" role="img" aria-hidden="true" aria-label={label} />
      <Typography variant="caption" component="span" sx={{ color: 'inherit' }}>
        {label}
      </Typography>
    </Box>
  );
}
