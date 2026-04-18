import { useEffect, useRef, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, FormControlLabel, Paper, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import { bookingService } from '../../services/bookingService'
import type { ConflictItem, ReceivedFeedbackItem } from '../../types/conflict'
import { formatApiError } from '../../services/apiError'
import ReceivedFeedbackList from './ReceivedFeedbackList'

type Props = {
  bookingId: number
  canAcknowledge: boolean
}

export default function ConflictsPanel({ bookingId, canAcknowledge }: Props) {
  const [tab, setTab] = useState(0)
  const [items, setItems] = useState<ConflictItem[]>([])
  const [received, setReceived] = useState<ReceivedFeedbackItem[]>([])
  const [pending, setPending] = useState<Record<number, { willing_to_share: boolean; notes: string }>>({})
  const [conflictsError, setConflictsError] = useState<string | null>(null)
  const [receivedError, setReceivedError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [savingIds, setSavingIds] = useState<Set<number>>(new Set())
  const hasRendered = useRef(false)
  const reloadGen = useRef(0)

  const reload = async () => {
    const myGen = ++reloadGen.current
    const [conflictsRes, receivedRes] = await Promise.allSettled([
      bookingService.getConflicts(bookingId),
      bookingService.getReceivedFeedback(bookingId),
    ])
    if (myGen !== reloadGen.current) return   // superseded — drop results
    if (conflictsRes.status === 'fulfilled') {
      setItems(conflictsRes.value)
      setConflictsError(null)
    } else {
      setConflictsError(formatApiError(conflictsRes.reason, 'Failed to load conflicts'))
    }
    if (receivedRes.status === 'fulfilled') {
      setReceived(receivedRes.value)
      setReceivedError(null)
    } else {
      setReceivedError(formatApiError(receivedRes.reason, 'Failed to load received feedback'))
    }
    setLoading(false)
  }

  useEffect(() => {
    hasRendered.current = false
    reload()
  }, [bookingId])

  const shouldRenderNow =
    items.length > 0 ||
    received.length > 0 ||
    conflictsError != null ||
    receivedError != null

  if (shouldRenderNow) {
    hasRendered.current = true
  }

  if (!loading && !shouldRenderNow && !hasRendered.current) return null

  const saveAck = async (otherId: number) => {
    const p = pending[otherId] ?? { willing_to_share: false, notes: '' }
    setSavingIds((s) => new Set(s).add(otherId))
    try {
      await bookingService.acknowledgeConflict(bookingId, otherId, p)
      await reload()
    } finally {
      setSavingIds((s) => {
        const next = new Set(s)
        next.delete(otherId)
        return next
      })
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} aria-label="Conflict feedback" sx={{ mb: 2 }}>
        <Tab label={`Your feedback (${items.length})`} />
        <Tab label={`Feedback received (${received.length})`} />
      </Tabs>

      {tab === 0 && (
        <Box>
          {conflictsError && (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setConflictsError(null)}>
              {conflictsError}
            </Alert>
          )}
          {items.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              No conflicts for this booking.
            </Typography>
          ) : (
            items.map((it) => {
              const p = pending[it.other_booking.id] ?? {
                willing_to_share: it.ack?.willing_to_share ?? false,
                notes: it.ack?.notes ?? '',
              }
              return (
                <Box key={it.other_booking.id} sx={{ mb: 2, pb: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="body2">
                    Booking #{it.other_booking.id} ({new Date(it.other_booking.start_date).toLocaleDateString()} – {new Date(it.other_booking.end_date).toLocaleDateString()}) — status {it.other_booking.status}
                  </Typography>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={p.willing_to_share}
                        disabled={!canAcknowledge}
                        onChange={(e) => setPending((s) => ({ ...s, [it.other_booking.id]: { ...p, willing_to_share: e.target.checked } }))}
                      />
                    }
                    label="Willing to share"
                  />
                  <TextField
                    label="Notes" fullWidth size="small" multiline minRows={2}
                    value={p.notes}
                    disabled={!canAcknowledge}
                    onChange={(e) => setPending((s) => ({ ...s, [it.other_booking.id]: { ...p, notes: e.target.value } }))}
                  />
                  {canAcknowledge && (
                    <Button sx={{ mt: 1 }} size="small" variant="contained" onClick={() => saveAck(it.other_booking.id)} disabled={savingIds.has(it.other_booking.id)}>
                      Save
                    </Button>
                  )}
                  {it.ack?.acknowledged_at && (
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      Last updated {new Date(it.ack.acknowledged_at).toLocaleString()}
                    </Typography>
                  )}
                </Box>
              )
            })
          )}
        </Box>
      )}

      {tab === 1 && (
        <Box>
          {receivedError && (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setReceivedError(null)}>
              {receivedError}
            </Alert>
          )}
          <ReceivedFeedbackList items={received} />
        </Box>
      )}
    </Paper>
  )
}
