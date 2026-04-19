/**
 * ReleaseCalendar — FullCalendar view of release phases.
 * Backed by GET /api/v1/releases/calendar?from=&to=
 * Click a phase event → /releases/:releaseId?tab=phases&phase=:phaseId
 */
import { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import type { EventClickArg, EventInput, DatesSetArg } from '@fullcalendar/core';
import { Box, CircularProgress, Typography } from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseCalendar } from '../../store/releaseSlice';

const PHASE_STATUS_COLORS: Record<string, string> = {
  pending: '#9e9e9e',
  in_progress: '#1976d2',
  completed: '#388e3c',
  skipped: '#bdbdbd',
};

function toCalendarEvents(entries: RootState['release']['calendar']): EventInput[] {
  return entries
    .filter((e) => e.start_date)
    .map((e) => {
      const color = PHASE_STATUS_COLORS[e.status] ?? '#1976d2';
      return {
        id: `${e.release_id}-${e.phase_id}`,
        title: `[${e.release_name}] ${e.phase_name}`,
        start: e.start_date!,
        end: e.end_date ?? e.start_date!,
        backgroundColor: color,
        borderColor: color,
        extendedProps: { entry: e },
      };
    });
}

export default function ReleaseCalendar() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { calendar, loading } = useSelector((state: RootState) => state.release);

  // Track the current visible date range so we can re-fetch on navigation
  const rangeRef = useRef<{ from: string; to: string } | null>(null);

  const loadRange = (from: string, to: string) => {
    rangeRef.current = { from, to };
    dispatch(fetchReleaseCalendar({ from, to }));
  };

  const handleDatesSet = (arg: DatesSetArg) => {
    const from = arg.startStr.slice(0, 10);
    const to = arg.endStr.slice(0, 10);
    loadRange(from, to);
  };

  // Load current month on mount
  useEffect(() => {
    const now = new Date();
    const from = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
    const to = new Date(now.getFullYear(), now.getMonth() + 2, 0).toISOString().slice(0, 10);
    loadRange(from, to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleEventClick = (info: EventClickArg) => {
    const entry = info.event.extendedProps.entry as RootState['release']['calendar'][number];
    navigate(`/releases/${entry.release_id}?tab=phases&phase=${entry.phase_id}`);
  };

  const events = toCalendarEvents(calendar);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Release Calendar
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Phase timeline for all active releases. Click a phase to open the release.
      </Typography>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      <Box
        sx={{
          '& .fc-event': { cursor: 'pointer' },
          '& .fc': { fontSize: '0.875rem' },
        }}
      >
        <FullCalendar
          plugins={[dayGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          headerToolbar={{
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,dayGridWeek',
          }}
          events={events}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          height="auto"
          eventDisplay="block"
          dayMaxEventRows={4}
        />
      </Box>
    </Box>
  );
}
