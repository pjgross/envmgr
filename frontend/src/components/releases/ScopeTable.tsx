/**
 * ScopeTable — MUI DataGrid of scope items (release changes).
 *
 * "Group by Epic" toggle is deferred to sub-project 3.
 */
import { useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import { Box, Button, Chip, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { AppDispatch } from '../../store';
import { deleteReleaseChange } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import ScopeItemDialog from './ScopeItemDialog';
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

  const openCreate = () => {
    setEditItem(null);
    setDialogOpen(true);
  };

  const openEdit = (item: ReleaseChangeResponse) => {
    setEditItem(item);
    setDialogOpen(true);
  };

  const handleDelete = async (changeId: number) => {
    if (!(await confirm({ message: 'Delete this scope item?', destructive: true }))) return;
    try {
      await dispatch(deleteReleaseChange(changeId)).unwrap();
      snackbar.success('Scope item deleted');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete scope item');
    }
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
        field: 'source',
        headerName: 'Source',
        width: 90,
        renderCell: (params) => (
          <Chip label={params.row.source} size="small" variant="outlined" />
        ),
      },
      {
        field: '_actions',
        headerName: '',
        width: 70,
        sortable: false,
        renderCell: (params) => (
          <Button
            size="small"
            color="error"
            onClick={(e) => {
              e.stopPropagation();
              handleDelete(params.row.id);
            }}
          >
            <DeleteIcon fontSize="small" />
          </Button>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [releaseId]
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">
          Scope Items ({changes.length})
        </Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={openCreate}>
          Add Item
        </Button>
      </Box>

      <Box sx={{ height: 400 }}>
        <DataTable<ReleaseChangeResponse>
          storageKey="release-scope-table"
          rows={changes}
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
    </Box>
  );
}
