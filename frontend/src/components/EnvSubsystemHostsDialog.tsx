import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { AppDispatch, RootState } from '../store';
import { fetchInfrastructureComponents } from '../store/infrastructureComponentSlice';
import { infrastructureComponentService } from '../services/infrastructureComponentService';
import type {
  EnvironmentSubSystemHostResponse,
  HostAttachment,
  InfrastructureComponentResponse,
} from '../types/infrastructureComponent';

interface Props {
  open: boolean;
  onClose: () => void;
  envId: number;
  subsystemId: number;
  subsystemLabel: string;
  onSaved?: () => void;
}

type Row = {
  host: InfrastructureComponentResponse;
  role: string;
};

export default function EnvSubsystemHostsDialog({
  open,
  onClose,
  envId,
  subsystemId,
  subsystemLabel,
  onSaved,
}: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const allHosts = useSelector((s: RootState) => s.infrastructureComponent.components);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [rows, setRows] = useState<Row[]>([]);
  const [pickValue, setPickValue] = useState<InfrastructureComponentResponse | null>(null);
  const [pickRole, setPickRole] = useState('');

  useEffect(() => {
    if (!open) return;
    dispatch(fetchInfrastructureComponents());
    let cancelled = false;
    setLoading(true);
    setError('');
    (async () => {
      try {
        const resp = await infrastructureComponentService.listEnvSubsystemHosts(
          envId,
          subsystemId
        );
        if (cancelled) return;
        // The summary shape from the API is a subset of InfrastructureComponentResponse;
        // we fill the rest with safe defaults since rows only need display fields + id.
        const initial: Row[] = resp.hosts.map((h: EnvironmentSubSystemHostResponse) => ({
          host: {
            id: h.infrastructure_component_id,
            name: h.infrastructure_component.name,
            component_type: h.infrastructure_component.component_type,
            provider: h.infrastructure_component.provider,
            region: h.infrastructure_component.region,
          } as InfrastructureComponentResponse,
          role: h.role ?? '',
        }));
        setRows(initial);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load hosts');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, envId, subsystemId, dispatch]);

  const attachedIds = useMemo(() => new Set(rows.map((r) => r.host.id)), [rows]);
  const availableHosts = useMemo(
    () => allHosts.filter((h) => !attachedIds.has(h.id)),
    [allHosts, attachedIds]
  );

  const addHost = () => {
    if (!pickValue) return;
    setRows((prev) => [...prev, { host: pickValue, role: pickRole }]);
    setPickValue(null);
    setPickRole('');
  };

  const removeHost = (id: number) => {
    setRows((prev) => prev.filter((r) => r.host.id !== id));
  };

  const updateRole = (id: number, role: string) => {
    setRows((prev) => prev.map((r) => (r.host.id === id ? { ...r, role } : r)));
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const attachments: HostAttachment[] = rows.map((r) => ({
        infrastructure_component_id: r.host.id,
        role: r.role || null,
      }));
      await infrastructureComponentService.setEnvSubsystemHosts(
        envId,
        subsystemId,
        attachments
      );
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save hosts');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Hosts for {subsystemLabel}</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
            <CircularProgress size={24} />
          </Box>
        ) : (
          <>
            <Typography variant="caption" color="text.secondary">
              A subsystem can live on multiple hosts (replicas, multi-AZ). Use `role` to
              tag the function of each host.
            </Typography>
            <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
              {rows.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No hosts attached yet.
                </Typography>
              ) : (
                rows.map((r) => (
                  <Box
                    key={r.host.id}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      border: 1,
                      borderColor: 'divider',
                      borderRadius: 1,
                      p: 1,
                    }}
                  >
                    <Box sx={{ flexGrow: 1 }}>
                      <Typography variant="body2" fontWeight="medium">
                        {r.host.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {r.host.component_type}
                        {r.host.region ? ` · ${r.host.region}` : ''}
                        {r.host.provider ? ` · ${r.host.provider}` : ''}
                      </Typography>
                    </Box>
                    <TextField
                      size="small"
                      label="Role"
                      placeholder="primary, replica…"
                      value={r.role}
                      onChange={(e) => updateRole(r.host.id, e.target.value)}
                      sx={{ width: 160 }}
                    />
                    <IconButton
                      size="small"
                      color="error"
                      aria-label="Remove host"
                      onClick={() => removeHost(r.host.id)}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Box>
                ))
              )}
            </Box>

            <Box sx={{ mt: 3, display: 'flex', gap: 1, alignItems: 'center' }}>
              <Autocomplete
                size="small"
                sx={{ flexGrow: 1 }}
                options={availableHosts}
                value={pickValue}
                onChange={(_, v) => setPickValue(v)}
                getOptionLabel={(h) => `${h.name} (${h.component_type})`}
                isOptionEqualToValue={(a, b) => a.id === b.id}
                renderInput={(params) => <TextField {...params} label="Add host" />}
              />
              <TextField
                size="small"
                label="Role"
                value={pickRole}
                onChange={(e) => setPickRole(e.target.value)}
                sx={{ width: 160 }}
              />
              <Button onClick={addHost} disabled={!pickValue}>
                Add
              </Button>
            </Box>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || loading}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
