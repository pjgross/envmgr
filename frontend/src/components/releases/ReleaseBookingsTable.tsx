/**
 * ReleaseBookingsTable — list bookings associated with this release.
 */
import { useMemo } from 'react';
import { Box, Chip, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import type { BookingResponse } from '../../types/booking';
import type { TestPhaseResponse } from '../../types/release';

interface Props {
  bookings: BookingResponse[];
  phases: TestPhaseResponse[];
  loading?: boolean;
}

export default function ReleaseBookingsTable({ bookings, phases, loading }: Props) {
  const phaseNameMap = useMemo(
    () => new Map(phases.map((p) => [p.id, p.name])),
    [phases]
  );

  const columns = useMemo<GridColDef<BookingResponse>[]>(
    () => [
      { field: 'id', headerName: 'ID', width: 70 },
      {
        field: 'project_name',
        headerName: 'Purpose',
        flex: 1,
        minWidth: 150,
      },
      {
        field: 'environment_name',
        headerName: 'Environment',
        width: 180,
        renderCell: (params) => (
          <Typography variant="body2">
            {params.row.environment_name ?? `Env ${params.row.environment_id}`}
          </Typography>
        ),
      },
      {
        field: 'test_phase_id',
        headerName: 'Phase',
        width: 150,
        renderCell: (params) =>
          params.row.test_phase_id ? (
            <Chip
              label={phaseNameMap.get(params.row.test_phase_id) ?? `Phase ${params.row.test_phase_id}`}
              size="small"
              variant="outlined"
            />
          ) : (
            <Typography variant="body2" color="text.secondary">
              —
            </Typography>
          ),
      },
      {
        field: 'start_date',
        headerName: 'Start',
        width: 120,
        valueFormatter: (p) =>
          p.value ? new Date(p.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'end_date',
        headerName: 'End',
        width: 120,
        valueFormatter: (p) =>
          p.value ? new Date(p.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 120,
        renderCell: (params) => <Chip label={params.row.status} size="small" />,
      },
    ],
    [phaseNameMap]
  );

  return (
    <Box sx={{ height: 300 }}>
      <DataTable<BookingResponse>
        storageKey="release-bookings-table"
        rows={bookings}
        columns={columns}
        loading={loading}
        emptyMessage="No bookings yet"
      />
    </Box>
  );
}
