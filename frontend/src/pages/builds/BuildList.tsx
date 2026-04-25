import { useEffect, useState, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Paper, Stack, TextField, Typography } from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import { fetchBuilds } from '../../store/buildSlice';
import type { BuildFilters, PipelineStep } from '../../types/build';

function latestStepSummary(steps: PipelineStep[]): string {
  if (steps.length === 0) return '—';
  const last = steps[steps.length - 1];
  return `${last.name} (${last.status})`;
}

export default function BuildList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.build);

  const [subsystem, setSubsystem] = useState('');
  const [branch, setBranch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const filters = useMemo<BuildFilters>(() => {
    const f: BuildFilters = {};
    if (branch) f.branch = branch;
    if (dateFrom) f.date_from = new Date(`${dateFrom}T00:00:00Z`).toISOString();
    if (dateTo) f.date_to = new Date(`${dateTo}T23:59:59Z`).toISOString();
    return f;
  }, [branch, dateFrom, dateTo]);

  useEffect(() => {
    dispatch(fetchBuilds(filters));
  }, [dispatch, filters]);

  const filteredItems = useMemo(() => {
    if (!subsystem.trim()) return items;
    const needle = subsystem.trim().toLowerCase();
    return items.filter((b) => (b.subsystem_name ?? '').toLowerCase().includes(needle));
  }, [items, subsystem]);

  const rows = filteredItems.map((b) => ({
    id: b.id,
    subsystem_name: b.subsystem_name ?? '—',
    git_sha_short: b.git_sha.slice(0, 8),
    git_branch: b.git_branch ?? '—',
    build_number: b.build_number ?? '—',
    release_name: b.release_name ?? '—',
    commit_timestamp: new Date(b.commit_timestamp).toLocaleString(),
    latest_step: latestStepSummary(b.pipeline_steps),
  }));

  const cols: GridColDef[] = [
    { field: 'subsystem_name', headerName: 'SubSystem', width: 180 },
    { field: 'git_branch', headerName: 'Branch', width: 160 },
    { field: 'git_sha_short', headerName: 'SHA', width: 100 },
    { field: 'build_number', headerName: 'Build #', width: 100 },
    { field: 'release_name', headerName: 'Release', width: 160 },
    { field: 'commit_timestamp', headerName: 'Commit at', width: 200 },
    { field: 'latest_step', headerName: 'Latest step', flex: 1 },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Builds</Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            size="small" label="SubSystem"
            value={subsystem} onChange={(e) => setSubsystem(e.target.value)}
            sx={{ width: 200 }}
          />
          <TextField
            size="small" label="Branch"
            value={branch} onChange={(e) => setBranch(e.target.value)}
            sx={{ width: 180 }}
          />
          <TextField
            size="small" label="From" type="date"
            value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            size="small" label="To" type="date"
            value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
        </Stack>
      </Paper>

      <Paper variant="outlined">
        <DataGrid
          rows={rows}
          columns={cols}
          autoHeight
          loading={loading}
          onRowClick={(p: GridRowParams) => navigate(`/builds/${p.id}`)}
          disableRowSelectionOnClick
        />
      </Paper>
    </Box>
  );
}
