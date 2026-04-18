import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
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
import { fetchEnvironments } from '../../store/environmentSlice'
import { bookingService } from '../../services/bookingService'
import { bookingRequestService } from '../../services/bookingRequestService'
import type { BookingResponse } from '../../types/booking'
import type { BookingRequestResponse } from '../../types/bookingRequest'
import type { BookingStatusHistory, AllowedTransition } from '../../types/bookingLifecycle'
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay'
import TransitionButtons from '../../components/bookings/TransitionButtons'
import EditStandardFieldsDialog from '../../components/bookings/EditStandardFieldsDialog'
import EditCustomFieldsDialog from '../../components/bookings/EditCustomFieldsDialog'
import EnvironmentsPanel from '../../components/bookings/EnvironmentsPanel'
import ConflictsPanel from '../../components/bookings/ConflictsPanel'
import ConflictIndicator from '../../components/bookings/ConflictIndicator'
import EditEnvOverridesDialog from '../../components/bookings/EditEnvOverridesDialog'
import { formatApiError } from '../../services/apiError'

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
  const currentUser = useSelector((state: RootState) => state.auth.user)
  const environments = useSelector((state: RootState) => state.environment.environments)

  // Local state
  const [booking, setBooking] = useState<BookingResponse | null>(null)
  const [bookingRequest, setBookingRequest] = useState<BookingRequestResponse | null>(null)
  const [allowedTransitions, setAllowedTransitions] = useState<AllowedTransition[]>([])
  const [history, setHistory] = useState<BookingStatusHistory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingCustomFields, setEditingCustomFields] = useState(false)
  const [editingStandardFields, setEditingStandardFields] = useState(false)
  const [editingEnvOverrides, setEditingEnvOverrides] = useState(false)
  const [addEnvOpen, setAddEnvOpen] = useState(false)

  // Add-env dialog local state
  const [addEnvId, setAddEnvId] = useState<number | ''>('')
  const [addEnvStart, setAddEnvStart] = useState('')
  const [addEnvEnd, setAddEnvEnd] = useState('')
  const [addEnvSaving, setAddEnvSaving] = useState(false)

  // Load on mount
  useEffect(() => {
    dispatch(fetchBookingTypes())
    dispatch(fetchLifecycleTemplates())
    dispatch(fetchDefinitions('booking'))
    dispatch(fetchEnvironments())

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

        // Fetch request if available (may be null for legacy rows)
        if (b.booking_request_id != null) {
          try {
            const req = await bookingRequestService.get(b.booking_request_id)
            setBookingRequest(req)
          } catch {
            // Legacy row or request not found — leave bookingRequest null
          }
        }
      } catch (err: unknown) {
        setError(formatApiError(err, 'Failed to load booking'))
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [bookingId, dispatch])

  // Transition handler (used for top-level booking transitions outside EnvironmentsPanel)
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
      setError(formatApiError(err, 'Transition failed'))
    }
  }

  // Reset add-env dialog fields
  const resetAddEnvForm = () => {
    setAddEnvId('')
    setAddEnvStart('')
    setAddEnvEnd('')
  }

  // Add-env confirm handler
  const handleAddEnvConfirm = async () => {
    if (!bookingRequest || addEnvId === '') return
    setAddEnvSaving(true)
    try {
      await bookingRequestService.addEnvironment(bookingRequest.id, {
        environment_id: addEnvId as number,
        start_date: addEnvStart || undefined,
        end_date: addEnvEnd || undefined,
      })
      const req = await bookingRequestService.get(bookingRequest.id)
      setBookingRequest(req)
      setAddEnvOpen(false)
      resetAddEnvForm()
    } catch (err: unknown) {
      setError(formatApiError(err, 'Failed to add environment'))
    } finally {
      setAddEnvSaving(false)
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

  // Environments already in this request (to exclude from add-env picker)
  const existingEnvIds = new Set((bookingRequest?.bookings ?? []).map((b) => b.environment_id))
  const availableEnvs = environments.filter((e) => !existingEnvIds.has(e.id))

  // --- Main render ---

  return (
    <Box sx={{ p: 3, maxWidth: 900 }}>
      {/* Back button */}
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/bookings/list')}
        sx={{ mb: 2 }}
      >
        Back to Bookings
      </Button>

      {/* Request context */}
      {booking.request && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="h6">{booking.request.project_name}</Typography>
            <ConflictIndicator hasUnacknowledged={booking.has_unacknowledged_conflicts} />
            <Box sx={{ flexGrow: 1 }} />
            {bookingRequest != null && (
              <Button size="small" onClick={() => setEditingStandardFields(true)}>Edit request</Button>
            )}
          </Box>
        </Paper>
      )}

      {/* Booking status chip (for context when no request block shows, or as supplementary info) */}
      {!booking.request && (
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
      )}

      {/* Error banner (transition errors) */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* EnvironmentsPanel — shows all envs in the request with per-env transitions */}
      {bookingRequest && (
        <EnvironmentsPanel
          requestId={bookingRequest.id}
          envBookings={bookingRequest.bookings}
          highlightBookingId={booking.id}
          onTransition={async (id, toState, label) => {
            const notes = toState === 'draft' ? (window.prompt(`Reason for "${label}":`) ?? undefined) : undefined
            try {
              await bookingService.transitionState(id, toState, notes)
              const req = await bookingRequestService.get(bookingRequest.id)
              setBookingRequest(req)
              if (id === booking.id) {
                const b = await bookingService.getBooking(id)
                setBooking(b)
              }
            } catch (err: unknown) {
              setError(formatApiError(err, 'Transition failed'))
            }
          }}
          onRemove={async (id) => {
            try {
              await bookingRequestService.removeEnvironment(bookingRequest.id, id)
              const req = await bookingRequestService.get(bookingRequest.id)
              setBookingRequest(req)
            } catch (err: unknown) {
              setError(formatApiError(err, 'Failed to remove environment'))
            }
          }}
          onAddClick={() => setAddEnvOpen(true)}
        />
      )}

      {/* Legacy (no request): show transition buttons */}
      {!bookingRequest && allowedTransitions.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <TransitionButtons transitions={allowedTransitions} onTransition={handleTransition} />
        </Box>
      )}

      {/* Booking details — env-level info */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
          <Button size="small" onClick={() => setEditingEnvOverrides(true)}>
            Edit dates
          </Button>
        </Box>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: '180px 1fr',
            rowGap: 1.5,
            columnGap: 2,
          }}
        >
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

          {!bookingRequest && (
            <>
              <Typography variant="body2" color="text.secondary">Project Name</Typography>
              <Typography variant="body2">{booking.project_name}</Typography>

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
            </>
          )}
        </Box>
      </Paper>

      {/* ConflictsPanel */}
      <ConflictsPanel
        bookingId={booking.id}
        canAcknowledge={
          Boolean(currentUser) && (
            currentUser!.id === bookingRequest?.booked_by ||
            (bookingRequest?.delegate_user_ids ?? []).includes(currentUser!.id)
          )
        }
      />

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
              {editableDefs.length > 0 && bookingRequest != null && (
                <Button
                  size="small"
                  onClick={() => setEditingCustomFields(true)}
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

      {/* Edit Standard Fields Dialog — points at request-level update */}
      {booking && bookingRequest != null && (
        <EditStandardFieldsDialog
          open={editingStandardFields}
          booking={booking}
          bookingTypes={bookingTypes}
          onClose={() => setEditingStandardFields(false)}
          onSaved={async (updatedBooking) => {
            setBooking(updatedBooking)
            // Also refresh the request (mirrors project_name, dates, etc.)
            const req = await bookingRequestService.get(bookingRequest.id)
            setBookingRequest(req)
          }}
          saver={async (payload) => {
            await bookingRequestService.updateStandardFields(bookingRequest.id, payload)
            // Re-fetch booking to get mirrored fields
            return bookingService.getBooking(bookingId)
          }}
          onError={setError}
        />
      )}

      {/* Edit Custom Fields Dialog — points at request-level update */}
      {booking && bookingRequest != null && (
        <EditCustomFieldsDialog
          open={editingCustomFields}
          booking={booking}
          definitions={customFieldDefs}
          onClose={() => setEditingCustomFields(false)}
          onSaved={async (updatedBooking) => {
            setBooking(updatedBooking)
            const req = await bookingRequestService.get(bookingRequest.id)
            setBookingRequest(req)
          }}
          saver={async (values) => {
            await bookingRequestService.updateCustomFields(bookingRequest.id, values)
            return bookingService.getBooking(bookingId)
          }}
          onError={setError}
        />
      )}

      {/* Edit Env Overrides Dialog — env-level date edit */}
      {booking && (
        <EditEnvOverridesDialog
          open={editingEnvOverrides}
          booking={booking}
          onClose={() => setEditingEnvOverrides(false)}
          onSaved={async (updatedBooking) => {
            setBooking(updatedBooking)
            if (bookingRequest != null) {
              const req = await bookingRequestService.get(bookingRequest.id)
              setBookingRequest(req)
            }
          }}
          saver={(payload) => bookingService.updateStandardFields(bookingId, payload)}
          onError={setError}
        />
      )}

      {/* Add Environment Dialog */}
      <Dialog open={addEnvOpen} onClose={() => { setAddEnvOpen(false); resetAddEnvForm() }} maxWidth="xs" fullWidth>
        <DialogTitle>Add Environment</DialogTitle>
        <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <FormControl fullWidth size="small">
            <InputLabel>Environment</InputLabel>
            <Select
              label="Environment"
              value={addEnvId}
              onChange={(e) => setAddEnvId(e.target.value as number)}
            >
              {availableEnvs.map((env) => (
                <MenuItem key={env.id} value={env.id}>{env.name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Start Date (optional)" type="date" size="small"
            InputLabelProps={{ shrink: true }}
            value={addEnvStart}
            onChange={(e) => setAddEnvStart(e.target.value)}
          />
          <TextField
            label="End Date (optional)" type="date" size="small"
            InputLabelProps={{ shrink: true }}
            value={addEnvEnd}
            onChange={(e) => setAddEnvEnd(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setAddEnvOpen(false); resetAddEnvForm() }}>Cancel</Button>
          <Button
            variant="contained"
            disabled={addEnvId === '' || addEnvSaving}
            onClick={handleAddEnvConfirm}
          >
            {addEnvSaving ? 'Adding…' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
