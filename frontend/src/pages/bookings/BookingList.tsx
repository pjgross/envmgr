import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  Typography,
} from '@mui/material'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridValueGetterParams,
} from '@mui/x-data-grid'
import { format } from 'date-fns'
import { AppDispatch, RootState } from '../../store'
import { fetchBookings } from '../../store/bookingSlice'
import { fetchDefinitions } from '../../store/customFieldSlice'
import type { BookingResponse, BookingStatus } from '../../types/booking'
import type { AllowedTransition } from '../../types/bookingLifecycle'
import { bookingService } from '../../services/bookingService'
import ConflictIndicator from '../../components/bookings/ConflictIndicator'
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
  const navigate = useNavigate()
  const { bookings, loading, error } = useSelector((state: RootState) => state.booking)
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  )
  const user = useSelector((state: RootState) => state.auth.user)

  const [statusFilter, setStatusFilter] = useState<BookingStatus | 'all'>('all')
  const [formOpen, setFormOpen] = useState(false)
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  )

  // Kebab menu state: tracks which row's menu is open and the anchor element
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; rowId: number } | null>(null)

  // Per-row transition cache keyed by booking id
  const [transitionCache, setTransitionCache] = useState<Record<number, AllowedTransition[]>>({})

  // Transition error state for local error feedback
  const [transitionError, setTransitionError] = useState<string | null>(null)

  useEffect(() => {
    dispatch(fetchBookings())
    dispatch(fetchDefinitions('booking'))
  }, [dispatch])

  // --- Filtered rows ---

  const filteredBookings =
    statusFilter === 'all'
      ? bookings
      : bookings.filter((b) => b.status === statusFilter)

  // --- Kebab menu handlers ---

  const handleMenuOpen = async (el: HTMLElement, rowId: number) => {
    setMenuAnchor({ el, rowId })
    // Lazily fetch transitions if not cached
    if (!(rowId in transitionCache)) {
      try {
        const transitions = await bookingService.getAllowedTransitions(rowId)
        setTransitionCache((prev) => ({ ...prev, [rowId]: transitions }))
      } catch {
        setTransitionCache((prev) => ({ ...prev, [rowId]: [] }))
      }
    }
  }

  const handleMenuClose = () => {
    setMenuAnchor(null)
  }

  const handleOpenDetail = (rowId: number) => {
    handleMenuClose()
    navigate(`/bookings/${rowId}`)
  }

  const handleTransition = async (rowId: number, toState: string) => {
    handleMenuClose()
    // Invalidate cache entry so next open re-fetches fresh transitions
    setTransitionCache((prev) => {
      const next = { ...prev }
      delete next[rowId]
      return next
    })
    try {
      await bookingService.transitionState(rowId, toState)
      dispatch(fetchBookings())
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Transition failed'
      setTransitionError(msg)
    }
  }

  // --- Column visibility ---

  const handleColumnVisibilityChange = (model: GridColumnVisibilityModel) => {
    setColumnVisibilityModel(model)
    saveColumnModel(user?.id, model)
  }

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
    {
      field: 'conflicts',
      headerName: 'Conflicts',
      width: 90,
      hideable: false,
      sortable: false,
      renderCell: ({ row }) => (
        <ConflictIndicator hasUnacknowledged={row.has_unacknowledged_conflicts} />
      ),
    },
    {
      field: 'actions',
      headerName: '',
      width: 48,
      hideable: false,
      sortable: false,
      disableColumnMenu: true,
      renderCell: ({ row }) => (
        <IconButton
          size="small"
          onClick={(e) => handleMenuOpen(e.currentTarget, row.id)}
          aria-label="row actions"
        >
          <MoreVertIcon fontSize="small" />
        </IconButton>
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

  // Only show loading overlay on initial load
  const isInitialLoading = loading && bookings.length === 0

  // Transitions for the currently open menu row
  const activeTransitions = menuAnchor ? (transitionCache[menuAnchor.rowId] ?? null) : null

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

      {/* Transition Error */}
      {transitionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setTransitionError(null)}>
          {transitionError}
        </Alert>
      )}

      {/* DataGrid */}
      <DataGrid
        rows={filteredBookings}
        columns={columns}
        loading={isInitialLoading}
        columnVisibilityModel={columnVisibilityModel}
        onColumnVisibilityModelChange={handleColumnVisibilityChange}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      {/* Per-row kebab menu */}
      <Menu
        anchorEl={menuAnchor?.el}
        open={Boolean(menuAnchor)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={() => menuAnchor && handleOpenDetail(menuAnchor.rowId)}>
          Open
        </MenuItem>
        {activeTransitions && activeTransitions.length > 0 && (
          <Divider />
        )}
        {activeTransitions === null && (
          <MenuItem disabled>Loading...</MenuItem>
        )}
        {activeTransitions?.map((t) => (
          <MenuItem
            key={t.to_state}
            onClick={() => menuAnchor && handleTransition(menuAnchor.rowId, t.to_state)}
          >
            {t.label}
          </MenuItem>
        ))}
      </Menu>

      {/* New Booking dialog */}
      <BookingForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  )
}
