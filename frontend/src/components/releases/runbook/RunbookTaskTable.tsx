/**
 * The runbook's task table. Renders ONLY what the composite read says —
 * action buttons come from `allowed_transitions`, never a local rule.
 * `disableVirtualization`: runbooks are tens of rows, and without it jsdom
 * renders a fraction of the columns (see CLAUDE.md, A3).
 */
import { Box, Button, Chip, Stack, Tooltip } from '@mui/material';
import WhatshotIcon from '@mui/icons-material/Whatshot';
import ScheduleIcon from '@mui/icons-material/Schedule';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import BlockIcon from '@mui/icons-material/Block';
import type { GridColDef, GridValueGetterParams } from '@mui/x-data-grid';
import { useSelector } from 'react-redux';
import DataTable from '../../DataTable';
import type { RootState } from '../../../store';
import type { RunbookRead, RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';
import { FLAG_TEXT, KIND_LABEL, STATUS_COLOR, STATUS_LABEL, actionLabel } from './labels';

interface Props {
  read: RunbookRead;
  canEdit: boolean;
  onAction: (task: RunbookTaskRead, to: TaskStatus) => void;
  onRecordTime: (task: RunbookTaskRead) => void;
  onEdit: (task: RunbookTaskRead) => void;
}

const FLAGS: { key: keyof typeof FLAG_TEXT; Icon: typeof WhatshotIcon; color: 'error' | 'warning' | 'info' }[] = [
  { key: 'blocked', Icon: BlockIcon, color: 'error' },
  { key: 'critical', Icon: WhatshotIcon, color: 'error' },
  { key: 'late_start', Icon: ScheduleIcon, color: 'warning' },
  { key: 'overrunning', Icon: HourglassBottomIcon, color: 'warning' },
  { key: 'slipped_past_fixed_start', Icon: SkipNextIcon, color: 'info' },
];

export default function RunbookTaskTable({ read, canEdit, onAction, onRecordTime, onEdit }: Props) {
  const user = useSelector((s: RootState) => s.auth.user);
  const nameById = new Map(read.tasks.map((t) => [t.id, t.name]));
  const columns: GridColDef<RunbookTaskRead>[] = [
    { field: 'name', headerName: 'Task', flex: 1.4, minWidth: 180 },
    {
      field: 'kind', headerName: 'Kind', width: 110,
      valueGetter: (params: GridValueGetterParams<RunbookTaskRead>) => KIND_LABEL[params.row.kind],
    },
    {
      field: 'team_name', headerName: 'Team', width: 140,
      valueGetter: (params: GridValueGetterParams<RunbookTaskRead>) => params.row.team_name ?? '—',
    },
    {
      field: 'system_name', headerName: 'System', width: 170,
      valueGetter: (params: GridValueGetterParams<RunbookTaskRead>) => params.row.system_name
        ? (params.row.system_on_release ? params.row.system_name : `${params.row.system_name} (no longer on this release)`)
        : '—',
    },
    { field: 'duration_minutes', headerName: 'Mins', width: 70 },
    {
      field: 'predecessor_ids', headerName: 'After', flex: 1, minWidth: 160, sortable: false,
      valueGetter: (params: GridValueGetterParams<RunbookTaskRead>) =>
        params.row.predecessor_ids.map((id) => nameById.get(id) ?? '—').join(', ') || '—',
    },
    {
      field: 'planned_start', headerName: 'Planned start', width: 150,
      valueGetter: (params: GridValueGetterParams<RunbookTaskRead>) => formatBookingDateTime(params.row.planned_start),
    },
    {
      field: 'forecast_start', headerName: 'Forecast start', width: 150,
      valueGetter: (params: GridValueGetterParams<RunbookTaskRead>) => formatBookingDateTime(params.row.forecast_start),
    },
    {
      field: 'status', headerName: 'Status', width: 120,
      renderCell: ({ row }) => <Chip size="small" label={STATUS_LABEL[row.status]} color={STATUS_COLOR[row.status]} />,
    },
    {
      field: 'flags', headerName: 'Flags', width: 130, sortable: false,
      renderCell: ({ row }) => (
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
          {FLAGS.filter((f) => row[f.key]).map(({ key, Icon, color }) => (
            <Tooltip key={key} title={FLAG_TEXT[key]}>
              <Icon fontSize="small" color={color} aria-label={FLAG_TEXT[key]} role="img" />
            </Tooltip>
          ))}
        </Stack>
      ),
    },
    {
      field: 'actions', headerName: 'Actions', minWidth: 240, flex: 1, sortable: false,
      renderCell: ({ row }) => (
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', height: '100%', flexWrap: 'wrap' }}>
          {row.allowed_transitions.map((to) => {
            const label = actionLabel(to, row.status);
            return (
              <Button key={to} size="small" variant={to === 'failed' ? 'text' : 'outlined'}
                      color={to === 'failed' ? 'error' : 'primary'} aria-label={`${label} ${row.name}`}
                      onClick={() => onAction(row, to)}>
                {label}
              </Button>
            );
          })}
          {row.allowed_transitions.length > 0 && (
            <Button size="small" aria-label={`Record a time for ${row.name}`} onClick={() => onRecordTime(row)}>
              Record time
            </Button>
          )}
          {canEdit && (
            <Button size="small" aria-label={`Edit ${row.name}`} onClick={() => onEdit(row)}>Edit</Button>
          )}
        </Box>
      ),
    },
  ];
  return (
    <DataTable<RunbookTaskRead>
      storageKey="release-runbook-tasks"
      userId={user?.id ?? 'guest'}
      rows={read.tasks}
      columns={columns}
      autoHeight
      disableVirtualization
      disableColumnFilter
      hideFooter
      // A runbook past 100 tasks would need real paging; out of scope for C5a.
      pageSizeOptions={[100]}
      initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}
      emptyMessage="This runbook has no tasks yet."
    />
  );
}
