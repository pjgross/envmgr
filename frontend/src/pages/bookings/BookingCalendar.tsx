import { useCallback, useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import interactionPlugin from '@fullcalendar/interaction';
import type { EventClickArg, EventContentArg, EventInput } from '@fullcalendar/core';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { AppDispatch, RootState } from '../../store';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { BookingResponse } from '../../types/booking';
import type { AllowedTransition } from '../../types/bookingLifecycle';
import { bookingService } from '../../services/bookingService';
import BookingForm from './BookingForm';
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay';
import TransitionButtons from '../../components/bookings/TransitionButtons';
import ConflictIndicator from '../../components/bookings/ConflictIndicator';
import { ContentionMarker } from '../../components/bookings/ContentionMarker';
import { PROTECTED_MARKER } from '../../constants/protection';

const STATUS_COLORS: Record<string, string> = {
  pending: '#9e9e9e',
  approved: '#4caf50',
  rejected: '#f44336',
};

// Exported for its own test: FullCalendar's DOM is not a useful assertion
// target in jsdom, and the mapping IS the behaviour here.
// eslint-disable-next-line react-refresh/only-export-components
export function bookingToEvent(booking: BookingResponse): EventInput {
  const base =
    booking.request?.project_name && booking.environment_name
      ? `${booking.request.project_name} — ${booking.environment_name}`
      : booking.project_name;
  // Absent means the response did not say — not "soft". Marking it would be a
  // guess in the direction that matters most.
  const isProtected = booking.protection_level === 'hard';

  return {
    id: booking.id.toString(),
    title: isProtected ? `${base} · ${PROTECTED_MARKER}` : base,
    start: booking.start_date,
    end: booking.end_date,
    // Status keeps the fill; protection is additive, so the status legend
    // still means what it says.
    backgroundColor: STATUS_COLORS[booking.status] ?? '#1976d2',
    borderColor: isProtected ? '#5e35b1' : (STATUS_COLORS[booking.status] ?? '#1976d2'),
    ...(isProtected ? { classNames: ['booking-protected'] } : {}),
    extendedProps: { booking },
  };
}

// Exported for its own test, for the same reason as `bookingToEvent` above:
// FullCalendar's own DOM is not a reliable assertion target in jsdom, and
// unlike the protection marker (plain text folded into `event.title`), B6's
// `ContentionMarker` is a React component (an icon + a label) that has to be
// attached through FullCalendar's `eventContent` render prop rather than a
// string. `eventContent` REPLACES FullCalendar's own title rendering, so the
// title is rendered here explicitly alongside the marker — an omission would
// silently blank every event's text.
//
// Renders NOTHING when `contention_state` is null — the common case, not an
// edge case — matching Task 6's list-column contract exactly (never an empty
// marker); see ContentionMarker's own docstring for why the component has no
// branch for that at all.
// eslint-disable-next-line react-refresh/only-export-components
export function renderEventContent(arg: EventContentArg) {
  const booking: BookingResponse = arg.event.extendedProps.booking;
  return (
    <Box sx={{ overflow: 'hidden', width: '100%' }}>
      <Typography variant="caption" component="div" noWrap>
        {arg.event.title}
      </Typography>
      {booking.contention_state && (
        <span data-testid="contention-marker">
          <ContentionMarker state={booking.contention_state} />
        </span>
      )}
    </Box>
  );
}

export default function BookingCalendar() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  // NOT from state.booking: that slice is BookingList's current filtered page
  // since the C3 conversion, and a calendar needs a month of bookings rather
  // than one grid page. Same fix three release-slice consumers received.
  const [bookings, setBookings] = useState<BookingResponse[]>([]);
  const [loading, setLoading] = useState(false);
  // Not the shared environment slice: same reason as the booking fetch
  // above — that slice is BookingList's grid page now, not the full list, and
  // this filter dropdown wants every environment.
  const { environments, truncated: environmentsTruncated } = useAllEnvironments();
  const bookingCustomFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  );

  const [selectedBooking, setSelectedBooking] = useState<BookingResponse | null>(null);
  const [selectedTransitions, setSelectedTransitions] = useState<AllowedTransition[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [envFilter, setEnvFilter] = useState<number | ''>('');

  const loadBookings = useCallback((environmentId?: number) => {
    setLoading(true);
    bookingService
      .listBookings(environmentId !== undefined ? { environment_id: environmentId } : undefined)
      .then((page) => setBookings(page.rows))
      .catch(() => setBookings([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    dispatch(fetchDefinitions('booking'));
    loadBookings();
  }, [dispatch, loadBookings]);

  const handleEnvFilter = (envId: number | '') => {
    setEnvFilter(envId);
    loadBookings(envId === '' ? undefined : envId);
  };

  const handleEventClick = async (info: EventClickArg) => {
    const booking: BookingResponse = info.event.extendedProps.booking;
    setSelectedBooking(booking);
    setTransitionError(null);
    setDrawerOpen(true);
    try {
      const transitions = await bookingService.getAllowedTransitions(booking.id);
      setSelectedTransitions(transitions);
    } catch {
      setSelectedTransitions([]);
    }
  };

  const handleTransition = async (toState: string) => {
    if (!selectedBooking) return;
    setTransitionError(null);
    try {
      await bookingService.transitionState(selectedBooking.id, toState);
      const [updated, transitions] = await Promise.all([
        bookingService.getBooking(selectedBooking.id),
        bookingService.getAllowedTransitions(selectedBooking.id),
      ]);
      setSelectedBooking(updated);
      setSelectedTransitions(transitions);
      loadBookings(envFilter === '' ? undefined : envFilter);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Transition failed';
      setTransitionError(message);
    }
  };

  const events: EventInput[] = bookings.map(bookingToEvent);

  return (
    <Box sx={{ p: 3 }}>
      {/* Toolbar */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Bookings
        </Typography>

        {/* Environment filter */}
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Filter by Environment</InputLabel>
          <Select
            value={envFilter}
            label="Filter by Environment"
            onChange={(e) => handleEnvFilter(e.target.value as number | '')}
          >
            <MenuItem value="">All environments</MenuItem>
            {environments.map((env) => (
              <MenuItem key={env.id} value={env.id}>
                {env.name}
              </MenuItem>
            ))}
          </Select>
          {environmentsTruncated && (
            <FormHelperText>Only the first {environments.length} environments are shown.</FormHelperText>
          )}
        </FormControl>

        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setFormOpen(true)}>
          New Booking
        </Button>
      </Box>

      {loading && (
        <Typography color="text.secondary" sx={{ mb: 1 }}>
          Loading...
        </Typography>
      )}

      {/* Calendar */}
      <FullCalendar
        plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
        initialView="dayGridMonth"
        headerToolbar={{
          left: 'prev,next today',
          center: 'title',
          right: 'dayGridMonth,timeGridWeek',
        }}
        events={events}
        eventClick={handleEventClick}
        eventContent={renderEventContent}
        height="auto"
      />

      {/* Booking Detail Drawer */}
      <Drawer
        anchor="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{ sx: { width: 360, p: 3 } }}
      >
        {selectedBooking && (
          <Box>
            <Typography
              variant="h6"
              gutterBottom
              sx={{ cursor: 'pointer', '&:hover': { textDecoration: 'underline' } }}
              onClick={() => navigate(`/bookings/${selectedBooking.id}`)}
            >
              {selectedBooking.request?.project_name ?? selectedBooking.project_name}
            </Typography>

            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
              <Chip
                label={selectedBooking.status}
                size="small"
                sx={{
                  bgcolor: STATUS_COLORS[selectedBooking.status],
                  color: '#fff',
                }}
              />
              {selectedBooking.has_unacknowledged_conflicts && <ConflictIndicator />}
            </Box>

            <Divider sx={{ mb: 2 }} />

            <Typography variant="body2" color="text.secondary">
              Environment
            </Typography>
            <Typography variant="body1" gutterBottom>
              {selectedBooking.environment_name ?? `ID: ${selectedBooking.environment_id}`}
            </Typography>

            <Typography variant="body2" color="text.secondary">
              Type
            </Typography>
            <Typography variant="body1" gutterBottom>
              {selectedBooking.booking_type_id}
            </Typography>

            <Typography variant="body2" color="text.secondary">
              Start
            </Typography>
            <Typography variant="body1" gutterBottom>
              {new Date(selectedBooking.start_date).toLocaleString()}
            </Typography>

            <Typography variant="body2" color="text.secondary">
              End
            </Typography>
            <Typography variant="body1" gutterBottom>
              {new Date(selectedBooking.end_date).toLocaleString()}
            </Typography>

            {selectedBooking.notes && (
              <>
                <Typography variant="body2" color="text.secondary">
                  Notes
                </Typography>
                <Typography variant="body1" gutterBottom>
                  {selectedBooking.notes}
                </Typography>
              </>
            )}

            <Typography variant="body2" color="text.secondary">
              Booked by
            </Typography>
            <Typography variant="body1" gutterBottom>
              {selectedBooking.booked_by_username ?? `User #${selectedBooking.booked_by}`}
            </Typography>

            {selectedBooking.context_tag !== 'none' && (
              <>
                <Typography variant="body2" color="text.secondary">
                  Context
                </Typography>
                <Typography variant="body1" gutterBottom>
                  {selectedBooking.context_tag}
                </Typography>
              </>
            )}

            {selectedBooking.recurrence_rule && (
              <>
                <Typography variant="body2" color="text.secondary">
                  Recurrence Rule
                </Typography>
                <Typography
                  variant="body1"
                  gutterBottom
                  sx={{ fontFamily: 'monospace', fontSize: 12 }}
                >
                  {selectedBooking.recurrence_rule}
                </Typography>
              </>
            )}

            {bookingCustomFieldDefs.length > 0 && selectedBooking?.custom_fields && (
              <>
                <Divider sx={{ my: 1 }} />
                <CustomFieldsDisplay
                  definitions={bookingCustomFieldDefs}
                  values={selectedBooking.custom_fields}
                />
              </>
            )}

            <Divider sx={{ my: 2 }} />

            {transitionError && (
              <Alert severity="error" sx={{ mb: 1 }}>
                {transitionError}
              </Alert>
            )}

            <TransitionButtons
              transitions={selectedTransitions}
              onTransition={handleTransition}
              size="small"
            />

            <Button
              variant="text"
              size="small"
              sx={{ mt: 1 }}
              onClick={() => navigate(`/bookings/${selectedBooking.id}`)}
            >
              View full details
            </Button>
          </Box>
        )}
      </Drawer>

      {/* New Booking Form */}
      <BookingForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        defaultEnvId={envFilter !== '' ? (envFilter as number) : undefined}
        // This component doesn't read the booking slice at all (see the note
        // above), so it must supply its own reload — the same one used after
        // a transition — not a bare dispatch(fetchBookings()).
        onCreated={() => loadBookings(envFilter === '' ? undefined : envFilter)}
      />
    </Box>
  );
}
