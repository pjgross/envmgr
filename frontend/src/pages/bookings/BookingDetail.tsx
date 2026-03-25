import { useEffect, useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Paper,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { AppDispatch, RootState } from '../../store'
import { fetchBookingTypes } from '../../store/bookingLifecycleSlice'
import { bookingService } from '../../services/bookingService'
import type { BookingResponse } from '../../types/booking'
import type { BookingStatusHistory, AllowedTransition } from '../../types/bookingLifecycle'

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

  // Auth
  const currentUserRole = useSelector((state: RootState) => state.auth.user?.role)

  // Redux lifecycle data
  const { bookingTypes, templates } = useSelector((state: RootState) => state.bookingLifecycle)

  // Local state
  const [booking, setBooking] = useState<BookingResponse | null>(null)
  const [allowedTransitions, setAllowedTransitions] = useState<AllowedTransition[]>([])
  const [history, setHistory] = useState<BookingStatusHistory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load on mount
  useEffect(() => {
    dispatch(fetchBookingTypes())

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

  // Field-level edit permissions
  const editableFields = useMemo(() => {
    if (!booking) return []
    const bt = bookingTypes.find((t) => t.id === booking.booking_type_id)
    const tmpl = templates.find((t) => t.id === bt?.lifecycle_template_id)
    if (!tmpl || !currentUserRole) return []
    const perm = tmpl.definition.field_permissions[booking.status]
    if (!perm || !perm.editable_by.includes(currentUserRole)) return []
    return perm.editable_fields
  }, [booking, bookingTypes, templates, currentUserRole])

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
        <Box sx={{ mb: 3, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
          {allowedTransitions.map((t) => (
            <Button
              key={t.to_state}
              variant="contained"
              color={
                t.to_state === 'rejected'
                  ? 'error'
                  : t.to_state === 'approved'
                  ? 'success'
                  : 'primary'
              }
              onClick={() => handleTransition(t.to_state, t.label)}
              size="small"
            >
              {t.label}
            </Button>
          ))}
        </Box>
      )}

      {/* Booking details */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
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
          <Box>
            {editableFields.includes('notes') ? (
              <textarea
                defaultValue={booking.notes ?? ''}
                rows={3}
                style={{
                  width: '100%',
                  fontFamily: 'inherit',
                  fontSize: '0.875rem',
                  padding: '4px 8px',
                  borderRadius: 4,
                  border: '1px solid #ccc',
                  resize: 'vertical',
                }}
              />
            ) : (
              <Typography variant="body2">{booking.notes ?? '—'}</Typography>
            )}
          </Box>
        </Box>
      </Paper>

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
    </Box>
  )
}
