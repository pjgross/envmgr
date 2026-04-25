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
  type ScheduleDeployment,
} from '../../services/scheduleService';
import { formatApiError } from '../../services/apiError';

// Blue palette for bookings, orange for regular CRs, red for outage CRs —
// keeps the three kinds visually distinct on a shared timeline.
const BOOKING_COLOR = '#1976d2';
const CR_COLOR = '#ed6c02';
const CR_OUTAGE_COLOR = '#d32f2f';

const DEP_COLORS: Record<string, string> = {
  pending: '#607d8b',
  in_progress: '#607d8b',
  success: '#43a047',
  failed: '#e53935',
  rolled_back: '#ffb300',
};

interface EnvironmentScheduleProps {
  envId: number;
}

type EventExtProps =
  | { kind: 'booking'; booking: ScheduleBooking }
  | { kind: 'cr'; changeRequest: ScheduleChangeRequest }
  | { kind: 'deployment'; deployment: ScheduleDeployment };

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

function deploymentToEvent(d: ScheduleDeployment): EventInput {
  const color = DEP_COLORS[d.status] ?? '#607d8b';
  return {
    id: `deployment-${d.id}`,
    title: `Deploy ${d.build_sha_short} (${d.status})`,
    start: d.deployed_at,
    end: d.deployed_at,
    backgroundColor: color,
    borderColor: color,
    extendedProps: { kind: 'deployment', deployment: d } as EventExtProps,
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
    ...(data?.deployments ?? []).map(deploymentToEvent),
  ];

  const handleEventClick = (arg: EventClickArg) => {
    const ext = arg.event.extendedProps as EventExtProps;
    if (ext.kind === 'booking') {
      navigate(`/bookings/${ext.booking.id}`);
    } else if (ext.kind === 'cr') {
      navigate(`/change-requests/${ext.changeRequest.id}`);
    } else {
      navigate(`/deployments/${ext.deployment.id}`);
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
          <Chip
            label="Deploy success"
            size="small"
            sx={{ backgroundColor: DEP_COLORS.success, color: 'white' }}
          />
          <Chip
            label="Deploy failed"
            size="small"
            sx={{ backgroundColor: DEP_COLORS.failed, color: 'white' }}
          />
          <Chip
            label="Deploy in-progress"
            size="small"
            sx={{ backgroundColor: DEP_COLORS.in_progress, color: 'white' }}
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
