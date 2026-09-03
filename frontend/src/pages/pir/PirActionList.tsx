/**
 * Every PIR action in the tenant, in one place.
 *
 * A PIR action is a process fix that outlives the release it came from — "make
 * the perf gate mandatory", not "restart the service". Inside the release's own
 * PIR tab it becomes invisible the moment attention moves on, which is the
 * classic reason PIR actions never get done. This page is the point of the
 * feature.
 *
 * READABLE BY ANY TENANT MEMBER, deliberately — the same call the contention and
 * decommission worklists made. Who may EDIT an action is settled on the PIR
 * itself, not by hiding the list.
 *
 * EVERY FILTER RUNS ON THE WIRE. Fetching a page and filtering it in the browser
 * would answer "how many process fixes are overdue" with "however many of the
 * first 25 happen to be", and `.find()` into a capped collection loses the row
 * outright rather than merely hiding it.
 *
 * `is_overdue` IS THE SERVER'S, NEVER RE-DERIVED — computed from one clock per
 * request against the same day boundary the filter uses, so a row cannot be
 * selected as overdue and rendered as not. A browser with a wrong clock cannot
 * manufacture a queue nobody can clear.
 *
 * NOTHING HERE REFUSES ANYTHING. An overdue action blocks no release transition
 * and no deployment — see backend/tests/test_pir_records_never_refuses.py. The
 * advisory line says so, because a queue of overdue items reads like a queue of
 * things that are about to stop something.
 */
import { useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  Alert, Box, Chip, FormControl, InputLabel, MenuItem, Select, Stack, Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { Link as RouterLink } from 'react-router-dom';

import type { RootState } from '../../store';
import { formatApiError } from '../../services/apiError';
import { pirService } from '../../services/pirService';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { PirActionRow, PirActionStatus } from '../../types/pir';
import PageHeader from '../../components/layout/PageHeader';

const STATUS_LABELS: Record<PirActionStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  done: 'Done',
  cancelled: 'Cancelled',
};

/**
 * "No filter" is spelled `any`, NEVER `all`.
 *
 * `all` is `buildParams`' own "no selection" sentinel and is dropped from the
 * request, so both "no filter" and a literal `all` selection would build
 * byte-identical params and the grid would never refetch — the hazard
 * documented in docs/pagination.md, and the fifth sub-project to meet it. The
 * API agrees from its side: `GET /pir-actions` has no `all` value on the wire
 * either, and an empty `?status=` is a 422, not an ignored filter.
 */
function statusParam(value: string | number | undefined): { status?: PirActionStatus } {
  return value === 'open' || value === 'in_progress' || value === 'done'
    || value === 'cancelled'
    ? { status: value }
    : {};
}

/** Narrowed on the wire, never by filtering the page in the browser. */
function ownerParam(
  value: string | number | undefined,
  userId: number | undefined,
): { owner_id?: number } {
  return value === 'me' && userId !== undefined ? { owner_id: userId } : {};
}

/**
 * The URL carries strings; the API takes a boolean, and only when asked.
 *
 * BOTH values are forwarded. `'false'` falling through to `{}` was a dead
 * control: the request became byte-identical to "Any", so *Not overdue* refetched
 * and returned the whole set, overdue rows and all, under a dropdown saying
 * otherwise. The backend implements the exact complement — undated and closed
 * actions belong to `false` — so the two answers partition the set.
 */
function overdueParam(value: string | number | undefined): { overdue?: boolean } {
  if (value === 'true') return { overdue: true };
  if (value === 'false') return { overdue: false };
  return {};
}

function formatDue(due: string | null): string {
  if (!due) return '—';
  // UTC calendar day: the form writes a due date at T00:00:00Z, so rendering it
  // in local time shows the day before to anyone west of Greenwich.
  const d = new Date(due);
  return `${d.getUTCDate()} ${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })} ${d.getUTCFullYear()}`;
}

export default function PirActionList() {
  const user = useSelector((s: RootState) => s.auth.user);

  const [rows, setRows] = useState<PirActionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Drops a superseded response rather than letting a slow first page overwrite
  // a fast second one — the same guard EscalationWorklist carries.
  const generation = useRef(0);

  const grid = useServerGrid({
    endpoint: 'pir-actions',
    filterKeys: ['status', 'action_owner', 'overdue'],
    onFetch: (params) => {
      const myGeneration = ++generation.current;
      setLoading(true);
      pirService
        .listActions({
          limit: params.limit,
          offset: params.offset,
          sort_by: params.sort_by,
          sort_dir: params.sort_dir,
          ...statusParam(params.status),
          ...ownerParam(params.action_owner, user?.id),
          ...overdueParam(params.overdue),
        })
        .then(({ rows: r, total: t }) => {
          if (myGeneration !== generation.current) return;
          setRows(r);
          setTotal(t);
          setLoadError(null);
        })
        .catch((err) => {
          if (myGeneration !== generation.current) return;
          setRows([]);
          setTotal(0);
          setLoadError(formatApiError(err, 'Failed to load PIR actions'));
        })
        .finally(() => {
          if (myGeneration === generation.current) setLoading(false);
        });
    },
    total,
    totalPending: loading,
  });

  // Read back off the URL on every mount, not held in component state, so a
  // reload or a shared link reproduces the same queue.
  const statusFilter = grid.filters.status ?? 'any';
  const ownerFilter = grid.filters.action_owner ?? 'anyone';
  const overdueFilter = grid.filters.overdue ?? 'any';

  const columns: GridColDef<PirActionRow>[] = [
    {
      field: 'title',
      headerName: 'Action',
      flex: 1,
      minWidth: 240,
      renderCell: (params) => (
        <Box sx={{ py: 0.5 }}>
          <Typography variant="body2">{params.row.title}</Typography>
          {params.row.detail && (
            <Typography variant="caption" color="text.secondary" display="block">
              {params.row.detail}
            </Typography>
          )}
        </Box>
      ),
    },
    {
      field: 'release',
      headerName: 'Release',
      width: 180,
      // The NAME travels with the row and links to the release itself. A
      // worklist is a list of things the reader has never seen, so `#7` names
      // nothing.
      renderCell: (params) => (
        <RouterLink to={`/releases/${params.row.release_id}`}>
          {params.row.release_name}
        </RouterLink>
      ),
    },
    {
      field: 'finding_title',
      headerName: 'Finding',
      flex: 1,
      minWidth: 180,
      // Joined from pir_finding, not a column on pir_action — PIR_ACTION_SORTS
      // does not carry it, and a sortable header here would 422 on click.
      sortable: false,
      renderCell: (params) => params.row.finding_title,
    },
    {
      field: 'owner',
      headerName: 'Owner',
      width: 140,
      // Resolved server-side and travelling WITH the row — never `#5`, and
      // never looked up here against a capped user list.
      renderCell: (params) => params.row.owner_username ?? '—',
    },
    {
      field: 'due_date',
      headerName: 'Due',
      width: 190,
      renderCell: (params) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <span>{formatDue(params.row.due_date)}</span>
          {/* The server's verdict, never re-derived here. */}
          {params.row.is_overdue && (
            <Chip size="small" color="error" label="Overdue" data-testid="overdue-chip" />
          )}
        </Stack>
      ),
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 130,
      renderCell: (params) => (
        <Chip size="small" variant="outlined" label={STATUS_LABELS[params.row.status]} />
      ),
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader title="PIR Actions" />

      <Alert severity="info" sx={{ mb: 2 }} data-testid="pir-actions-advisory">
        Process fixes raised by post-implementation reviews across every release. An
        overdue action stops nothing — it is work somebody owes, not a gate.
      </Alert>

      <Stack direction="row" spacing={2} sx={{ mb: 2, flexWrap: 'wrap' }}>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="pir-action-status-label">Status</InputLabel>
          <Select
            labelId="pir-action-status-label"
            label="Status"
            value={statusFilter}
            onChange={(e) => grid.setFilter('status', String(e.target.value))}
          >
            <MenuItem value="any">All</MenuItem>
            <MenuItem value="open">Open</MenuItem>
            <MenuItem value="in_progress">In progress</MenuItem>
            <MenuItem value="done">Done</MenuItem>
            <MenuItem value="cancelled">Cancelled</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="pir-action-owner-label">Owner</InputLabel>
          <Select
            labelId="pir-action-owner-label"
            label="Owner"
            value={ownerFilter}
            onChange={(e) => grid.setFilter('action_owner', String(e.target.value))}
          >
            <MenuItem value="anyone">Anyone</MenuItem>
            <MenuItem value="me">Mine</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="pir-action-overdue-label">Overdue</InputLabel>
          <Select
            labelId="pir-action-overdue-label"
            label="Overdue"
            value={overdueFilter}
            onChange={(e) => grid.setFilter('overdue', String(e.target.value))}
          >
            <MenuItem value="any">Any</MenuItem>
            <MenuItem value="true">Overdue only</MenuItem>
            <MenuItem value="false">Not overdue</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      {loadError && <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>}

      <DataGrid
        rows={rows}
        columns={columns}
        getRowHeight={() => 'auto'}
        loading={loading && rows.length === 0}
        rowCount={total}
        paginationMode="server"
        sortingMode="server"
        // `rows` is one windowed page, not the whole result set — a browser-side
        // column filter would filter the page and report a total for the set.
        disableColumnFilter
        paginationModel={grid.paginationModel}
        onPaginationModelChange={grid.onPaginationModelChange}
        sortModel={grid.sortModel}
        onSortModelChange={grid.onSortModelChange}
        pageSizeOptions={[10, 25, 50, 100]}
        sx={{ border: 1, borderColor: 'divider' }}
      />
    </Box>
  );
}
