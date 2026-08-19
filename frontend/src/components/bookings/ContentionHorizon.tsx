import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { Box, Chip, Link, Skeleton, Typography } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';

import type { AppDispatch, RootState } from '../../store';
import { fetchContentionHorizon } from '../../store/contentionForecastSlice';

/** Options are weeks, never days — a leading indicator this coarse has no
 * use for day-level precision, and 2/6/12/26 map onto a sprint, two sprints,
 * a quarter and a half-year without the reader doing arithmetic. */
export const HORIZON_WEEK_OPTIONS = [2, 6, 12, 26] as const;
export type HorizonWeeksOption = (typeof HORIZON_WEEK_OPTIONS)[number];
/** Roughly two sprints — far enough out to act on, near enough to matter. */
export const DEFAULT_HORIZON_WEEKS: HorizonWeeksOption = 6;

const PARAM_NAME = 'horizon_weeks';

function parseHorizonParam(raw: string | null): HorizonWeeksOption {
  const n = Number(raw);
  return (HORIZON_WEEK_OPTIONS as readonly number[]).includes(n)
    ? (n as HorizonWeeksOption)
    : DEFAULT_HORIZON_WEEKS;
}

/**
 * B6 Task 8 — the forward-contention HEADLINE, and the sub-project's central
 * claim: "N contentions in the next W weeks", pointing at the A4 escalation
 * worklist that already exists (`/contentions`, filterable by state — B6
 * builds no second worklist here).
 *
 * INDEPENDENCE FROM THE VISIBLE CALENDAR RANGE IS THE WHOLE POINT, NOT A
 * DETAIL. A calendar only ever answers "what is happening in the month I
 * navigated to" — a summary that quietly tracked that range would be
 * restating a question the reader already had to ask by navigating, not
 * answering a new one. So this component takes NO PROPS AT ALL: there is
 * nothing describing a visible date range for a parent to hand it, by
 * construction, which is what makes "not on a calendar month change" true
 * structurally rather than by a check someone has to remember. The only
 * thing that can make it refetch is a change to `weeks`, which it owns
 * itself — read from and written to its OWN url query param
 * (`horizon_weeks`), never lifted into a parent's state. See
 * ContentionHorizon.test.tsx and, for the integration proof against the real
 * page, bookingCalendarContentionHorizon.test.tsx.
 *
 * THE HORIZON LIVES IN THE URL so the view is shareable/bookmarkable — a
 * link to "26 weeks out" should reproduce that window on open, not silently
 * fall back to the default.
 */
export default function ContentionHorizon() {
  const dispatch = useDispatch<AppDispatch>();
  const [searchParams, setSearchParams] = useSearchParams();
  const weeks = parseHorizonParam(searchParams.get(PARAM_NAME));

  const { count, weeks: fetchedWeeks, loading, error } = useSelector(
    (state: RootState) => state.contentionForecast
  );

  // THE ONLY TRIGGER: mount, and a change of `weeks`. `dispatch` is stable
  // (React-Redux guarantees it), so this effect fires exactly on those two
  // occasions and on nothing else — see the module docstring above.
  useEffect(() => {
    dispatch(fetchContentionHorizon(weeks));
  }, [dispatch, weeks]);

  const handleSelect = (next: HorizonWeeksOption) => {
    if (next === weeks) return;
    const params = new URLSearchParams(searchParams);
    params.set(PARAM_NAME, String(next));
    setSearchParams(params);
  };

  // The server echoes `weeks` back (contentionForecastSlice's own reason: a
  // stale in-flight response for the outgoing window must not get
  // relabelled under the incoming one's heading). Render the count only once
  // it actually describes the window currently selected.
  const showCount = !loading && !error && fetchedWeeks === weeks && count !== null;

  return (
    <Box
      data-testid="contention-horizon"
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 2,
        mb: 2,
        p: 1.5,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        flexWrap: 'wrap',
      }}
    >
      <TrendingUpIcon color="action" fontSize="small" aria-hidden="true" />

      <Box sx={{ minWidth: 220 }}>
        {error && (
          <Typography variant="body2" color="error">
            {error}
          </Typography>
        )}
        {!error && !showCount && <Skeleton width={220} />}
        {!error && showCount && (
          <Typography variant="body2">
            <strong>{count}</strong> {count === 1 ? 'contention' : 'contentions'} in the next{' '}
            {fetchedWeeks} weeks
          </Typography>
        )}
      </Box>

      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {HORIZON_WEEK_OPTIONS.map((option) => (
          <Chip
            key={option}
            label={`${option} weeks`}
            clickable
            component="button"
            size="small"
            color={weeks === option ? 'primary' : 'default'}
            variant={weeks === option ? 'filled' : 'outlined'}
            onClick={() => handleSelect(option)}
          />
        ))}
      </Box>

      <Link component={RouterLink} to="/contentions" variant="body2">
        View contentions worklist
      </Link>
    </Box>
  );
}
