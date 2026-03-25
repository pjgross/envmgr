import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link as RouterLink } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridRowSelectionModel,
  GridValueGetterParams,
} from '@mui/x-data-grid'
import { format } from 'date-fns'
import { AppDispatch, RootState } from '../../store'
import {
  fetchBookings,
  approveBooking,
  rejectBooking,
} from '../../store/bookingSlice'
import { fetchDefinitions } from '../../store/customFieldSlice'
import type { BookingResponse, BookingStatus } from '../../types/booking'
import BookingForm from './BookingForm'

// --- Status filter -----------------------------------------------------------

const STATUS_OPTIONS: Array<{ label: string; value: BookingStatus | 'all' }> = [
  { label: 'All',                value: 'all' },
  { label: 'Draft',              value: 'draft' },
  { label: 'Submitted',          value: 'submitted' },
  { label: 'Approved',           value: 'approved' },
  { label: 'Rejected',           value: 'rejected' },
  { label: 'Ext. Requested',     value: 'extension_requested' },
  { label: 'Closed',             value: 'closed' },
]

const STATUS_COLORS: Record<string, 'default' | 'warning' | 'success' | 'error' | 'info'> = {
  draft:               'default',
  submitted:           'warning',
  approved:            'success',
  rejected:            'error',
  extension_requested: 'warning',
  closed:              'info',
}

// --- Column visibility localStorage ------------------------------------------

function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `bookings-list-columns-${userId ?? 'guest'}`
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    return JSON.parse(raw) ?? {}
  } catch {
    return {}
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `bookings-list-columns-${userId ?? 'guest'}`
  localStorage.setItem(key, JSON.stringify(model))
}

// --- Component ---------------------------------------------------------------

export default function BookingList() {
  const dispatch = useDispatch<AppDispatch>()
  const { bookings, loading, error } = useSelector((state: RootState) => state.booking)
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  )
  const user = useSelector((state: RootState) => state.auth.user)

  const [statusFilter, setStatusFilter] = useState<BookingStatus | 'all'>('all')
  const [rowSelectionModel, setRowSelectionModel] = useState<GridRowSelectionModel>([])
  const [isBulkLoading, setIsBulkLoading] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  )

  useEffect(() => {
    dispatch(fetchBookings())
    dispatch(fetchDefinitions('booking'))
  }, [dispatch])

  // --- Filtered rows ---

  const filteredBookings =
    statusFilter === 'all'
      ? bookings
      : bookings.filter((b) => b.status === statusFilter)

  // --- Columns ---

  const coreColumns: GridColDef<BookingResponse>[] = [
    {
      field: 'project_name',
      headerName: 'Project',
      flex: 1.5,
      hideable: false,
      renderCell: ({ row }) => (
        <Button
          variant="text"
          size="small"
          component={RouterLink}
          to={`/bookings/${row.id}`}
          sx={{ textTransform: 'none', p: 0, minWidth: 0, justifyContent: 'flex-start' }}
        >
          {row.project_name}
        </Button>
      ),
    },
    {
      field: 'environment_name',
      headerName: 'Environment',
      flex: 1,
      hideable: false,
      valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
        params.row.environment_name ?? '—',
    },
    {
      field: 'booked_by_username',
      headerName: 'Booked By',
      flex: 1,
      hideable: false,
      valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
        params.row.booked_by_username ?? '—',
    },
    {
      field: 'start_date',
      headerName: 'Start',
      flex: 0.8,
      hideable: false,
      valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
        format(new Date(params.row.start_date), 'dd MMM yyyy'),
    },
    {
      field: 'end_date',
      headerName: 'End',
      flex: 0.8,
      hideable: false,
      valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
        format(new Date(params.row.end_date), 'dd MMM yyyy'),
    },
    {
      field: 'booking_type_id',
      headerName: 'Type',
      flex: 0.8,
      hideable: false,
      renderCell: ({ row }) => (
        <Chip
          label={row.booking_type_id}
          size="small"
          color="primary"
          variant="outlined"
        />
      ),
    },
    {
      field: 'status',
      headerName: 'Status',
      flex: 0.8,
      hideable: false,
      renderCell: ({ row }) => (
        <Chip
          label={row.status}
          size="small"
          color={STATUS_COLORS[row.status]}
        />
      ),
    },
  ]

  const customFieldColumns: GridColDef<BookingResponse>[] = customFieldDefs.map((def) => ({
    field: def.field_key,
    headerName: def.label,
    flex: 1,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      params.row.custom_fields?.[def.field_key] ?? '—',
  } as GridColDef<BookingResponse>))

  const columns = [...coreColumns, ...customFieldColumns]

  // --- Bulk actions ---

  const handleBulkApprove = async () => {
    setIsBulkLoading(true)
    const results = await Promise.allSettled(
      rowSelectionModel.map((id) => dispatch(approveBooking(Number(id))))
    )
    // Only clear rows that were successfully processed
    const successIds = rowSelectionModel.filter((_, i) => results[i].status === 'fulfilled')
    setRowSelectionModel((prev) => prev.filter((id) => !successIds.includes(id)))
    setIsBulkLoading(false)
  }

  const handleBulkReject = async () => {
    setIsBulkLoading(true)
    const results = await Promise.allSettled(
      rowSelectionModel.map((id) => dispatch(rejectBooking(Number(id))))
    )
    const successIds = rowSelectionModel.filter((_, i) => results[i].status === 'fulfilled')
    setRowSelectionModel((prev) => prev.filter((id) => !successIds.includes(id)))
    setIsBulkLoading(false)
  }

  // --- Column visibility ---

  const handleColumnVisibilityChange = (model: GridColumnVisibilityModel) => {
    setColumnVisibilityModel(model)
    saveColumnModel(user?.id, model)
  }

  // Only show loading overlay on initial load (not during bulk operations)
  const isInitialLoading = loading && bookings.length === 0

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
          Status:
        </Typography>
        {STATUS_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            clickable
            color={statusFilter === opt.value ? 'primary' : 'default'}
            variant={statusFilter === opt.value ? 'filled' : 'outlined'}
            onClick={() => setStatusFilter(opt.value)}
            size="small"
          />
        ))}
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" size="small" onClick={() => setFormOpen(true)}>
          + New Booking
        </Button>
      </Box>

      {/* Error */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Selection toolbar */}
      {rowSelectionModel.length > 0 && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: 2,
            py: 1,
            mb: 0,
            bgcolor: 'primary.50',
            border: '1px solid',
            borderColor: 'primary.200',
            borderBottom: 'none',
            borderRadius: '4px 4px 0 0',
          }}
        >
          <Typography variant="body2" color="primary" fontWeight={500}>
            {rowSelectionModel.length} selected
          </Typography>
          <Button
            size="small"
            color="success"
            variant="contained"
            startIcon={<CheckIcon />}
            disabled={isBulkLoading}
            onClick={handleBulkApprove}
          >
            Approve
          </Button>
          <Button
            size="small"
            color="error"
            variant="contained"
            startIcon={<CloseIcon />}
            disabled={isBulkLoading}
            onClick={handleBulkReject}
          >
            Reject
          </Button>
          <Box sx={{ flexGrow: 1 }} />
          <Button
            size="small"
            color="inherit"
            onClick={() => setRowSelectionModel([])}
          >
            Clear
          </Button>
        </Box>
      )}

      {/* DataGrid */}
      <DataGrid
        rows={filteredBookings}
        columns={columns}
        loading={isInitialLoading}
        checkboxSelection
        rowSelectionModel={rowSelectionModel}
        onRowSelectionModelChange={setRowSelectionModel}
        columnVisibilityModel={columnVisibilityModel}
        onColumnVisibilityModelChange={handleColumnVisibilityChange}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      {/* New Booking dialog */}
      <BookingForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  )
}
