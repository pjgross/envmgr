import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Chip,
  MenuItem,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DriveFileMoveIcon from '@mui/icons-material/DriveFileMove';
import DataTable from '../../components/DataTable';
import { useServerGrid } from '../../hooks/useServerGrid';
import { AppDispatch, RootState } from '../../store';
import { fetchReleases, fetchBacklogChanges } from '../../store/releaseSlice';
import type { ReleaseListItemResponse } from '../../types/release';
import type { ReleaseChangeResponse } from '../../types/releaseChange';
import ReleaseForm from './ReleaseForm';
import MoveScopeItemDialog from '../../components/releases/MoveScopeItemDialog';
import { systemService } from '../../services/systemService';
import type { SystemResponse } from '../../types/system';
import { releaseColumns } from './releaseColumns';

const KIND_COLORS: Record<string, 'default' | 'info' | 'error' | 'warning'> = {
  story: 'info',
  defect: 'error',
  task: 'default',
  spike: 'warning',
};

const RELEASE_TYPES = ['project', 'hotfix', 'patch', 'major', 'minor'];

export default function ReleaseList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { list, total, backlog, loading, listLoading } = useSelector((s: RootState) => s.release);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [tab, setTab] = useState(0);
  const [systems, setSystems] = useState<SystemResponse[]>([]);
  const [formOpen, setFormOpen] = useState(false);

  const [moveDialogOpen, setMoveDialogOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState<ReleaseChangeResponse | null>(null);

  const grid = useServerGrid({
    endpoint: 'releases',
    filterKeys: ['status', 'release_type', 'release_kind', 'system_id'],
    total,
    totalPending: listLoading,
    onFetch: (params) => dispatch(fetchReleases(params)),
  });

  useEffect(() => {
    systemService.listSystems().then(setSystems).catch(() => setSystems([]));
  }, []);

  useEffect(() => {
    if (tab === 1) {
      dispatch(fetchBacklogChanges());
    }
  }, [tab, dispatch]);

  const backlogColumns = useMemo<GridColDef<ReleaseChangeResponse>[]>(
    () => [
      { field: 'external_key', headerName: 'Key', width: 110 },
      { field: 'title', headerName: 'Title', flex: 1, minWidth: 200 },
      {
        field: 'change_kind',
        headerName: 'Kind',
        width: 100,
        renderCell: (params) => (
          <Chip
            label={params.row.change_kind}
            color={KIND_COLORS[params.row.change_kind] ?? 'default'}
            size="small"
          />
        ),
      },
      {
        field: 'external_status',
        headerName: 'Status',
        width: 130,
        renderCell: (params) => (
          <Typography variant="body2">{params.row.external_status ?? '—'}</Typography>
        ),
      },
      {
        field: '_actions',
        headerName: '',
        width: 80,
        sortable: false,
        renderCell: (params) => (
          <Tooltip
            title={
              params.row.source === 'jira'
                ? 'Cannot move jira-sourced scope items'
                : 'Move to a release'
            }
          >
            <span>
              <Button
                size="small"
                startIcon={<DriveFileMoveIcon fontSize="small" />}
                disabled={params.row.source === 'jira'}
                onClick={(e) => {
                  e.stopPropagation();
                  setMoveTarget(params.row);
                  setMoveDialogOpen(true);
                }}
              >
                Move
              </Button>
            </span>
          </Tooltip>
        ),
      },
    ],
    []
  );

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Releases
        </Typography>
        <Button variant="contained" onClick={() => setFormOpen(true)}>
          New Release
        </Button>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Releases" />
        <Tab label="Backlog" />
      </Tabs>

      {tab === 0 && (
        <>
          <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
            <TextField
              select
              label="Status"
              size="small"
              value={grid.filters.status ?? 'all'}
              onChange={(e) => grid.setFilter('status', e.target.value)}
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="all">All</MenuItem>
              <MenuItem value="draft">Draft</MenuItem>
              <MenuItem value="planning">Planning</MenuItem>
              <MenuItem value="in_progress">In Progress</MenuItem>
              <MenuItem value="completed">Completed</MenuItem>
              <MenuItem value="cancelled">Cancelled</MenuItem>
            </TextField>
            <TextField
              select
              label="Type"
              size="small"
              value={grid.filters.release_type ?? 'all'}
              onChange={(e) => grid.setFilter('release_type', e.target.value)}
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="all">All</MenuItem>
              {RELEASE_TYPES.map((t) => (
                <MenuItem key={t} value={t}>
                  {t}
                </MenuItem>
              ))}
            </TextField>
            <ToggleButtonGroup
              value={grid.filters.release_kind ?? 'all'}
              exclusive
              size="small"
              onChange={(_, v) => v && grid.setFilter('release_kind', v)}
              aria-label="Release kind filter"
            >
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="project">Projects</ToggleButton>
              <ToggleButton value="enterprise">Enterprise</ToggleButton>
            </ToggleButtonGroup>
            <TextField
              select
              label="System"
              size="small"
              value={grid.filters.system_id ?? 'all'}
              onChange={(e) => grid.setFilter('system_id', e.target.value)}
              sx={{ minWidth: 180 }}
              disabled={systems.length === 0}
            >
              <MenuItem value="all">All systems</MenuItem>
              {systems.map((s) => (
                <MenuItem key={s.id} value={String(s.id)}>{s.name}</MenuItem>
              ))}
            </TextField>
          </Box>

          <Box sx={{ height: 600, width: '100%' }}>
            <DataTable<ReleaseListItemResponse>
              storageKey="releases-list"
              userId={currentUserId}
              rows={list}
              columns={releaseColumns}
              loading={listLoading}
              emptyMessage="No releases yet"
              onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
              paginationMode="server"
              sortingMode="server"
              rowCount={total}
              paginationModel={grid.paginationModel}
              onPaginationModelChange={grid.onPaginationModelChange}
              sortModel={grid.sortModel}
              onSortModelChange={grid.onSortModelChange}
            />
          </Box>
        </>
      )}

      {tab === 1 && (
        <Box sx={{ height: 600, width: '100%' }}>
          <DataTable<ReleaseChangeResponse>
            storageKey="backlog-list"
            rows={backlog}
            columns={backlogColumns}
            loading={loading}
            emptyMessage="No backlog items"
          />
        </Box>
      )}

      <ReleaseForm open={formOpen} onClose={() => setFormOpen(false)} />

      {moveTarget && (
        <MoveScopeItemDialog
          open={moveDialogOpen}
          onClose={() => setMoveDialogOpen(false)}
          changeId={moveTarget.id}
          currentReleaseId={null}
          itemTitle={moveTarget.title}
          onMoved={() => dispatch(fetchBacklogChanges())}
        />
      )}
    </Box>
  );
}
