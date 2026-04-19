import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import interactionPlugin from '@fullcalendar/interaction';
import type { EventClickArg, EventInput, DatesSetArg } from '@fullcalendar/core';
import { Alert, Box, Chip, Paper, Stack, Typography } from '@mui/material';
import {
  scheduleService,
  type EnvironmentScheduleResponse,
  type ScheduleBooking,
  type ScheduleChangeRequest,
} from '../../services/scheduleService';
import { formatApiError } from '../../services/apiError';

// Blue palette for bookings, orange for regular CRs, red for outage CRs —
// keeps the three kinds visually distinct on a shared timeline.
const BOOKING_COLOR = '#1976d2';
const CR_COLOR = '#ed6c02';
const CR_OUTAGE_COLOR = '#d32f2f';

interface EnvironmentScheduleProps {
  envId: number;
}

type EventExtProps =
  | { kind: 'booking'; booking: ScheduleBooking }
  | { kind: 'cr'; changeRequest: ScheduleChangeRequest };

function bookingToEvent(b: ScheduleBooking): EventInput {
  return {
    id: `booking-${b.id}`,
    title: `${b.project_name} — booking`,
    start: b.start_date,
    end: b.end_date,
    backgroundColor: BOOKING_COLOR,
    borderColor: BOOKING_COLOR,
    extendedProps: { kind: 'booking', booking: b } as EventExtProps,
  };
}

function crToEvent(cr: ScheduleChangeRequest): EventInput {
  const color = cr.has_outage ? CR_OUTAGE_COLOR : CR_COLOR;
  return {
    id: `cr-${cr.id}`,
    title: cr.has_outage ? `⚠︎ ${cr.title}` : cr.title,
    start: cr.scheduled_start,
    end: cr.scheduled_end,
    backgroundColor: color,
    borderColor: color,
    extendedProps: { kind: 'cr', changeRequest: cr } as EventExtProps,
  };
}

export default function EnvironmentSchedule({ envId }: EnvironmentScheduleProps) {
  const navigate = useNavigate();
  const [data, setData] = useState<EnvironmentScheduleResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<{ start: Date; end: Date } | null>(null);

  // FullCalendar calls datesSet when the visible window changes (initial mount
  // and every navigation). Use that to drive the backend query.
  const handleDatesSet = useCallback((arg: DatesSetArg) => {
    setRange({ start: arg.start, end: arg.end });
  }, []);

  useEffect(() => {
    if (!range) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    scheduleService
      .getEnvironmentSchedule(envId, range.start, range.end)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err, 'Failed to load schedule'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [envId, range]);

  const events: EventInput[] = [
    ...(data?.bookings ?? []).map(bookingToEvent),
    ...(data?.change_requests ?? []).map(crToEvent),
  ];

  const handleEventClick = (arg: EventClickArg) => {
    const ext = arg.event.extendedProps as EventExtProps;
    if (ext.kind === 'booking') {
      navigate(`/bookings/${ext.booking.id}`);
    } else {
      navigate(`/change-requests/${ext.changeRequest.id}`);
    }
  };

  return (
    <Box>
      <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Typography variant="body2" color="text.secondary">
            Legend:
          </Typography>
          <Chip
            label="Booking"
            size="small"
            sx={{ backgroundColor: BOOKING_COLOR, color: 'white' }}
          />
          <Chip
            label="Change request"
            size="small"
            sx={{ backgroundColor: CR_COLOR, color: 'white' }}
          />
          <Chip
            label="Change request (outage)"
            size="small"
            sx={{ backgroundColor: CR_OUTAGE_COLOR, color: 'white' }}
          />
          {loading && (
            <Typography variant="caption" color="text.secondary">
              Loading…
            </Typography>
          )}
        </Stack>
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2 }}>
        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          headerToolbar={{
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay',
          }}
          events={events}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          height="auto"
        />
      </Paper>
    </Box>
  );
}
