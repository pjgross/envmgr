import { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Checkbox,
  FormControlLabel,
  FormControl,
  FormHelperText,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import type { BookingResponse } from '../../types/booking';
import { formatApiError } from '../../services/apiError';
import { useAllProjects } from '../../hooks/useAllProjects';

type BookingType = { id: number; name: string };

export type EditStandardFieldsDialogProps = {
  open: boolean;
  booking: BookingResponse;
  bookingTypes: BookingType[];
  onClose: () => void;
  onSaved: (updated: BookingResponse) => void | Promise<void>;
  saver: (payload: Record<string, unknown>) => Promise<BookingResponse>;
  onError?: (msg: string) => void;
};

export default function EditStandardFieldsDialog({
  open,
  booking,
  bookingTypes,
  onClose,
  onSaved,
  saver,
  onError,
}: EditStandardFieldsDialogProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => ({
    project_name: booking.project_name,
    project_id: booking.project_id,
    start_date: booking.start_date.slice(0, 10),
    end_date: booking.end_date.slice(0, 10),
    booking_type: booking.booking_type_id,
    notes: booking.notes ?? '',
    exclusive_use: booking.exclusive_use,
    context_tag: booking.context_tag,
  }));
  const [saving, setSaving] = useState(false);

  // is_active: true, useSharedList-backed — never state.project.projects,
  // which is a page-scoped paged slice a second consumer can clobber.
  const { projects, truncated: projectsTruncated } = useAllProjects();

  const sfPerms = booking.standard_field_permissions ?? {};
  // `project_id` is editable unless the backend says otherwise.
  //
  // It is deliberately absent from ENTITY_FIELD_SPECS["booking"]["valid"],
  // because PATCH /booking-requests/{id}/standard-fields gates on
  // STANDARD_REQUEST_FIELDS and never consults lifecycle field permissions —
  // see the `TODO permission gating` in booking_request_service. So sfPerms
  // carries no entry for it, and gating on `sfPerms[...].editable` the normal
  // way would render the field permanently disabled.
  //
  // Written as a FALLBACK, not an override: the moment the backend does start
  // emitting a real project_id permission, that permission wins and this
  // special case disarms itself. An unconditional `field === 'project_id' ||`
  // would silently outrank it, and no test here would catch that — the
  // fixtures cannot contain a permission the backend does not yet send.
  const canEdit = (field: string) =>
    field === 'project_id' && !(field in sfPerms)
      ? true
      : sfPerms[field]?.editable === true;

  const handleSave = async () => {
    setSaving(true);
    try {
      const fieldMap: Record<string, string> = {
        project_name: 'project_name',
        project_id: 'project_id',
        start_date: 'start_date',
        end_date: 'end_date',
        booking_type: 'booking_type_id',
        notes: 'notes',
        exclusive_use: 'exclusive_use_requested',
        context_tag: 'context_tag',
      };
      const payload: Record<string, unknown> = {};
      for (const [key, apiKey] of Object.entries(fieldMap)) {
        if (!canEdit(key)) continue;
        const v = values[key];
        if ((key === 'start_date' || key === 'end_date') && typeof v === 'string' && v) {
          payload[apiKey] = new Date(v).toISOString();
        } else {
          payload[apiKey] = v;
        }
      }
      const updated = await saver(payload);
      await onSaved(updated);
      onClose();
    } catch (err: unknown) {
      onError?.(formatApiError(err, 'Save failed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Standard Fields</DialogTitle>
      <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <TextField
          label="Purpose"
          fullWidth
          size="small"
          value={values.project_name as string}
          disabled={!canEdit('project_name')}
          onChange={(e) => setValues((v) => ({ ...v, project_name: e.target.value }))}
        />
        <FormControl fullWidth size="small" disabled={!canEdit('project_id')}>
          <InputLabel id="edit-standard-fields-project-label">Project</InputLabel>
          <Select
            labelId="edit-standard-fields-project-label"
            label="Project"
            value={(values.project_id as number | null) ?? ''}
            onChange={(e) =>
              setValues((v) => ({
                ...v,
                project_id: e.target.value === '' ? null : Number(e.target.value),
              }))
            }
          >
            <MenuItem value="">None</MenuItem>
            {/* An archived project stays selectable only when it is still the
                value on this booking, so opening this dialog after its
                project was archived doesn't silently clear a link the
                backend deliberately preserves (A1's carve-out on
                update_standard_fields) — same shape as ReleaseForm's Owning
                project select. */}
            {booking.project_id != null &&
              values.project_id === booking.project_id &&
              !projects.some((p) => p.id === booking.project_id) && (
                <MenuItem value={booking.project_id}>
                  {booking.project_name_link ?? `#${booking.project_id}`} (archived)
                </MenuItem>
              )}
            {projects.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.name}
              </MenuItem>
            ))}
          </Select>
          {projectsTruncated && (
            <FormHelperText>Only the first {projects.length} projects are shown.</FormHelperText>
          )}
        </FormControl>
        <TextField
          label="Start Date"
          type="date"
          fullWidth
          size="small"
          InputLabelProps={{ shrink: true }}
          value={values.start_date as string}
          disabled={!canEdit('start_date')}
          onChange={(e) => setValues((v) => ({ ...v, start_date: e.target.value }))}
        />
        <TextField
          label="End Date"
          type="date"
          fullWidth
          size="small"
          InputLabelProps={{ shrink: true }}
          value={values.end_date as string}
          disabled={!canEdit('end_date')}
          onChange={(e) => setValues((v) => ({ ...v, end_date: e.target.value }))}
        />
        <FormControl fullWidth size="small" disabled={!canEdit('booking_type')}>
          <InputLabel>Booking Type</InputLabel>
          <Select
            label="Booking Type"
            value={(values.booking_type as number) ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, booking_type: e.target.value }))}
          >
            {bookingTypes.map((bt) => (
              <MenuItem key={bt.id} value={bt.id}>
                {bt.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          label="Notes"
          multiline
          minRows={3}
          fullWidth
          size="small"
          value={values.notes as string}
          disabled={!canEdit('notes')}
          onChange={(e) => setValues((v) => ({ ...v, notes: e.target.value }))}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={Boolean(values.exclusive_use)}
              disabled={!canEdit('exclusive_use')}
              onChange={(e) => setValues((v) => ({ ...v, exclusive_use: e.target.checked }))}
            />
          }
          label="Exclusive Use"
        />
        <FormControl fullWidth size="small" disabled={!canEdit('context_tag')}>
          <InputLabel>Context Tag</InputLabel>
          <Select
            label="Context Tag"
            value={(values.context_tag as string) ?? 'none'}
            onChange={(e) => setValues((v) => ({ ...v, context_tag: e.target.value }))}
          >
            <MenuItem value="none">None</MenuItem>
            <MenuItem value="deployment">Deployment</MenuItem>
            <MenuItem value="regression">Regression</MenuItem>
          </Select>
        </FormControl>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
