import { useState } from 'react'
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField } from '@mui/material'
import type { BookingResponse } from '../../types/booking'

type Props = {
  open: boolean
  booking: BookingResponse
  onClose: () => void
  onSaved: (updated: BookingResponse) => void | Promise<void>
  saver: (payload: { start_date?: string; end_date?: string }) => Promise<BookingResponse>
  onError?: (msg: string) => void
}

export default function EditEnvOverridesDialog({ open, booking, onClose, onSaved, saver, onError }: Props) {
  const [start, setStart] = useState(booking.start_date.slice(0, 10))
  const [end, setEnd] = useState(booking.end_date.slice(0, 10))
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await saver({ start_date: start, end_date: end })
      await onSaved(updated)
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed'
      onError?.(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Edit Environment Dates</DialogTitle>
      <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <TextField label="Start" type="date" size="small" InputLabelProps={{ shrink: true }} value={start} onChange={(e) => setStart(e.target.value)} />
        <TextField label="End" type="date" size="small" InputLabelProps={{ shrink: true }} value={end} onChange={(e) => setEnd(e.target.value)} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      </DialogActions>
    </Dialog>
  )
}
