/**
 * ReleaseSystemsTab — manage the systems a release impacts, by role.
 * Local-state CRUD (no Redux), mirroring the self-contained sub-resource tabs.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import { releaseService } from '../../services/releaseService';
import { useAllSystems } from '../../hooks/useAllSystems';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import type { ReleaseSystemResponse } from '../../types/release';
import {
  RELEASE_SYSTEM_ROLE_LABELS,
  RELEASE_SYSTEM_ROLE_COLORS,
  RELEASE_SYSTEM_ROLE_ORDER,
  type ReleaseSystemRole,
} from '../../utils/releaseSystemRoles';

interface Props {
  releaseId: number;
}

function extractError(err: unknown, fallback: string): string {
  const axiosErr = err as { response?: { data?: { detail?: unknown } } };
  const detail = axiosErr?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function ReleaseSystemsTab({ releaseId }: Props) {
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [rows, setRows] = useState<ReleaseSystemResponse[]>([]);
  // Not the shared systems slice: since the C3 conversion (a later task) it
  // will become SystemCatalog's current filtered page, so this add-system
  // dropdown would silently offer a subset.
  const { systems: allSystems, truncated: systemsTruncated } = useAllSystems();
  const [loading, setLoading] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [systemId, setSystemId] = useState<number | ''>('');
  const [role, setRole] = useState<ReleaseSystemRole>('changing');
  const [deploymentDate, setDeploymentDate] = useState('');

  const load = () => {
    setLoading(true);
    releaseService
      .listSystems(releaseId)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [releaseId]);

  // Systems not already linked, for the add dropdown.
  const availableSystems = useMemo(() => {
    const linked = new Set(rows.map((r) => r.system_id));
    return allSystems.filter((s) => !linked.has(s.id));
  }, [rows, allSystems]);

  // Group + order by role for the table.
  const orderedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const ra = RELEASE_SYSTEM_ROLE_ORDER.indexOf(a.role);
      const rb = RELEASE_SYSTEM_ROLE_ORDER.indexOf(b.role);
      if (ra !== rb) return ra - rb;
      return (a.system_name ?? '').localeCompare(b.system_name ?? '');
    });
  }, [rows]);

  const openAdd = () => {
    setSystemId('');
    setRole('changing');
    setDeploymentDate('');
    setAddOpen(true);
  };

  const handleAdd = async () => {
    if (systemId === '') return;
    try {
      await releaseService.addSystem(releaseId, {
        system_id: Number(systemId),
        role,
        deployment_date: deploymentDate ? new Date(`${deploymentDate}T00:00:00Z`).toISOString() : null,
      });
      snackbar.success('System added');
      setAddOpen(false);
      load();
    } catch (err) {
      snackbar.error(extractError(err, 'Failed to add system'));
    }
  };

  const handleRemove = async (row: ReleaseSystemResponse) => {
    if (!(await confirm({ message: `Remove ${row.system_name ?? 'system'} from this release?`, destructive: true }))) return;
    try {
      await releaseService.removeSystem(row.id);
      snackbar.success('System removed');
      load();
    } catch (err) {
      snackbar.error(extractError(err, 'Failed to remove system'));
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle1">Impacted Systems ({rows.length})</Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={openAdd} disabled={availableSystems.length === 0}>
          Add System
        </Button>
      </Box>

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>System</TableCell>
            <TableCell>Role</TableCell>
            <TableCell>Deployment date</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {orderedRows.length === 0 && !loading && (
            <TableRow>
              <TableCell colSpan={4}>
                <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                  No systems linked yet.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {orderedRows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>{row.system_name ?? `#${row.system_id}`}</TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={RELEASE_SYSTEM_ROLE_LABELS[row.role]}
                  color={RELEASE_SYSTEM_ROLE_COLORS[row.role]}
                />
              </TableCell>
              <TableCell>
                {row.deployment_date ? new Date(row.deployment_date).toLocaleDateString() : '—'}
              </TableCell>
              <TableCell align="right">
                <IconButton size="small" color="error" onClick={() => handleRemove(row)} aria-label="remove system">
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Add impacted system</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select label="System" fullWidth value={systemId}
              onChange={(e) => setSystemId(e.target.value === '' ? '' : Number(e.target.value))}
              helperText={
                systemsTruncated ? `Only the first ${allSystems.length} systems are shown.` : undefined
              }
            >
              {availableSystems.map((s) => (
                <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
              ))}
            </TextField>
            <TextField
              select label="Role" fullWidth value={role}
              onChange={(e) => setRole(e.target.value as ReleaseSystemRole)}
            >
              {RELEASE_SYSTEM_ROLE_ORDER.map((r) => (
                <MenuItem key={r} value={r}>{RELEASE_SYSTEM_ROLE_LABELS[r]}</MenuItem>
              ))}
            </TextField>
            <TextField
              label="Deployment date (optional)" type="date" fullWidth
              value={deploymentDate} onChange={(e) => setDeploymentDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleAdd} disabled={systemId === ''}>Add</Button>
        </DialogActions>
      </Dialog>

      {confirmDialog}
    </Box>
  );
}
