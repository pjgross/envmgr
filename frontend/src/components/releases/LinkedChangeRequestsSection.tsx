/**
 * LinkedChangeRequestsSection — tabular list of change requests linked to this release.
 */
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Chip, Typography } from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { releaseService } from '../../services/releaseService';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import type { ChangeRequestResponse } from '../../types/changeRequest';

interface Props {
  releaseId: number;
  changeRequests: ChangeRequestResponse[];
  loading?: boolean;
  onUnlinked: () => void;
}

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  in_progress: 'info',
  completed: 'info',
};

export default function LinkedChangeRequestsSection({
  releaseId,
  changeRequests,
  loading,
  onUnlinked,
}: Props) {
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const handleUnlink = async (crId: number) => {
    if (!(await confirm({ message: 'Unlink this change request from the release?', destructive: true }))) return;
    try {
      await releaseService.unlinkChangeRequest(releaseId, crId);
      snackbar.success('Change request unlinked');
      onUnlinked();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to unlink');
    }
  };

  const columns = useMemo<GridColDef<ChangeRequestResponse>[]>(
    () => [
      { field: 'id', headerName: 'ID', width: 70 },
      { field: 'title', headerName: 'Title', flex: 1, minWidth: 200 },
      { field: 'change_type', headerName: 'Type', width: 150 },
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
        field: '_actions',
        headerName: '',
        width: 80,
        sortable: false,
        renderCell: (params) => (
          <Button
            size="small"
            color="error"
            onClick={(e) => {
              e.stopPropagation();
              handleUnlink(params.row.id);
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
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Linked Change Requests
      </Typography>
      <Box sx={{ height: 300 }}>
        <DataTable<ChangeRequestResponse>
          storageKey="release-linked-crs-table"
          rows={changeRequests}
          columns={columns}
          loading={loading}
          emptyMessage="No change requests linked"
          onRowClick={(params) => navigate(`/change-requests/${params.row.id}`)}
        />
      </Box>
      {confirmDialog}
    </Box>
  );
}
