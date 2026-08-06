import { Box, Chip, Tooltip, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import BlockIcon from '@mui/icons-material/Block';
import ComputedColumnHeader from '../../components/ComputedColumnHeader';
import type { ReleaseListItemResponse } from '../../types/release';
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

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "releases"): name, release_type, release_kind, status, target_date, created_at.
// `id` is not in the whitelist, so it stops being sortable — and the six computed
// columns (phase_count, scope_count, scope_change_count, blocker_count,
// overdue_criterion_count, systems) never were and never can be: none is backed by
// a single column the database could order by. `owning_project_name` joins the
// same way (a batched name lookup after the query), so it's permanently
// unsortable too, not merely unwhitelisted for now.
export const releaseColumns: GridColDef<ReleaseListItemResponse>[] = [
  { field: 'id', headerName: 'ID', width: 70, sortable: false },
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
    // Joined — resolved by a batched project_service.get_project_names
    // lookup after the query, never a column the database could order by.
    // Renders owning_project_name, never owning_project_id or project_name
    // (a different, external-tracker field on ReleaseChange — see ScopeTable).
    field: 'owning_project_name',
    headerName: 'Project',
    width: 160,
    sortable: false,
    renderCell: (params) =>
      params.row.owning_project_name ?? (
        <Typography variant="body2" color="text.secondary">—</Typography>
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
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Phases" />,
  },
  {
    field: 'scope_count',
    headerName: 'Scope',
    width: 90,
    align: 'center',
    headerAlign: 'center',
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Scope" />,
  },
  {
    field: 'scope_change_count',
    headerName: 'Scope Changes',
    width: 150,
    align: 'center',
    headerAlign: 'center',
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Scope Changes" />,
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
    renderHeader: () => <ComputedColumnHeader label="Systems" />,
    renderCell: (params) =>
      params.row.systems.length === 0 ? (
        <Typography variant="body2" color="text.secondary">—</Typography>
      ) : (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {params.row.systems.map((s) => (
            <Tooltip key={s.id} title={RELEASE_SYSTEM_ROLE_LABELS[s.role]}>
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
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Blockers" />,
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
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Overdue" />,
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
];
