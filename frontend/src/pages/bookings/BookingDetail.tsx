import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { AppDispatch } from '../../store'
import type { RootState } from '../../store'
import { fetchBookingTypes, fetchLifecycleTemplates } from '../../store/bookingLifecycleSlice'
import { fetchDefinitions } from '../../store/customFieldSlice'
import { bookingService } from '../../services/bookingService'
import type { BookingResponse } from '../../types/booking'
import type { BookingStatusHistory, AllowedTransition } from '../../types/bookingLifecycle'
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay'
import CustomFieldsSection from '../../components/CustomFieldsSection'
import TransitionButtons from '../../components/bookings/TransitionButtons'

// --- Status colour map -------------------------------------------------------

const STATE_COLOURS: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  extension_requested: 'warning',
  closed: 'info',
}

// --- Component ---------------------------------------------------------------

export default function BookingDetail() {
  const { id } = useParams<{ id: string }>()
  const bookingId = Number(id)
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['booking'] ?? [])
  const bookingTypes = useSelector((state: RootState) => state.bookingLifecycle.bookingTypes)

  // Local state
  const [booking, setBooking] = useState<BookingResponse | null>(null)
  const [allowedTransitions, setAllowedTransitions] = useState<AllowedTransition[]>([])
  const [history, setHistory] = useState<BookingStatusHistory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingCustomFields, setEditingCustomFields] = useState(false)
  const [cfEditValues, setCfEditValues] = useState<Record<string, unknown>>({})
  const [cfSaving, setCfSaving] = useState(false)
  const [editingStandardFields, setEditingStandardFields] = useState(false)
  const [sfEditValues, setSfEditValues] = useState<Record<string, unknown>>({})
  const [sfSaving, setSfSaving] = useState(false)

  // Load on mount
  useEffect(() => {
    dispatch(fetchBookingTypes())
    dispatch(fetchLifecycleTemplates())
    dispatch(fetchDefinitions('booking'))

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const [b, transitions, hist] = await Promise.all([
          bookingService.getBooking(bookingId),
          bookingService.getAllowedTransitions(bookingId),
          bookingService.getHistory(bookingId),
        ])
        setBooking(b)
        setAllowedTransitions(transitions)
        setHistory(hist)
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Failed to load booking'
        setError(msg)
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [bookingId, dispatch])

  // Transition handler
  const handleTransition = async (toState: string, label: string) => {
    const notes =
      toState === 'draft' ? (window.prompt(`Reason for "${label}":`) ?? undefined) : undefined
    try {
      await bookingService.transitionState(bookingId, toState, notes)
      const [updated, transitions, hist] = await Promise.all([
        bookingService.getBooking(bookingId),
        bookingService.getAllowedTransitions(bookingId),
        bookingService.getHistory(bookingId),
      ])
      setBooking(updated)
      setAllowedTransitions(transitions)
      setHistory(hist)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Transition failed'
      setError(msg)
    }
  }

  // --- Render states ---

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (error && !booking) {
    return (
      <Box sx={{ p: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/bookings/list')}
          sx={{ mb: 2 }}
        >
          Back to Bookings
        </Button>
        <Alert severity="error">{error}</Alert>
      </Box>
    )
  }

  if (!booking) return null

  // --- Main render ---

  return (
    <Box sx={{ p: 3, maxWidth: 800 }}>
      {/* Back button */}
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/bookings/list')}
        sx={{ mb: 2 }}
      >
        Back to Bookings
      </Button>

      {/* Title + status badge */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Typography variant="h5" fontWeight="bold">
          {booking.project_name}
        </Typography>
        <Chip
          label={booking.status}
          color={STATE_COLOURS[booking.status] ?? 'default'}
          size="small"
        />
      </Box>

      {/* Error banner (transition errors) */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Action buttons from allowed transitions */}
      {allowedTransitions.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <TransitionButtons transitions={allowedTransitions} onTransition={handleTransition} />
        </Box>
      )}

      {/* Booking details */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        {/* Show Edit button if any standard field is editable */}
        {(() => {
          const sfPerms = booking.standard_field_permissions ?? {};
          const hasEditable = Object.values(sfPerms).some((p) => p.editable);
          if (!hasEditable) return null;
          return (
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
              <Button
                size="small"
                onClick={() => {
                  setSfEditValues({
                    project_name: booking.project_name,
                    start_date: booking.start_date.slice(0, 10),
                    end_date: booking.end_date.slice(0, 10),
                    booking_type: booking.booking_type_id,
                    notes: booking.notes ?? '',
                    exclusive_use: booking.exclusive_use,
                    context_tag: booking.context_tag,
                  });
                  setEditingStandardFields(true);
                }}
              >
                Edit
              </Button>
            </Box>
          );
        })()}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: '180px 1fr',
            rowGap: 1.5,
            columnGap: 2,
          }}
        >
          <Typography variant="body2" color="text.secondary">Project Name</Typography>
          <Typography variant="body2">{booking.project_name}</Typography>

          <Typography variant="body2" color="text.secondary">Environment</Typography>
          <Typography variant="body2">{booking.environment_name ?? '—'}</Typography>

          <Typography variant="body2" color="text.secondary">Status</Typography>
          <Box>
            <Chip
              label={booking.status}
              color={STATE_COLOURS[booking.status] ?? 'default'}
              size="small"
            />
          </Box>

          <Typography variant="body2" color="text.secondary">Booked By</Typography>
          <Typography variant="body2">{booking.booked_by_username ?? '—'}</Typography>

          <Typography variant="body2" color="text.secondary">Start Date</Typography>
          <Typography variant="body2">
            {new Date(booking.start_date).toLocaleDateString()}
          </Typography>

          <Typography variant="body2" color="text.secondary">End Date</Typography>
          <Typography variant="body2">
            {new Date(booking.end_date).toLocaleDateString()}
          </Typography>

          <Typography variant="body2" color="text.secondary">Exclusive Use</Typography>
          <Box>
            <Chip
              label={booking.exclusive_use ? 'Yes' : 'No'}
              color={booking.exclusive_use ? 'warning' : 'default'}
              size="small"
            />
          </Box>

          <Typography variant="body2" color="text.secondary">Context Tag</Typography>
          <Typography variant="body2">{booking.context_tag}</Typography>

          <Typography variant="body2" color="text.secondary" sx={{ pt: 0.5 }}>Notes</Typography>
          <Typography variant="body2">{booking.notes ?? '—'}</Typography>
        </Box>
      </Paper>

      {/* Custom Fields */}
      {(() => {
        const perms = booking.custom_field_permissions ?? {};
        const visibleDefs = customFieldDefs.filter((d) => d.field_key in perms);
        const editableDefs = visibleDefs.filter((d) => perms[d.field_key]?.editable);
        if (visibleDefs.length === 0) return null;
        return (
          <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle2">Custom Fields</Typography>
              {editableDefs.length > 0 && (
                <Button
                  size="small"
                  onClick={() => {
                    setCfEditValues(
                      Object.fromEntries(
                        editableDefs.map((d) => [d.field_key, booking.custom_fields?.[d.field_key] ?? ''])
                      )
                    );
                    setEditingCustomFields(true);
                  }}
                >
                  Edit
                </Button>
              )}
            </Box>
            <CustomFieldsDisplay definitions={visibleDefs} values={booking.custom_fields} />
          </Paper>
        );
      })()}

      <Divider />

      {/* History */}
      <Box sx={{ mt: 3 }}>
        <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
          History
        </Typography>
        {history.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No history yet.
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {history.map((row) => (
              <Box key={row.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ minWidth: 150 }}
                >
                  {new Date(row.changed_at).toLocaleString()}
                </Typography>
                {row.from_state ? (
                  <>
                    <Chip label={row.from_state} size="small" />
                    <Typography variant="caption">→</Typography>
                    <Chip label={row.to_state} size="small" color="primary" />
                  </>
                ) : (
                  <>
                    <Typography variant="caption">Created as</Typography>
                    <Chip label={row.to_state} size="small" />
                  </>
                )}
                {row.notes && (
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    {row.notes}
                  </Typography>
                )}
              </Box>
            ))}
          </Box>
        )}
      </Box>

      {/* Edit Standard Fields Dialog */}
      <Dialog open={editingStandardFields} onClose={() => setEditingStandardFields(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Standard Fields</DialogTitle>
        <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {(() => {
            const sfPerms = booking?.standard_field_permissions ?? {};
            const canEdit = (field: string) => sfPerms[field]?.editable === true;
            return (
              <>
                <TextField
                  label="Project Name"
                  value={(sfEditValues.project_name as string) ?? ''}
                  onChange={(e) => setSfEditValues((v) => ({ ...v, project_name: e.target.value }))}
                  disabled={!canEdit('project_name')}
                  fullWidth
                  size="small"
                />
                <TextField
                  label="Start Date"
                  type="date"
                  value={(sfEditValues.start_date as string) ?? ''}
                  onChange={(e) => setSfEditValues((v) => ({ ...v, start_date: e.target.value }))}
                  disabled={!canEdit('start_date')}
                  fullWidth
                  size="small"
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  label="End Date"
                  type="date"
                  value={(sfEditValues.end_date as string) ?? ''}
                  onChange={(e) => setSfEditValues((v) => ({ ...v, end_date: e.target.value }))}
                  disabled={!canEdit('end_date')}
                  fullWidth
                  size="small"
                  InputLabelProps={{ shrink: true }}
                />
                <FormControl fullWidth size="small" disabled={!canEdit('booking_type')}>
                  <InputLabel>Booking Type</InputLabel>
                  <Select
                    label="Booking Type"
                    value={(sfEditValues.booking_type as number) ?? ''}
                    onChange={(e) => setSfEditValues((v) => ({ ...v, booking_type: e.target.value }))}
                  >
                    {bookingTypes.map((bt) => (
                      <MenuItem key={bt.id} value={bt.id}>{bt.name}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Notes"
                  value={(sfEditValues.notes as string) ?? ''}
                  onChange={(e) => setSfEditValues((v) => ({ ...v, notes: e.target.value }))}
                  disabled={!canEdit('notes')}
                  fullWidth
                  size="small"
                  multiline
                  minRows={3}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={(sfEditValues.exclusive_use as boolean) ?? false}
                      onChange={(e) => setSfEditValues((v) => ({ ...v, exclusive_use: e.target.checked }))}
                      disabled={!canEdit('exclusive_use')}
                    />
                  }
                  label="Exclusive Use"
                />
                <FormControl fullWidth size="small" disabled={!canEdit('context_tag')}>
                  <InputLabel>Context Tag</InputLabel>
                  <Select
                    label="Context Tag"
                    value={(sfEditValues.context_tag as string) ?? 'none'}
                    onChange={(e) => setSfEditValues((v) => ({ ...v, context_tag: e.target.value }))}
                  >
                    <MenuItem value="none">None</MenuItem>
                    <MenuItem value="deployment">Deployment</MenuItem>
                    <MenuItem value="regression">Regression</MenuItem>
                  </Select>
                </FormControl>
              </>
            );
          })()}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditingStandardFields(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={sfSaving}
            onClick={async () => {
              setSfSaving(true);
              try {
                // Only send editable fields
                const sfPerms = booking?.standard_field_permissions ?? {};
                const payload: Record<string, unknown> = {};
                const fieldMap: Record<string, string> = {
                  project_name: 'project_name',
                  start_date: 'start_date',
                  end_date: 'end_date',
                  booking_type: 'booking_type_id',
                  notes: 'notes',
                  exclusive_use: 'exclusive_use',
                  context_tag: 'context_tag',
                };
                for (const [key, apiKey] of Object.entries(fieldMap)) {
                  if (sfPerms[key]?.editable) {
                    payload[apiKey] = sfEditValues[key];
                  }
                }
                const updated = await bookingService.updateStandardFields(bookingId, payload);
                setBooking(updated);
                setEditingStandardFields(false);
              } catch (err: unknown) {
                const msg =
                  (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
                  'Save failed';
                setError(msg);
              } finally {
                setSfSaving(false);
              }
            }}
          >
            {sfSaving ? 'Saving...' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit Custom Fields Dialog */}
      <Dialog open={editingCustomFields} onClose={() => setEditingCustomFields(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Custom Fields</DialogTitle>
        <DialogContent sx={{ pt: 2 }}>
          {(() => {
            const perms = booking?.custom_field_permissions ?? {};
            const editableDefs = customFieldDefs.filter((d) => perms[d.field_key]?.editable);
            return (
              <CustomFieldsSection
                definitions={editableDefs}
                values={cfEditValues}
                onChange={setCfEditValues}
              />
            );
          })()}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditingCustomFields(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={cfSaving}
            onClick={async () => {
              setCfSaving(true);
              try {
                const updated = await bookingService.updateCustomFields(bookingId, cfEditValues);
                setBooking(updated);
                setEditingCustomFields(false);
              } catch (err: unknown) {
                const msg =
                  (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
                  'Save failed';
                setError(msg);
              } finally {
                setCfSaving(false);
              }
            }}
          >
            {cfSaving ? 'Saving...' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
