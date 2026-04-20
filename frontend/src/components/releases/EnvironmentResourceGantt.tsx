/**
 * EnvironmentResourceGantt — read-only Gantt showing bookings per environment,
 * colour-coded by test phase.
 *
 * Rows = environments involved in the release bookings.
 * Bars = bookings, labelled with phase name.
 */
import { Box, Tooltip, Typography } from '@mui/material';
import type { BookingResponse } from '../../types/booking';
import type { TestPhaseResponse } from '../../types/release';

interface Props {
  bookings: BookingResponse[];
  phases: TestPhaseResponse[];
}

const PHASE_PALETTE = [
  '#90caf9',
  '#ffb74d',
  '#81c784',
  '#e57373',
  '#ce93d8',
  '#4dd0e1',
];

function parseDate(s: string): Date {
  return new Date(s);
}

export default function EnvironmentResourceGantt({ bookings, phases }: Props) {
  if (bookings.length === 0) {
    return (
      <Box
        sx={{
          border: '1px dashed',
          borderColor: 'divider',
          borderRadius: 1,
          p: 2,
          textAlign: 'center',
        }}
      >
        <Typography variant="body2" color="text.secondary">
          No environment bookings yet. Add bookings below.
        </Typography>
      </Box>
    );
  }

  const phaseColorMap = new Map<number, string>(
    phases.map((p, i) => [p.id, PHASE_PALETTE[i % PHASE_PALETTE.length]])
  );
  const phaseNameMap = new Map<number, string>(phases.map((p) => [p.id, p.name]));

  // Group by environment
  const envMap = new Map<number, { name: string; bookings: BookingResponse[] }>();
  for (const b of bookings) {
    if (!envMap.has(b.environment_id)) {
      envMap.set(b.environment_id, { name: b.environment_name ?? `Env ${b.environment_id}`, bookings: [] });
    }
    envMap.get(b.environment_id)!.bookings.push(b);
  }

  const allDates = bookings.flatMap((b) => [
    parseDate(b.start_date),
    parseDate(b.end_date),
  ]);
  const minDate = new Date(Math.min(...allDates.map((d) => d.getTime())));
  const maxDate = new Date(Math.max(...allDates.map((d) => d.getTime())));
  const totalMs = maxDate.getTime() - minDate.getTime() || 1;
  const toPercent = (d: Date) =>
    ((d.getTime() - minDate.getTime()) / totalMs) * 100;

  return (
    <Box sx={{ overflowX: 'auto' }}>
      {/* Axis */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5, px: 0.5 }}>
        <Typography variant="caption" color="text.secondary">
          {minDate.toLocaleDateString()}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {maxDate.toLocaleDateString()}
        </Typography>
      </Box>

      {Array.from(envMap.entries()).map(([envId, { name, bookings: envBookings }]) => (
        <Box key={envId} sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography
            variant="caption"
            sx={{ width: 130, flexShrink: 0, pr: 1, textAlign: 'right' }}
            noWrap
          >
            {name}
          </Typography>
          <Box
            sx={{
              position: 'relative',
              flex: 1,
              height: 28,
              bgcolor: 'action.hover',
              borderRadius: 0.5,
              minWidth: 200,
            }}
          >
            {envBookings.map((b) => {
              const start = parseDate(b.start_date);
              const end = parseDate(b.end_date);
              const left = toPercent(start);
              const width = Math.max(toPercent(end) - left, 0.5);
              const color = b.test_phase_id
                ? (phaseColorMap.get(b.test_phase_id) ?? '#90caf9')
                : '#b0bec5';
              const phaseName = b.test_phase_id
                ? (phaseNameMap.get(b.test_phase_id) ?? 'Phase')
                : 'No phase';

              return (
                <Tooltip
                  key={b.id}
                  title={`${b.project_name} · ${phaseName}: ${start.toLocaleDateString()} – ${end.toLocaleDateString()}`}
                  arrow
                >
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 3,
                      bottom: 3,
                      left: `${left}%`,
                      width: `${width}%`,
                      bgcolor: color,
                      borderRadius: 0.5,
                      overflow: 'hidden',
                      minWidth: 4,
                    }}
                  >
                    <Typography
                      variant="caption"
                      noWrap
                      sx={{ px: 0.5, fontSize: '0.65rem', lineHeight: '22px' }}
                    >
                      {b.project_name}
                    </Typography>
                  </Box>
                </Tooltip>
              );
            })}
          </Box>
        </Box>
      ))}
    </Box>
  );
}
