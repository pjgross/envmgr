/**
 * HandoverSection — the six handover fields that become a fulfilled
 * request's Welcome Pack (`WelcomePack.tsx` renders them back out).
 *
 * Editable by the operating team AS WELL AS Admins — deliberately different
 * from the Governance section above it on the same page, which is
 * Admin-only. A member of the operating team therefore sees Governance
 * read-only and Handover editable at the same time; that asymmetry is the
 * feature working; see the helper text rendered below the heading, which
 * exists so it reads as deliberate rather than broken.
 *
 * Group membership is not on the frontend's user object, so canEditHandover
 * cannot be computed locally the way it can for e.g. an Admin check. This
 * fetches the environment's operations group members itself
 * (userGroupService.listMembers) and derives membership from that. If the
 * fetch fails, the gate falls back to Admin-only, never to editable — a
 * network error must never widen who can write handover content that ends
 * up in front of a requester.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { updateEnvironmentHandover } from '../../store/environmentRequestSlice';
import { userGroupService } from '../../services/userGroupService';
import type { EnvironmentResponse } from '../../types/environment';
import type { EnvironmentHandoverUpdate } from '../../types/environmentRequest';

interface HandoverFormValues {
  access_url: string;
  connection_notes: string;
  support_contact: string;
  sla_notes: string;
  known_limitations: string;
  decommission_notes: string;
}

const FIELDS: { key: keyof HandoverFormValues; label: string; multiline?: boolean }[] = [
  { key: 'access_url', label: 'Access URL' },
  { key: 'connection_notes', label: 'How to connect', multiline: true },
  { key: 'support_contact', label: 'Support contact' },
  { key: 'sla_notes', label: 'SLA notes', multiline: true },
  { key: 'known_limitations', label: 'Known limitations', multiline: true },
  { key: 'decommission_notes', label: 'Offboarding / decommission notes', multiline: true },
];

function toFormValues(env: EnvironmentResponse): HandoverFormValues {
  return {
    access_url: env.access_url ?? '',
    connection_notes: env.connection_notes ?? '',
    support_contact: env.support_contact ?? '',
    sla_notes: env.sla_notes ?? '',
    known_limitations: env.known_limitations ?? '',
    decommission_notes: env.decommission_notes ?? '',
  };
}

interface HandoverSectionProps {
  environment: EnvironmentResponse;
}

export default function HandoverSection({ environment }: HandoverSectionProps) {
  const dispatch = useDispatch<AppDispatch>();
  const user = useSelector((state: RootState) => state.auth.user);

  const [editMode, setEditMode] = useState(false);
  const [form, setForm] = useState<HandoverFormValues>(() => toFormValues(environment));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [inOperatingTeam, setInOperatingTeam] = useState(false);

  useEffect(() => {
    setForm(toFormValues(environment));
  }, [environment]);

  const isAdmin = user?.role === 'Admin' || user?.is_master_admin === true;

  useEffect(() => {
    // An Admin's edit right doesn't depend on group membership at all —
    // skip the lookup entirely rather than issue a network call whose
    // result nothing reads.
    if (isAdmin) {
      setInOperatingTeam(false);
      return;
    }
    if (!environment.operations_group_id || !user) {
      setInOperatingTeam(false);
      return;
    }
    let cancelled = false;
    userGroupService
      .listMembers(environment.operations_group_id)
      .then((res) => {
        if (!cancelled) setInOperatingTeam(res.rows.some((m) => m.user_id === user.id));
      })
      .catch(() => {
        // Fall back to Admin-only (isAdmin is false here), never editable.
        if (!cancelled) setInOperatingTeam(false);
      });
    return () => {
      cancelled = true;
    };
  }, [environment.operations_group_id, isAdmin, user]);

  const canEditHandover = isAdmin || inOperatingTeam;

  const handleCancel = () => {
    setForm(toFormValues(environment));
    setError(null);
    setEditMode(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    const data: EnvironmentHandoverUpdate = {
      access_url: form.access_url || null,
      connection_notes: form.connection_notes || null,
      support_contact: form.support_contact || null,
      sla_notes: form.sla_notes || null,
      known_limitations: form.known_limitations || null,
      decommission_notes: form.decommission_notes || null,
    };
    const result = await dispatch(
      updateEnvironmentHandover({ environmentId: environment.id, data })
    );
    setSaving(false);
    if (updateEnvironmentHandover.rejected.match(result)) {
      // `result.payload`, never `result.error.message` — see the note above
      // WelcomePack and CLAUDE.md's record of this exact defect shipping in
      // four other panels.
      setError(result.payload ?? 'Failed to save the handover details');
      return;
    }
    setEditMode(false);
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="h6">Handover</Typography>
        {canEditHandover && !editMode && (
          <Button size="small" onClick={() => setEditMode(true)}>
            Edit
          </Button>
        )}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Editable by this environment&apos;s operating team as well as admins — this is what a
        requester reads in their Welcome Pack once a request against this environment is
        fulfilled.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {editMode ? (
        <Stack spacing={2}>
          {FIELDS.map((f) => (
            <TextField
              key={f.key}
              label={f.label}
              value={form[f.key]}
              onChange={(e) => setForm((prev) => ({ ...prev, [f.key]: e.target.value }))}
              multiline={f.multiline}
              minRows={f.multiline ? 2 : undefined}
              fullWidth
            />
          ))}
          <Stack direction="row" spacing={1}>
            <Button variant="contained" onClick={handleSave} disabled={saving}>
              Save
            </Button>
            <Button onClick={handleCancel} disabled={saving}>
              Cancel
            </Button>
          </Stack>
        </Stack>
      ) : (
        <Stack spacing={1.5}>
          {FIELDS.map((f) => (
            <Box key={f.key}>
              <Typography variant="overline" color="text.secondary">
                {f.label}
              </Typography>
              <Typography variant="body2">{form[f.key] || '—'}</Typography>
            </Box>
          ))}
        </Stack>
      )}
    </Paper>
  );
}
