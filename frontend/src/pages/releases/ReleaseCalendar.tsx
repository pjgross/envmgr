/**
 * ReleaseCalendar — FullCalendar view of release phases.
 * Backed by GET /api/v1/releases/calendar?from=&to=
 * Click a release → /releases/:releaseId. The endpoint returns one entry per
 * RELEASE (ReleaseCalendarEntry has no phase id), so there is nothing finer to
 * link to; a phase-level calendar would need a different endpoint.
 */
import { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import type { EventClickArg, EventInput, DatesSetArg } from '@fullcalendar/core';
import { Box, CircularProgress } from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseCalendar } from '../../store/releaseSlice';
import PageHeader from '../../components/layout/PageHeader';

const RELEASE_STATUS_COLORS: Record<string, string> = {
  draft: '#9e9e9e',
  submitted: '#ffa726',
  approved: '#26a69a',
  in_progress: '#1976d2',
  ready_for_release: '#7e57c2',
  completed: '#388e3c',
  completed_with_issues: '#ef6c00',
  backed_out: '#d32f2f',
  rejected: '#b71c1c',
  cancelled: '#616161',
};

function toCalendarEvents(entries: RootState['release']['calendar']): EventInput[] {
  return entries
    .filter((e) => e.start)
    .map((e) => {
      const color = RELEASE_STATUS_COLORS[e.status] ?? '#1976d2';
      return {
        id: String(e.id),
        title: `${e.title} (${e.release_type})`,
        start: e.start!,
        end: e.end ?? e.start!,
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
    navigate(`/releases/${entry.id}`);
  };

  const events = toCalendarEvents(calendar);

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Release Calendar"
        subtitle="Target and actual dates for all active releases. Click a release to open it."
      />

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
