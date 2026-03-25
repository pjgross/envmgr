import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import interactionPlugin from '@fullcalendar/interaction';
import type { EventClickArg, EventInput } from '@fullcalendar/core';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { AppDispatch, RootState } from '../../store';
import { fetchBookings, approveBooking, rejectBooking, cancelBooking } from '../../store/bookingSlice';
import { fetchEnvironments } from '../../store/environmentSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { BookingResponse } from '../../types/booking';
import BookingForm from './BookingForm';
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay';

const STATUS_COLORS: Record<string, string> = {
  pending: '#9e9e9e',
  approved: '#4caf50',
  rejected: '#f44336',
};

function bookingToEvent(booking: BookingResponse): EventInput {
  return {
    id: booking.id.toString(),
    title: booking.project_name,
    start: booking.start_date,
    end: booking.end_date,
    backgroundColor: STATUS_COLORS[booking.status] ?? '#1976d2',
    borderColor: STATUS_COLORS[booking.status] ?? '#1976d2',
    extendedProps: { booking },
  };
}

export default function BookingCalendar() {
  const dispatch = useDispatch<AppDispatch>();
  const { bookings, loading } = useSelector((state: RootState) => state.booking);
  const environments = useSelector((state: RootState) => state.environment.environments);
  const user = useSelector((state: RootState) => state.auth.user);
  const bookingCustomFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  );

  const [selectedBooking, setSelectedBooking] = useState<BookingResponse | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [envFilter, setEnvFilter] = useState<number | ''>('');
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  useEffect(() => {
    dispatch(fetchEnvironments());
    dispatch(fetchBookings());
    dispatch(fetchDefinitions('booking'));
  }, [dispatch]);

  const handleEnvFilter = (envId: number | '') => {
    setEnvFilter(envId);
    dispatch(fetchBookings(envId !== '' ? { environment_id: envId as number } : undefined));
  };

  const handleEventClick = (info: EventClickArg) => {
    const booking: BookingResponse = info.event.extendedProps.booking;
    setSelectedBooking(booking);
    setDrawerOpen(true);
  };

  const canApproveReject =
    user?.is_master_admin || user?.role === 'Admin' || user?.role === 'Release Manager';

  const canCancel = (booking: BookingResponse) =>
    booking.booked_by === user?.id || user?.is_master_admin || user?.role === 'Admin';

  const handleApprove = async () => {
    if (!selectedBooking) return;
    const result = await dispatch(approveBooking(selectedBooking.id));
    if (approveBooking.fulfilled.match(result)) {
      setSelectedBooking(result.payload);
      setSnackbar({ open: true, message: 'Booking approved.', severity: 'success' });
      dispatch(fetchBookings(envFilter !== '' ? { environment_id: envFilter as number } : undefined));
    }
  };

  const handleReject = async () => {
    if (!selectedBooking) return;
    const result = await dispatch(rejectBooking(selectedBooking.id));
    if (rejectBooking.fulfilled.match(result)) {
      setSelectedBooking(result.payload);
      setSnackbar({ open: true, message: 'Booking rejected.', severity: 'success' });
      dispatch(fetchBookings(envFilter !== '' ? { environment_id: envFilter as number } : undefined));
    }
  };

  const handleCancel = async () => {
    if (!selectedBooking) return;
    const result = await dispatch(cancelBooking(selectedBooking.id));
    if (cancelBooking.fulfilled.match(result)) {
      setDrawerOpen(false);
      setSelectedBooking(null);
      setSnackbar({ open: true, message: 'Booking cancelled.', severity: 'success' });
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
        </FormControl>

        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setFormOpen(true)}
        >
          New Booking
        </Button>
      </Box>

      {loading && <Typography color="text.secondary" sx={{ mb: 1 }}>Loading...</Typography>}

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
            <Typography variant="h6" gutterBottom>
              {selectedBooking.project_name}
            </Typography>

            <Chip
              label={selectedBooking.status}
              size="small"
              sx={{
                bgcolor: STATUS_COLORS[selectedBooking.status],
                color: '#fff',
                mb: 2,
              }}
            />

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
                <Typography variant="body1" gutterBottom sx={{ fontFamily: 'monospace', fontSize: 12 }}>
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

            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {canApproveReject && selectedBooking.status === 'pending' && (
                <>
                  <Button variant="contained" color="success" onClick={handleApprove}>
                    Approve
                  </Button>
                  <Button variant="contained" color="error" onClick={handleReject}>
                    Reject
                  </Button>
                </>
              )}
              {canCancel(selectedBooking) && selectedBooking.status !== 'rejected' && (
                <Button variant="outlined" color="error" onClick={handleCancel}>
                  Cancel Booking
                </Button>
              )}
            </Box>
          </Box>
        )}
      </Drawer>

      {/* New Booking Form */}
      <BookingForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        defaultEnvId={envFilter !== '' ? (envFilter as number) : undefined}
      />

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar((s) => ({ ...s, open: false }))}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
