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
import BlockIcon from '@mui/icons-material/Block';
import DriveFileMoveIcon from '@mui/icons-material/DriveFileMove';
import DataTable from '../../components/DataTable';
import { AppDispatch, RootState } from '../../store';
import { fetchReleases, fetchBacklogChanges } from '../../store/releaseSlice';
import type { ReleaseListItemResponse } from '../../types/release';
import type { ReleaseChangeResponse } from '../../types/releaseChange';
import ReleaseForm from './ReleaseForm';
import MoveScopeItemDialog from '../../components/releases/MoveScopeItemDialog';
import { systemService } from '../../services/systemService';
import type { SystemResponse } from '../../types/system';
import { RELEASE_SYSTEM_ROLE_LABELS } from '../../utils/releaseSystemRoles';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  planning: 'info',
  in_progress: 'info',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  completed: 'success',
  cancelled: 'error',
};

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
  const { list, backlog, loading } = useSelector((s: RootState) => s.release);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [tab, setTab] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [kindFilter, setKindFilter] = useState<'all' | 'project' | 'enterprise'>('all');
  const [systemFilter, setSystemFilter] = useState<string>('all');
  const [systems, setSystems] = useState<SystemResponse[]>([]);
  const [formOpen, setFormOpen] = useState(false);

  const [moveDialogOpen, setMoveDialogOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState<ReleaseChangeResponse | null>(null);

  useEffect(() => {
    dispatch(fetchReleases({}));
  }, [dispatch]);

  useEffect(() => {
    systemService.listSystems().then(setSystems).catch(() => setSystems([]));
  }, []);

  useEffect(() => {
    if (tab === 1) {
      dispatch(fetchBacklogChanges());
    }
  }, [tab, dispatch]);

  const filteredRows = useMemo(
    () =>
      list.filter((r) => {
        if (statusFilter !== 'all' && r.status !== statusFilter) return false;
        if (typeFilter !== 'all' && r.release_type !== typeFilter) return false;
        if (kindFilter !== 'all' && r.release_kind !== kindFilter) return false;
        if (systemFilter !== 'all' && !r.systems.some((s) => s.id === Number(systemFilter))) return false;
        return true;
      }),
    [list, statusFilter, typeFilter, kindFilter, systemFilter]
  );

  const releaseColumns = useMemo<GridColDef<ReleaseListItemResponse>[]>(
    () => [
      { field: 'id', headerName: 'ID', width: 70 },
      {
        field: 'name',
        headerName: 'Name',
        flex: 1,
        minWidth: 200,
      },
      {
        field: 'release_type',
        headerName: 'Type',
        width: 120,
        renderCell: (params) => (
          <Chip label={params.row.release_type} size="small" variant="outlined" />
        ),
      },
      {
        field: 'release_kind',
        headerName: 'Kind',
        width: 110,
        renderCell: (params) => (
          <Chip
            label={params.row.release_kind}
            color={params.row.release_kind === 'enterprise' ? 'secondary' : 'default'}
            size="small"
            variant="outlined"
          />
        ),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 130,
        renderCell: (params) => (
          <Chip
            label={params.row.status}
            color={STATUS_COLORS[params.row.status] ?? 'default'}
            size="small"
          />
        ),
      },
      {
        field: 'target_date',
        headerName: 'Target Date',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'phase_count',
        headerName: 'Phases',
        width: 90,
        align: 'center',
        headerAlign: 'center',
      },
      {
        field: 'scope_count',
        headerName: 'Scope',
        width: 90,
        align: 'center',
        headerAlign: 'center',
      },
      {
        field: 'scope_change_count',
        headerName: 'Scope Changes',
        width: 150,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) => {
          const row = params.row;
          if (!row.scope_change_count) {
            return (
              <Typography variant="body2" color="text.secondary">
                —
              </Typography>
            );
          }
          return (
            <Tooltip
              title={`+${row.scope_additions_count} additions, -${row.scope_removals_count} removals`}
            >
              <Chip
                label={`scope: +${row.scope_additions_count}/-${row.scope_removals_count}`}
                size="small"
                color="warning"
              />
            </Tooltip>
          );
        },
      },
      {
        field: 'systems',
        headerName: 'Systems',
        width: 200,
        sortable: false,
        renderCell: (params) =>
          params.row.systems.length === 0 ? (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ) : (
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {params.row.systems.map((s) => (
                <Tooltip key={s.id} title={(RELEASE_SYSTEM_ROLE_LABELS as Record<string, string>)[s.role] ?? s.role}>
                  <Chip label={s.name} size="small" variant="outlined" />
                </Tooltip>
              ))}
            </Box>
          ),
      },
      {
        field: 'blocker_count',
        headerName: 'Blockers',
        width: 100,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.blocker_count > 0 ? (
            <Tooltip title={`${params.row.blocker_count} pending gate(s)`}>
              <Chip
                icon={<BlockIcon />}
                label={params.row.blocker_count}
                color="warning"
                size="small"
              />
            </Tooltip>
          ) : (
            <Typography variant="body2" color="text.secondary">
              —
            </Typography>
          ),
      },
      {
        field: 'overdue_criterion_count',
        headerName: 'Overdue',
        width: 110,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.overdue_criterion_count > 0 ? (
            <Chip
              size="small"
              color="error"
              label={`${params.row.overdue_criterion_count} overdue`}
            />
          ) : (
            <Typography variant="body2" color="text.secondary">
              —
            </Typography>
          ),
      },
      {
        field: 'created_at',
        headerName: 'Created',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
    ],
    []
  );

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
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
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
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
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
              value={kindFilter}
              exclusive
              size="small"
              onChange={(_, v) => v && setKindFilter(v)}
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
              value={systemFilter}
              onChange={(e) => setSystemFilter(e.target.value)}
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
              rows={filteredRows}
              columns={releaseColumns}
              loading={loading}
              emptyMessage="No releases yet"
              onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
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
