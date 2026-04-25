import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeployments } from '../../store/deploymentSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { DeploymentFilters, DeploymentStatus } from '../../types/deployment';

const STATUS_OPTIONS: DeploymentStatus[] = [
  'pending', 'in_progress', 'success', 'failed', 'rolled_back',
];

export default function DeploymentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.deployment);

  const [environment, setEnvironment] = useState('');
  const [release, setRelease] = useState('');
  const [status, setStatus] = useState<string>('');

  const filters = useMemo<DeploymentFilters>(() => {
    const f: DeploymentFilters = {};
    if (status) f.status = status as DeploymentStatus;
    return f;
  }, [status]);

  useEffect(() => {
    dispatch(fetchDeployments(filters));
  }, [dispatch, filters]);

  const filteredItems = useMemo(() => {
    return items.filter((d) => {
      if (environment.trim()) {
        const needle = environment.trim().toLowerCase();
        if (!(d.environment_name ?? '').toLowerCase().includes(needle)) return false;
      }
      if (release.trim()) {
        const needle = release.trim().toLowerCase();
        if (!(d.release_name ?? '').toLowerCase().includes(needle)) return false;
      }
      return true;
    });
  }, [items, environment, release]);

  const rows = filteredItems.map((d) => ({
    id: d.id,
    environment_name: d.environment_name ?? '—',
    build_sha_short: d.build_sha_short ?? '—',
    status: d.status,
    deployer_name: d.deployer_name ?? '—',
    deployed_at: new Date(d.deployed_at).toLocaleString(),
    release_name: d.release_name ?? '—',
    change_request_title: d.change_request_title ?? '—',
  }));

  const cols: GridColDef[] = [
    { field: 'environment_name', headerName: 'Environment', width: 180 },
    { field: 'build_sha_short', headerName: 'Build', width: 110 },
    {
      field: 'status', headerName: 'Status', width: 140,
      renderCell: (p) => <DeploymentStatusChip status={p.value as DeploymentStatus} />,
    },
    { field: 'deployer_name', headerName: 'Deployer', flex: 1 },
    { field: 'deployed_at', headerName: 'Deployed at', width: 200 },
    { field: 'release_name', headerName: 'Release', width: 160 },
    { field: 'change_request_title', headerName: 'Change request', width: 200 },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Deployments</Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            size="small" label="Environment"
            value={environment} onChange={(e) => setEnvironment(e.target.value)}
            sx={{ width: 200 }}
          />
          <TextField
            size="small" label="Release"
            value={release} onChange={(e) => setRelease(e.target.value)}
            sx={{ width: 200 }}
          />
          <TextField
            select size="small" label="Status"
            value={status} onChange={(e) => setStatus(e.target.value)}
            sx={{ width: 160 }}
          >
            <MenuItem value="">Any</MenuItem>
            {STATUS_OPTIONS.map((s) => (
              <MenuItem key={s} value={s}>{s}</MenuItem>
            ))}
          </TextField>
        </Stack>
      </Paper>

      <Paper variant="outlined">
        <DataGrid
          rows={rows}
          columns={cols}
          autoHeight
          loading={loading}
          onRowClick={(p: GridRowParams) => navigate(`/deployments/${p.id}`)}
          disableRowSelectionOnClick
        />
      </Paper>
    </Box>
  );
}
