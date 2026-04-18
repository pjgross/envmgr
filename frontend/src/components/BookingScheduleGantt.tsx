import { useEffect, useMemo, useState } from 'react';
import {
  Box,
  CircularProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import { bookingService } from '../services/bookingService';
import type { BookingResponse } from '../types/booking';

interface EnvRow {
  id: number;
  name: string;
}

interface Props {
  envs: EnvRow[];
  scheduledStart?: Date | null;
  scheduledEnd?: Date | null;
  hasOutage?: boolean;
  outageStart?: Date | null;
  outageEnd?: Date | null;
  /** Half-width of the window in days (default 7 — one week either side). */
  daysEachSide?: number;
}

const STATUS_COLORS: Record<string, string> = {
  draft: '#90caf9',
  submitted: '#ffb74d',
  approved: '#81c784',
  rejected: '#e57373',
  in_progress: '#64b5f6',
  completed: '#9e9e9e',
};

const LABEL_COL_WIDTH = 140;
const ROW_HEIGHT = 36;
const HEADER_HEIGHT = 40;

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function dayLabel(d: Date): string {
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function weekdayLabel(d: Date): string {
  return d.toLocaleDateString(undefined, { weekday: 'short' });
}

/**
 * Readonly Gantt-style booking timeline. One row per environment, bars for
 * each booking, and vertical band overlays highlighting the proposed change
 * window and (if flagged) the outage window. No interactivity — this is a
 * reference view embedded in the change request form.
 */
export default function BookingScheduleGantt({
  envs,
  scheduledStart,
  scheduledEnd,
  hasOutage,
  outageStart,
  outageEnd,
  daysEachSide = 7,
}: Props) {
  // Snap to the day the proposed change starts (or today, if not yet set) so
  // small edits to the scheduled time don't thrash the fetch window.
  const centerMs = scheduledStart ? startOfDay(scheduledStart).getTime() : startOfDay(new Date()).getTime();
  const windowStart = useMemo(() => {
    const d = new Date(centerMs);
    d.setDate(d.getDate() - daysEachSide);
    return d;
  }, [centerMs, daysEachSide]);
  const totalDays = daysEachSide * 2 + 1;
  const windowEnd = useMemo(() => {
    const d = new Date(windowStart);
    d.setDate(d.getDate() + totalDays);
    return d;
  }, [windowStart, totalDays]);
  const totalMs = windowEnd.getTime() - windowStart.getTime();

  const [bookingsByEnv, setBookingsByEnv] = useState<Map<number, BookingResponse[]>>(
    new Map()
  );
  const [loading, setLoading] = useState(false);

  // Stable key so the effect doesn't refetch on every render when the parent
  // passes a new array reference with identical ids.
  const envKey = useMemo(
    () => envs.map((e) => e.id).sort((a, b) => a - b).join(','),
    [envs]
  );
  const windowKey = `${windowStart.toISOString()}|${windowEnd.toISOString()}`;

  useEffect(() => {
    if (envs.length === 0) {
      setBookingsByEnv(new Map());
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const results = await Promise.all(
          envs.map((e) =>
            bookingService
              .listBookings({
                environment_id: e.id,
                start: windowStart.toISOString(),
                end: windowEnd.toISOString(),
              })
              .then((list) => [e.id, list] as const)
              .catch(() => [e.id, [] as BookingResponse[]] as const)
          )
        );
        if (cancelled) return;
        setBookingsByEnv(new Map(results));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [envKey, windowKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const days = useMemo(() => {
    const out: Date[] = [];
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(windowStart);
      d.setDate(d.getDate() + i);
      out.push(d);
    }
    return out;
  }, [windowStart, totalDays]);

  const barStyle = (startISO: string, endISO: string) => {
    const s = Math.max(new Date(startISO).getTime(), windowStart.getTime());
    const e = Math.min(new Date(endISO).getTime(), windowEnd.getTime());
    if (e <= s) return null;
    return {
      left: `${((s - windowStart.getTime()) / totalMs) * 100}%`,
      width: `${((e - s) / totalMs) * 100}%`,
    } as const;
  };

  const overlayStyle = (start?: Date | null, end?: Date | null) => {
    if (!start || !end) return null;
    return barStyle(start.toISOString(), end.toISOString());
  };

  const proposedOverlay = overlayStyle(scheduledStart, scheduledEnd);
  const outageOverlay = hasOutage ? overlayStyle(outageStart, outageEnd) : null;
  const nowOverlay = (() => {
    const now = Date.now();
    if (now < windowStart.getTime() || now > windowEnd.getTime()) return null;
    return { left: `${((now - windowStart.getTime()) / totalMs) * 100}%` };
  })();

  if (envs.length === 0) return null;

  const minTimelineWidth = Math.max(560, totalDays * 48);

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Typography variant="subtitle2">Bookings around the proposed change</Typography>
        <Typography variant="caption" color="text.secondary">
          (readonly · {daysEachSide}d either side)
        </Typography>
        {loading && <CircularProgress size={14} sx={{ ml: 0.5 }} />}
      </Box>

      <Box sx={{ overflowX: 'auto' }}>
        <Box sx={{ minWidth: LABEL_COL_WIDTH + minTimelineWidth }}>
          {/* Header row with day markers */}
          <Box
            sx={{
              display: 'flex',
              height: HEADER_HEIGHT,
              borderBottom: 1,
              borderColor: 'divider',
            }}
          >
            <Box sx={{ width: LABEL_COL_WIDTH, flexShrink: 0 }} />
            <Box sx={{ flex: 1, position: 'relative' }}>
              {days.map((d, i) => (
                <Box
                  key={i}
                  sx={{
                    position: 'absolute',
                    left: `${(i / totalDays) * 100}%`,
                    width: `${(1 / totalDays) * 100}%`,
                    px: 0.5,
                    borderLeft: i === 0 ? 0 : 1,
                    borderColor: 'divider',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                  }}
                >
                  <Typography variant="caption" sx={{ lineHeight: 1 }}>
                    {dayLabel(d)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1 }}>
                    {weekdayLabel(d)}
                  </Typography>
                </Box>
              ))}
            </Box>
          </Box>

          {/* Rows */}
          <Stack>
            {envs.map((env) => {
              const bookings = bookingsByEnv.get(env.id) ?? [];
              return (
                <Box
                  key={env.id}
                  sx={{
                    display: 'flex',
                    height: ROW_HEIGHT,
                    borderBottom: 1,
                    borderColor: 'divider',
                  }}
                >
                  <Box
                    sx={{
                      width: LABEL_COL_WIDTH,
                      flexShrink: 0,
                      display: 'flex',
                      alignItems: 'center',
                      px: 1,
                      borderRight: 1,
                      borderColor: 'divider',
                    }}
                  >
                    <Typography variant="body2" noWrap title={env.name}>
                      {env.name}
                    </Typography>
                  </Box>
                  <Box sx={{ flex: 1, position: 'relative' }}>
                    {/* Day gridlines */}
                    {days.map((_, i) => (
                      <Box
                        key={i}
                        sx={{
                          position: 'absolute',
                          top: 0,
                          bottom: 0,
                          left: `${(i / totalDays) * 100}%`,
                          borderLeft: i === 0 ? 0 : 1,
                          borderColor: 'divider',
                          opacity: 0.5,
                        }}
                      />
                    ))}
                    {/* Booking bars */}
                    {bookings.map((b) => {
                      const style = barStyle(b.start_date, b.end_date);
                      if (!style) return null;
                      const color = STATUS_COLORS[b.status] ?? '#bdbdbd';
                      return (
                        <Tooltip
                          key={b.id}
                          title={
                            <Box>
                              <Typography variant="caption" component="div">
                                <strong>{b.project_name}</strong> · {b.status}
                              </Typography>
                              <Typography variant="caption" component="div">
                                {new Date(b.start_date).toLocaleString()} →{' '}
                                {new Date(b.end_date).toLocaleString()}
                              </Typography>
                            </Box>
                          }
                          arrow
                        >
                          <Box
                            sx={{
                              position: 'absolute',
                              top: 4,
                              bottom: 4,
                              left: style.left,
                              width: style.width,
                              bgcolor: color,
                              borderRadius: 0.5,
                              display: 'flex',
                              alignItems: 'center',
                              px: 0.75,
                              overflow: 'hidden',
                              cursor: 'default',
                              color: 'rgba(0,0,0,0.87)',
                            }}
                          >
                            <Typography
                              variant="caption"
                              noWrap
                              sx={{ fontWeight: 500, lineHeight: 1 }}
                            >
                              {b.project_name}
                            </Typography>
                          </Box>
                        </Tooltip>
                      );
                    })}
                  </Box>
                </Box>
              );
            })}
          </Stack>

          {/* Vertical overlays — proposed change + outage + now marker —
              rendered as an absolute layer over the timeline area only. */}
          <Box
            sx={{
              position: 'relative',
              pointerEvents: 'none',
              ml: `${LABEL_COL_WIDTH}px`,
              mt: `-${HEADER_HEIGHT + envs.length * ROW_HEIGHT}px`,
              height: HEADER_HEIGHT + envs.length * ROW_HEIGHT,
            }}
          >
            {nowOverlay && (
              <Box
                sx={{
                  position: 'absolute',
                  top: HEADER_HEIGHT,
                  bottom: 0,
                  left: nowOverlay.left,
                  borderLeft: '1px dashed',
                  borderColor: 'text.secondary',
                  opacity: 0.6,
                }}
              />
            )}
            {proposedOverlay && (
              <Box
                sx={{
                  position: 'absolute',
                  top: HEADER_HEIGHT,
                  bottom: 0,
                  left: proposedOverlay.left,
                  width: proposedOverlay.width,
                  bgcolor: 'primary.main',
                  opacity: 0.18,
                }}
              />
            )}
            {outageOverlay && (
              <Box
                sx={{
                  position: 'absolute',
                  top: HEADER_HEIGHT,
                  bottom: 0,
                  left: outageOverlay.left,
                  width: outageOverlay.width,
                  bgcolor: 'error.main',
                  opacity: 0.25,
                }}
              />
            )}
          </Box>
        </Box>
      </Box>

      {/* Legend */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mt: 1 }}>
        {Object.entries(STATUS_COLORS).map(([status, color]) => (
          <Box key={status} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 10, height: 10, bgcolor: color, borderRadius: 0.5 }} />
            <Typography variant="caption" color="text.secondary">
              {status}
            </Typography>
          </Box>
        ))}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Box
            sx={{
              width: 10,
              height: 10,
              bgcolor: 'primary.main',
              opacity: 0.35,
              borderRadius: 0.5,
            }}
          />
          <Typography variant="caption" color="text.secondary">
            proposed change
          </Typography>
        </Box>
        {hasOutage && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box
              sx={{
                width: 10,
                height: 10,
                bgcolor: 'error.main',
                opacity: 0.35,
                borderRadius: 0.5,
              }}
            />
            <Typography variant="caption" color="text.secondary">
              outage window
            </Typography>
          </Box>
        )}
      </Box>
    </Paper>
  );
}
