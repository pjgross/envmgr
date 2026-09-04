/**
 * ScopeTable — MUI DataGrid of scope items (release changes).
 *
 * "Group by Epic" toggle is deferred to sub-project 3.
 */
import { useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import { Box, Button, Chip, IconButton, MenuItem, TextField, Tooltip, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import DriveFileMoveIcon from '@mui/icons-material/DriveFileMove';
import HistoryIcon from '@mui/icons-material/History';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { AppDispatch } from '../../store';
import { deleteReleaseChange, fetchReleaseChanges } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import ScopeItemDialog from './ScopeItemDialog';
import MoveScopeItemDialog from './MoveScopeItemDialog';
import ScopeHistoryDrawer from './ScopeHistoryDrawer';
import type { ReleaseChangeResponse } from '../../types/releaseChange';

interface Props {
  releaseId: number;
  changes: ReleaseChangeResponse[];
  loading?: boolean;
}

const KIND_COLORS: Record<string, 'default' | 'info' | 'error' | 'warning'> = {
  story: 'info',
  defect: 'error',
  task: 'default',
  spike: 'warning',
};

export default function ScopeTable({ releaseId, changes, loading }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editItem, setEditItem] = useState<ReleaseChangeResponse | null>(null);

  const [moveDialogOpen, setMoveDialogOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState<ReleaseChangeResponse | null>(null);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyTarget, setHistoryTarget] = useState<ReleaseChangeResponse | null>(null);

  const [projectFilter, setProjectFilter] = useState('');

  const projectCodes = useMemo(() => {
    const codes = new Set<string>();
    changes.forEach((c) => {
      if (c.project_code) codes.add(c.project_code);
    });
    return Array.from(codes).sort();
  }, [changes]);

  const filteredChanges = useMemo(
    () =>
      projectFilter
        ? changes.filter((c) => c.project_code === projectFilter)
        : changes,
    [changes, projectFilter],
  );

  const openCreate = () => {
    setEditItem(null);
    setDialogOpen(true);
  };

  const openEdit = (item: ReleaseChangeResponse) => {
    setEditItem(item);
    setDialogOpen(true);
  };

  const openMove = (item: ReleaseChangeResponse) => {
    setMoveTarget(item);
    setMoveDialogOpen(true);
  };

  const openHistory = (item: ReleaseChangeResponse) => {
    setHistoryTarget(item);
    setHistoryOpen(true);
  };

  const handleDelete = async (item: ReleaseChangeResponse) => {
    const label = item.title ? `scope item "${item.title}"` : 'this scope item';
    if (!(await confirm({ message: `Delete ${label}?`, destructive: true }))) return;
    try {
      await dispatch(deleteReleaseChange(item.id)).unwrap();
      snackbar.success('Scope item deleted');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete scope item');
    }
  };

  const handleMoved = () => {
    dispatch(fetchReleaseChanges(releaseId));
  };

  const columns = useMemo<GridColDef<ReleaseChangeResponse>[]>(
    () => [
      {
        field: 'external_key',
        headerName: 'Key',
        width: 110,
        renderCell: (params) => (
          <Typography variant="body2" color="text.secondary">
            {params.row.external_key ?? '—'}
          </Typography>
        ),
      },
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
          <Typography variant="body2">
            {params.row.external_status ?? '—'}
          </Typography>
        ),
      },
      {
        field: 'project_code',
        headerName: 'Project',
        width: 110,
        renderCell: (params) => (
          <Typography variant="body2">
            {params.row.project_code ?? '—'}
          </Typography>
        ),
      },
      {
        field: 'project_name',
        headerName: 'Project Name',
        width: 160,
        renderCell: (params) => (
          <Typography variant="body2" color="text.secondary">
            {params.row.project_name ?? '—'}
          </Typography>
        ),
      },
      {
        field: 'source',
        headerName: 'Source',
        width: 90,
        renderCell: (params) => (
          <Chip label={params.row.source} size="small" variant="outlined" />
        ),
      },
      {
        field: 'is_scope_creep',
        headerName: 'Scope',
        width: 110,
        renderCell: (params) =>
          params.row.is_scope_creep ? (
            <Chip label="Creep" color="warning" size="small" />
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
      {
        field: '_actions',
        headerName: '',
        width: 120,
        sortable: false,
        renderCell: (params) => (
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <Tooltip
              title={
                params.row.source === 'jira'
                  ? 'Cannot move jira-sourced scope items'
                  : 'Move to another release'
              }
            >
              <span>
                <IconButton
                  size="small"
                  color="primary"
                  disabled={params.row.source === 'jira'}
                  onClick={(e) => {
                    e.stopPropagation();
                    openMove(params.row);
                  }}
                >
                  <DriveFileMoveIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="View history">
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation();
                  openHistory(params.row);
                }}
              >
                <HistoryIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <IconButton
              size="small"
              color="error"
              aria-label="Delete scope item"
              onClick={(e) => {
                e.stopPropagation();
                handleDelete(params.row);
              }}
            >
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Box>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [releaseId]
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">
          Scope Items ({filteredChanges.length})
          {(() => {
            const creep = filteredChanges.filter((c) => c.is_scope_creep).length;
            return creep > 0 ? ` — ${creep} added after scope deadline` : '';
          })()}
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <TextField
            select
            size="small"
            label="Project"
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}
            sx={{ minWidth: 160 }}
            disabled={projectCodes.length === 0}
          >
            <MenuItem value="">All projects</MenuItem>
            {projectCodes.map((code) => (
              <MenuItem key={code} value={code}>
                {code}
              </MenuItem>
            ))}
          </TextField>
          <Button size="small" startIcon={<AddIcon />} onClick={openCreate}>
            Add Item
          </Button>
        </Box>
      </Box>

      <Box sx={{ height: 400 }}>
        <DataTable<ReleaseChangeResponse>
          storageKey="release-scope-table"
          rows={filteredChanges}
          columns={columns}
          loading={loading}
          emptyMessage="No scope items yet"
          onRowClick={(params: GridRowParams<ReleaseChangeResponse>) => openEdit(params.row)}
        />
      </Box>

      {confirmDialog}
      <ScopeItemDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        releaseId={releaseId}
        item={editItem}
      />
      {moveTarget && (
        <MoveScopeItemDialog
          open={moveDialogOpen}
          onClose={() => setMoveDialogOpen(false)}
          changeId={moveTarget.id}
          currentReleaseId={moveTarget.release_id}
          itemTitle={moveTarget.title}
          onMoved={handleMoved}
        />
      )}
      {historyTarget && (
        <ScopeHistoryDrawer
          open={historyOpen}
          onClose={() => setHistoryOpen(false)}
          changeId={historyTarget.id}
          itemTitle={historyTarget.title}
        />
      )}
    </Box>
  );
}
