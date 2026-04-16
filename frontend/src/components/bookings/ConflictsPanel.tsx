import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, FormControlLabel, Paper, TextField, Typography,
} from '@mui/material'
import { bookingService } from '../../services/bookingService'
import type { ConflictItem } from '../../types/conflict'

type Props = {
  bookingId: number
  canAcknowledge: boolean
}

export default function ConflictsPanel({ bookingId, canAcknowledge }: Props) {
  const [items, setItems] = useState<ConflictItem[]>([])
  const [pending, setPending] = useState<Record<number, { willing_to_share: boolean; notes: string }>>({})
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setItems(await bookingService.getConflicts(bookingId))
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load conflicts')
    }
  }

  useEffect(() => { load() }, [bookingId])

  if (items.length === 0) return null

  const saveAck = async (otherId: number) => {
    const p = pending[otherId] ?? { willing_to_share: false, notes: '' }
    await bookingService.acknowledgeConflict(bookingId, otherId, p)
    await load()
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Typography variant="subtitle2" gutterBottom>Conflicts ({items.length})</Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>{error}</Alert>}
      {items.map((it) => {
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
              <Button sx={{ mt: 1 }} size="small" variant="contained" onClick={() => saveAck(it.other_booking.id)}>
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
      })}
    </Paper>
  )
}
