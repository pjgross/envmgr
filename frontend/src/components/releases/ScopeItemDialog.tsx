/**
 * ScopeItemDialog — create or edit a scope item (release change).
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import type { AppDispatch, RootState } from '../../store';
import {
  createReleaseChange,
  updateReleaseChange,
} from '../../store/releaseSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { fetchScopeChangeKinds } from '../../store/scopeChangeRulesSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import CustomFieldsSection from '../CustomFieldsSection';
import type { ReleaseChangeResponse } from '../../types/releaseChange';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  item?: ReleaseChangeResponse | null;
}

export default function ScopeItemDialog({ open, onClose, releaseId, item }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const isEdit = !!item;

  const [title, setTitle] = useState('');
  const [changeKind, setChangeKind] = useState('');
  const [externalKey, setExternalKey] = useState('');
  const [description, setDescription] = useState('');
  const [externalStatus, setExternalStatus] = useState('');
  const [customFields, setCustomFields] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);

  const allDefs = useSelector(
    (s: RootState) => s.customField.definitions['release_change'] ?? []
  );
  const changeKinds = useSelector((s: RootState) => s.scopeChangeRules.kinds);
  const visibleDefs = useMemo(
    () => allDefs.filter((d) => d.entity_subtype == null || d.entity_subtype === changeKind),
    [allDefs, changeKind],
  );

  useEffect(() => {
    if (open) {
      dispatch(fetchDefinitions('release_change'));
      dispatch(fetchScopeChangeKinds());
    }
  }, [open, dispatch]);

  useEffect(() => {
    if (open) {
      setTitle(item?.title ?? '');
      setChangeKind(item?.change_kind ?? '');
      setExternalKey(item?.external_key ?? '');
      setDescription(item?.description ?? '');
      setExternalStatus(item?.external_status ?? '');
      setCustomFields((item?.custom_fields as Record<string, unknown>) ?? {});
    }
  }, [open, item]);

  // On create, pick the first kind once the list loads.
  useEffect(() => {
    if (open && !isEdit && !changeKind && changeKinds.length) {
      setChangeKind(changeKinds[0]);
    }
  }, [open, isEdit, changeKind, changeKinds]);

  const requiredMissing = visibleDefs.some((d) => {
    if (!d.required) return false;
    const v = customFields[d.field_key];
    return v == null || (typeof v === 'string' && v.trim() === '');
  });

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSave = async () => {
    if (!title.trim() || requiredMissing) return;
    if (!isEdit && !changeKind) return;
    setSubmitting(true);
    try {
      if (isEdit && item) {
        await dispatch(
          updateReleaseChange({
            changeId: item.id,
            data: {
              title: title.trim(),
              description: description || null,
              external_key: externalKey || null,
              external_status: externalStatus || null,
              custom_fields: customFields,
            },
          })
        ).unwrap();
        snackbar.success('Scope item updated');
      } else {
        await dispatch(
          createReleaseChange({
            releaseId,
            data: {
              title: title.trim(),
              change_kind: changeKind,
              description: description || null,
              external_key: externalKey || null,
              external_status: externalStatus || null,
              custom_fields: customFields,
            },
          })
        ).unwrap();
        snackbar.success('Scope item added');
      }
      handleClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save scope item');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Scope Item' : 'Add Scope Item'}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            label="Title"
            required
            fullWidth
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={submitting}
          />
          <TextField
            select
            label="Kind"
            fullWidth
            value={changeKind}
            onChange={(e) => setChangeKind(e.target.value)}
            disabled={submitting || isEdit || changeKinds.length === 0}
            helperText={
              changeKinds.length === 0
                ? 'No change kinds configured. Ask an admin to add some.'
                : undefined
            }
          >
            {changeKinds.map((k) => (
              <MenuItem key={k} value={k}>
                {k}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="External Key (e.g. Jira issue)"
            fullWidth
            value={externalKey}
            onChange={(e) => setExternalKey(e.target.value)}
            disabled={submitting}
          />
          <TextField
            label="External Status"
            fullWidth
            value={externalStatus}
            onChange={(e) => setExternalStatus(e.target.value)}
            disabled={submitting}
          />
          <TextField
            label="Description"
            multiline
            rows={2}
            fullWidth
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={submitting}
          />

          <CustomFieldsSection
            definitions={visibleDefs}
            values={customFields}
            onChange={setCustomFields}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={
            !title.trim() ||
            requiredMissing ||
            submitting ||
            (!isEdit && !changeKind)
          }
          onClick={handleSave}
        >
          {isEdit ? 'Save' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
