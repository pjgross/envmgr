/**
 * Read-only planned-vs-forecast bars for a runbook. Modelled on
 * EnvironmentResourceGantt; deliberately not PhaseGanttEditor (an editor for a
 * different entity). Scrolls inside its own box — a runbook spanning two
 * evenings is wide, and page-level overflow here hides row labels under the
 * fixed drawer (IA PR 5).
 */
import { Box, Typography } from '@mui/material';
import type { RunbookRead } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';

const LABEL_W = 200;
const ROW_H = 36;
const PX_PER_MIN = 2;

export default function RunbookTimeline({ read }: { read: RunbookRead }) {
  const ms = (s: string) => new Date(s).getTime();
  const starts = read.tasks.flatMap((t) => [ms(t.planned_start), ms(t.forecast_start)]);
  const t0 = Math.min(ms(read.plan.anchor_start_at), ...starts);
  const t1 = Math.max(ms(read.planned_end), ms(read.forecast_end), t0 + 60_000);
  const minutes = (t1 - t0) / 60_000;
  const width = Math.max(720, minutes * PX_PER_MIN);
  const x = (s: string) => ((ms(s) - t0) / (t1 - t0)) * width;
  const now = Date.now();
  const showNow = now >= t0 && now <= t1;

  if (read.tasks.length === 0) {
    return <Typography color="text.secondary">This runbook has no tasks yet.</Typography>;
  }
  return (
    <Box
      data-testid="runbook-timeline-scroll"
      style={{ overflowX: 'auto' }}
      sx={{ border: 1, borderColor: 'divider', borderRadius: 1 }}
    >
      <Box sx={{ display: 'grid', gridTemplateColumns: `${LABEL_W}px ${width}px` }}>
        {read.tasks.map((t) => (
          <Box key={t.id} sx={{ display: 'contents' }}>
            <Box
              sx={{
                height: ROW_H,
                px: 1,
                display: 'flex',
                alignItems: 'center',
                position: 'sticky',
                left: 0,
                bgcolor: 'background.paper',
                zIndex: 1,
                borderBottom: 1,
                borderColor: 'divider',
              }}
            >
              <Typography variant="body2" noWrap title={t.name}>
                {t.name}
              </Typography>
            </Box>
            <Box sx={{ height: ROW_H, position: 'relative', borderBottom: 1, borderColor: 'divider' }}>
              <Box
                role="img"
                aria-label={`${t.name}: planned ${formatBookingDateTime(t.planned_start)} to ${formatBookingDateTime(t.planned_finish)}`}
                sx={{
                  position: 'absolute',
                  top: 6,
                  height: 10,
                  left: x(t.planned_start),
                  width: Math.max(2, x(t.planned_finish) - x(t.planned_start)),
                  border: 1,
                  borderColor: 'text.secondary',
                  borderRadius: 0.5,
                }}
              />
              <Box
                role="img"
                aria-label={`${t.name}: forecast ${formatBookingDateTime(t.forecast_start)} to ${formatBookingDateTime(t.forecast_finish)}${t.critical ? ', critical' : ''}`}
                sx={{
                  position: 'absolute',
                  top: 20,
                  height: 10,
                  left: x(t.forecast_start),
                  width: Math.max(2, x(t.forecast_finish) - x(t.forecast_start)),
                  bgcolor: t.critical ? 'error.main' : 'primary.main',
                  borderRadius: 0.5,
                }}
              />
              {showNow && (
                <Box
                  aria-hidden
                  sx={{
                    position: 'absolute',
                    top: 0,
                    bottom: 0,
                    width: 2,
                    bgcolor: 'warning.main',
                    left: ((now - t0) / (t1 - t0)) * width,
                  }}
                />
              )}
            </Box>
          </Box>
        ))}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', p: 1 }}>
        Outlined: planned. Filled: forecast. Red: on the critical path.
      </Typography>
    </Box>
  );
}
