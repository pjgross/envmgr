import { useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button } from '@mui/material';
import type { BookingResponse } from '../../types/booking';
import type { CustomFieldDefinition } from '../../types/customField';
import CustomFieldsSection from '../CustomFieldsSection';
import { formatApiError } from '../../services/apiError';

export type EditCustomFieldsDialogProps = {
  open: boolean;
  booking: BookingResponse;
  definitions: CustomFieldDefinition[];
  onClose: () => void;
  onSaved: (updated: BookingResponse) => void | Promise<void>;
  saver: (values: Record<string, unknown>) => Promise<BookingResponse>;
  onError?: (msg: string) => void;
};

export default function EditCustomFieldsDialog({
  open,
  booking,
  definitions,
  onClose,
  onSaved,
  saver,
  onError,
}: EditCustomFieldsDialogProps) {
  const perms = booking.custom_field_permissions ?? {};
  const editableDefs = definitions.filter((d) => perms[d.field_key]?.editable);
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(
      editableDefs.map((d) => [d.field_key, booking.custom_fields?.[d.field_key] ?? ''])
    )
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await saver(values);
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
      <DialogTitle>Edit Custom Fields</DialogTitle>
      <DialogContent sx={{ pt: 2 }}>
        <CustomFieldsSection definitions={editableDefs} values={values} onChange={setValues} />
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
