/**
 * RaidTab — per-release RAID log with R/A/I/D sub-tabs, filters and grids.
 * Summary cards + heat-map are layered on in Task E3.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Chip,
  FormControlLabel,
  IconButton,
  MenuItem,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../../DataTable';
import { AppDispatch, RootState } from '../../../store';
import { fetchRaidItems, deleteRaidItem, fetchRaidConfig, fetchRaidSummary } from '../../../store/raidSlice';
import { fetchUsers } from '../../../store/tenantAdminSlice';
import RaidSummaryCards from './RaidSummaryCards';
import RaidHeatMap from './RaidHeatMap';
import { Collapse, Paper } from '@mui/material';
import { useSnackbar } from '../../../hooks/useSnackbar';
import { useConfirm } from '../../../hooks/useConfirm';
import type { RaidItemResponse, RaidItemType, RaidRag } from '../../../types/raid';
import { RAID_TYPE_LABELS } from '../../../types/raid';
import RaidItemDialog from './RaidItemDialog';
import { RAID_TYPES, RAID_STATUSES, ragChipSx, isOverdueReview, titleCase } from './raidConstants';

interface Props {
  releaseId: number;
}

function fmtDate(d: string | null): string {
  return d ? new Date(d).toLocaleDateString() : '—';
}

export default function RaidTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const items = useSelector((s: RootState) => s.raid.items);
  const loading = useSelector((s: RootState) => s.raid.loading);
  const config = useSelector((s: RootState) => s.raid.config);
  const summary = useSelector((s: RootState) => s.raid.summary);
  const users = useSelector((s: RootState) => s.tenantAdmin.users);

  const [showHeatMap, setShowHeatMap] = useState(false);

  const [typeTab, setTypeTab] = useState<RaidItemType>('risk');
  const [statusFilter, setStatusFilter] = useState('');
  const [ownerFilter, setOwnerFilter] = useState<string>('');
  const [ragFilter, setRagFilter] = useState<string>('');
  const [overdueOnly, setOverdueOnly] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editItem, setEditItem] = useState<RaidItemResponse | null>(null);
  const [createType, setCreateType] = useState<RaidItemType>('risk');

  useEffect(() => {
    dispatch(fetchRaidItems({ releaseId }));
    dispatch(fetchRaidConfig());
    dispatch(fetchRaidSummary(releaseId));
    dispatch(fetchUsers());
  }, [dispatch, releaseId]);

  const ownerName = (ownerId: number | null): string => {
    if (ownerId == null) return '—';
    return users.find((u) => u.id === ownerId)?.username ?? '—';
  };

  const refresh = () => {
    dispatch(fetchRaidItems({ releaseId }));
    dispatch(fetchRaidSummary(releaseId));
  };

  const typeItems = useMemo(
    () => items.filter((i) => i.item_type === typeTab),
    [items, typeTab],
  );

  const filtered = useMemo(
    () =>
      typeItems.filter((i) => {
        if (statusFilter && i.status !== statusFilter) return false;
        if (ownerFilter && String(i.owner_id ?? '') !== ownerFilter) return false;
        if (ragFilter && i.rag !== ragFilter) return false;
        if (overdueOnly && !isOverdueReview(i.review_date, i.status)) return false;
        return true;
      }),
    [typeItems, statusFilter, ownerFilter, ragFilter, overdueOnly],
  );

  // Owners present in this type's items, for the filter dropdown.
  const ownerOptions = useMemo(() => {
    const ids = new Set<number>();
    typeItems.forEach((i) => {
      if (i.owner_id != null) ids.add(i.owner_id);
    });
    return Array.from(ids);
  }, [typeItems]);

  const openCreate = () => {
    setEditItem(null);
    setCreateType(typeTab);
    setDialogOpen(true);
  };

  const openEdit = (item: RaidItemResponse) => {
    setEditItem(item);
    setDialogOpen(true);
  };

  const handleDelete = async (item: RaidItemResponse) => {
    if (!(await confirm({ message: `Delete ${item.ref_code} "${item.title}"?`, destructive: true }))) return;
    try {
      await dispatch(deleteRaidItem({ releaseId, itemId: item.id })).unwrap();
      snackbar.success(`${item.ref_code} deleted`);
      dispatch(fetchRaidSummary(releaseId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete item');
    }
  };

  const scored = typeTab === 'risk' || typeTab === 'issue';

  const columns = useMemo<GridColDef<RaidItemResponse>[]>(() => {
    const cols: GridColDef<RaidItemResponse>[] = [
      { field: 'ref_code', headerName: 'Ref', width: 90 },
      { field: 'title', headerName: 'Title', flex: 1, minWidth: 200 },
      {
        field: 'owner_id',
        headerName: 'Owner',
        width: 130,
        valueGetter: (params) => ownerName(params.row.owner_id),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 130,
        renderCell: (params) => <Chip label={titleCase(params.row.status)} size="small" variant="outlined" />,
      },
    ];
    if (scored) {
      cols.push(
        {
          field: 'rag',
          headerName: 'RAG',
          width: 90,
          renderCell: (params) =>
            params.row.rag ? (
              <Chip
                label={params.row.rag.toUpperCase()}
                size="small"
                sx={ragChipSx(params.row.rag as RaidRag, config)}
              />
            ) : (
              <Typography variant="body2" color="text.secondary">—</Typography>
            ),
        },
        {
          field: 'severity',
          headerName: 'Severity',
          width: 90,
          renderCell: (params) => (
            <Typography variant="body2">{params.row.severity ?? '—'}</Typography>
          ),
        },
      );
    }
    cols.push(
      {
        field: 'target_date',
        headerName: 'Target',
        width: 110,
        valueGetter: (params) => fmtDate(params.row.target_date),
      },
      {
        field: 'review_date',
        headerName: 'Review',
        width: 110,
        renderCell: (params) => (
          <Typography
            variant="body2"
            color={isOverdueReview(params.row.review_date, params.row.status) ? 'error' : 'text.primary'}
          >
            {fmtDate(params.row.review_date)}
          </Typography>
        ),
      },
      {
        field: '_actions',
        headerName: '',
        width: 60,
        sortable: false,
        renderCell: (params) => (
          <IconButton
            size="small"
            color="error"
            aria-label="Delete RAID item"
            onClick={(e) => {
              e.stopPropagation();
              handleDelete(params.row);
            }}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        ),
      },
    );
    return cols;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scored, config, users]);

  return (
    <Box>
      <RaidSummaryCards summary={summary} config={config} />

      <Box sx={{ mb: 1 }}>
        <Button size="small" onClick={() => setShowHeatMap((v) => !v)}>
          {showHeatMap ? 'Hide' : 'Show'} probability × impact heat-map
        </Button>
        <Collapse in={showHeatMap}>
          <Paper variant="outlined" sx={{ p: 2, mt: 1, display: 'inline-block' }}>
            <RaidHeatMap config={config} heatmap={summary?.heatmap} />
          </Paper>
        </Collapse>
      </Box>

      <Tabs
        value={typeTab}
        onChange={(_, v) => {
          setTypeTab(v);
          setStatusFilter('');
          setOwnerFilter('');
          setRagFilter('');
          setOverdueOnly(false);
        }}
        sx={{ mb: 2 }}
      >
        {RAID_TYPES.map((t) => (
          <Tab key={t} value={t} label={RAID_TYPE_LABELS[t]} />
        ))}
      </Tabs>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
        <TextField
          select
          size="small"
          label="Status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          sx={{ minWidth: 150 }}
        >
          <MenuItem value="">All statuses</MenuItem>
          {RAID_STATUSES[typeTab].map((s) => (
            <MenuItem key={s} value={s}>{titleCase(s)}</MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Owner"
          value={ownerFilter}
          onChange={(e) => setOwnerFilter(e.target.value)}
          sx={{ minWidth: 150 }}
          disabled={ownerOptions.length === 0}
        >
          <MenuItem value="">All owners</MenuItem>
          {ownerOptions.map((id) => (
            <MenuItem key={id} value={String(id)}>{ownerName(id)}</MenuItem>
          ))}
        </TextField>
        {scored && (
          <TextField
            select
            size="small"
            label="RAG"
            value={ragFilter}
            onChange={(e) => setRagFilter(e.target.value)}
            sx={{ minWidth: 120 }}
          >
            <MenuItem value="">All</MenuItem>
            <MenuItem value="green">Green</MenuItem>
            <MenuItem value="amber">Amber</MenuItem>
            <MenuItem value="red">Red</MenuItem>
          </TextField>
        )}
        <FormControlLabel
          control={<Switch checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} />}
          label="Overdue reviews"
        />
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          Add {titleCase(typeTab)}
        </Button>
      </Box>

      <Box sx={{ height: 440 }}>
        <DataTable<RaidItemResponse>
          storageKey={`release-raid-${typeTab}`}
          rows={filtered}
          columns={columns}
          loading={loading}
          emptyMessage={`No ${RAID_TYPE_LABELS[typeTab].toLowerCase()} yet`}
          onRowClick={(params: GridRowParams<RaidItemResponse>) => openEdit(params.row)}
        />
      </Box>

      {confirmDialog}
      <RaidItemDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        releaseId={releaseId}
        item={editItem}
        defaultType={createType}
        onChanged={refresh}
      />
    </Box>
  );
}
