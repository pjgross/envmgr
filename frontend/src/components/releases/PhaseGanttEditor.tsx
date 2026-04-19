/**
 * PhaseGanttEditor — read-only CSS flexbox Gantt for release test phases.
 *
 * Drag-and-drop is deferred (sub-project 3). Date editing is handled via
 * the PhasesTable below this component.
 */
import { Box, Chip, Tooltip, Typography } from '@mui/material';
import type { TestPhaseResponse } from '../../types/release';

interface Props {
  phases: TestPhaseResponse[];
  /** The overall release target date — used to size the Gantt viewport */
  releaseTargetDate?: string | null;
}

function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

const STATUS_COLOR: Record<string, string> = {
  planned: '#90caf9',
  in_progress: '#ffb74d',
  completed: '#81c784',
  blocked: '#e57373',
};

export default function PhaseGanttEditor({ phases, releaseTargetDate }: Props) {
  const phasesWithDates = phases.filter(
    (p) => p.start_date != null && p.end_date != null
  );

  if (phasesWithDates.length === 0) {
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
          No phases with dates yet. Set start/end dates in the Phases table below.
        </Typography>
      </Box>
    );
  }

  // Compute viewport bounds
  const allDates = phasesWithDates.flatMap((p) => [
    parseDate(p.start_date)!,
    parseDate(p.end_date)!,
  ]);
  const releaseEnd = parseDate(releaseTargetDate);
  if (releaseEnd) allDates.push(releaseEnd);

  const minDate = new Date(Math.min(...allDates.map((d) => d.getTime())));
  const maxDate = new Date(Math.max(...allDates.map((d) => d.getTime())));
  const totalMs = maxDate.getTime() - minDate.getTime() || 1;

  const toPercent = (d: Date) =>
    ((d.getTime() - minDate.getTime()) / totalMs) * 100;

  return (
    <Box sx={{ overflowX: 'auto' }}>
      {/* Header axis */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          mb: 0.5,
          px: 0.5,
        }}
      >
        <Typography variant="caption" color="text.secondary">
          {minDate.toLocaleDateString()}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {maxDate.toLocaleDateString()}
        </Typography>
      </Box>

      {/* Phase rows */}
      <Box sx={{ position: 'relative', minWidth: 500 }}>
        {phasesWithDates.map((phase) => {
          const start = parseDate(phase.start_date)!;
          const end = parseDate(phase.end_date)!;
          const left = toPercent(start);
          const width = Math.max(toPercent(end) - left, 1);
          const color = STATUS_COLOR[phase.status] ?? '#90caf9';

          return (
            <Box
              key={phase.id}
              sx={{
                position: 'relative',
                height: 36,
                mb: 0.5,
                bgcolor: 'action.hover',
                borderRadius: 0.5,
              }}
            >
              <Tooltip
                title={`${phase.name}: ${new Date(phase.start_date!).toLocaleDateString()} – ${new Date(phase.end_date!).toLocaleDateString()} (${phase.status})`}
                arrow
              >
                <Box
                  sx={{
                    position: 'absolute',
                    top: 4,
                    bottom: 4,
                    left: `${left}%`,
                    width: `${width}%`,
                    bgcolor: color,
                    borderRadius: 0.5,
                    display: 'flex',
                    alignItems: 'center',
                    px: 0.5,
                    cursor: 'default',
                    overflow: 'hidden',
                    minWidth: 4,
                  }}
                >
                  <Typography
                    variant="caption"
                    noWrap
                    sx={{
                      fontWeight: 'medium',
                      color: 'text.primary',
                      fontSize: '0.7rem',
                    }}
                  >
                    {phase.name}
                  </Typography>
                </Box>
              </Tooltip>

              {/* Phase label in the row gutter */}
              <Box
                sx={{
                  position: 'absolute',
                  right: 4,
                  top: '50%',
                  transform: 'translateY(-50%)',
                }}
              >
                <Chip
                  label={phase.status}
                  size="small"
                  sx={{ height: 18, fontSize: '0.65rem', bgcolor: color }}
                />
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
