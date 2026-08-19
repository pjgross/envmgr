/**
 * The decommission worklist — every decommission this tenant can see, live
 * and terminal alike, following `EscalationWorklist` (A4's own worklist,
 * the direct precedent for this page's shape, its server-side paging, its
 * filter wiring and its URL handling).
 *
 * READABLE BY ANY TENANT MEMBER — this page carries no gate of its own,
 * matching `GET /decommissions`' own docstring ("there is no gate here
 * beyond tenant scoping"). Who may ACT on a decommission (extend, sign,
 * tear down, cancel) is settled on `DecommissionPanel`, on the environment's
 * own detail page — this worklist exists to be TRIAGED, not acted on: there
 * is no action control here at all, only a link to where the action lives.
 *
 * THIS IS THE ONE PLACE `fetchDecommissionWorklist` (`store/decommissionSlice.ts`)
 * IS DISPATCHED — the thunk shipped with no UI caller ahead of this task.
 * Unlike `EscalationWorklist`, which calls its service directly with no
 * slice in front of it, the worklist state (`worklist`/`worklistTotal`/
 * `worklistLoading`/`worklistError`) already lives on `decommissionSlice`,
 * so this page reads it back rather than holding a parallel copy in local
 * state.
 *
 * THE TWO STATES THAT MEAN SOMEBODY MUST ACT ARE `due` (the notice period
 * has elapsed) and `extension_requested` (the operating team is waiting on
 * an answer). The chip colours below are the ones `EnvironmentList` and
 * `DecommissionPanel` already use for these five literals — kept identical
 * rather than reinvented here, so the same state reads the same way
 * wherever a reader has seen it before.
 *
 * `state` IS THE SERVER'S, NEVER RE-DERIVED — computed from three columns
 * and one clock per request (`decommissions.py`: "ONE CLOCK decides both
 * the `state` filter and every rendered row's state"), so a row cannot be
 * selected as `due` and rendered `warned`, and a browser with a wrong clock
 * cannot manufacture a queue of phantom urgency.
 *
 * EVERY ROW IS IDENTIFIED BY NAME. `environment_name`, `owner_username` and
 * `initiated_by_username` travel with the row, resolved server-side in one
 * batch (`environment_decommission_service.decommission_views`) — the same
 * reason `Escalation`'s names do. A `#N` fallback, or a browser-side lookup
 * into a separately-fetched, capped picker collection, is exactly the
 * defect the pagination sweep found renders entities as `—`.
 */
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Chip, Link, Typography } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';

import type { AppDispatch, RootState } from '../../store';
import { fetchDecommissionWorklist } from '../../store/decommissionSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { DecommissionState, DecommissionWorklistRow } from '../../types/decommission';

// The exact five literals in `backend/app/core/decommission_states.py` /
// `types/decommission.ts`. Duplicated rather than imported from
// `DecommissionPanel`/`EnvironmentList` — the third copy of this map in the
// codebase, deliberately: each file's only coupling to the others is the
// shared `DecommissionState` type, not a shared constants module.
const STATE_LABELS: Record<DecommissionState, string> = {
  warned: 'Warned',
  due: 'Due',
  extension_requested: 'Extension requested',
  torn_down: 'Torn down',
  cancelled: 'Cancelled',
};

const STATE_COLORS: Record<DecommissionState, 'warning' | 'error' | 'info' | 'default'> = {
  warned: 'warning',
  due: 'error',
  extension_requested: 'info',
  torn_down: 'default',
  cancelled: 'default',
};

type StateFilter = 'any' | DecommissionState;

const STATE_FILTERS: { label: string; value: StateFilter }[] = [
  { label: 'All', value: 'any' },
  { label: 'Warned', value: 'warned' },
  { label: 'Due', value: 'due' },
  { label: 'Extension requested', value: 'extension_requested' },
  { label: 'Torn down', value: 'torn_down' },
  { label: 'Cancelled', value: 'cancelled' },
];

const DECOMMISSION_STATE_SET = new Set<string>(Object.keys(STATE_LABELS));

/**
 * "No filter" is spelled `any`, NEVER `all`.
 *
 * `all` is `buildParams`' own "no selection" sentinel and is dropped from
 * the request before it is ever built, so both "no filter" and a literal
 * `all` selection would build byte-identical params and the grid would
 * never refetch — the hazard A3, A4, B2 and B4 each hit in turn, documented
 * in docs/pagination.md. `GET /decommissions` agrees from its side: there
 * is deliberately no `all` value in its `state` pattern either, and
 * OMISSION is how a caller asks for everything.
 */
function stateParam(value: string | number | undefined): { state?: DecommissionState } {
  return typeof value === 'string' && DECOMMISSION_STATE_SET.has(value)
    ? { state: value as DecommissionState }
    : {};
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

export default function DecommissionWorklist() {
  const dispatch = useDispatch<AppDispatch>();
  const { worklist, worklistTotal, worklistLoading, worklistError } = useSelector(
    (s: RootState) => s.decommission
  );

  // `useServerGrid` aborts a superseded dispatch itself (the returned
  // `Abortable`); the slice's `fetchDecommissionWorklist.rejected` case
  // guards on `action.meta.aborted` for the same reason
  // `fetchReleases.rejected` does, so an aborted request cannot clobber
  // `worklistLoading`/`worklistError` after a newer request has already
  // resolved.
  const grid = useServerGrid({
    endpoint: 'decommissions',
    filterKeys: ['state'],
    total: worklistTotal,
    totalPending: worklistLoading,
    onFetch: (params) =>
      dispatch(
        fetchDecommissionWorklist({
          page: params.offset / params.limit,
          pageSize: params.limit,
          sortBy: params.sort_by as 'scheduled_teardown_at' | 'warned_at' | 'environment',
          sortDir: params.sort_dir,
          ...stateParam(params.state),
        })
      ),
  });

  const stateFilter = grid.filters.state ?? 'any';

  const columns: GridColDef<DecommissionWorklistRow>[] = [
    {
      field: 'environment',
      headerName: 'Environment',
      flex: 1,
      minWidth: 200,
      // `DECOMMISSION_SORTS['environment']` is `Environment.name`, joined —
      // not a column on this row, so no `valueGetter` reads `row.environment`.
      renderCell: (params) => (
        <Link
          component={RouterLink}
          to={`/environments/${params.row.environment_id}`}
          underline="hover"
        >
          {params.row.environment_name ?? `Environment ${params.row.environment_id}`}
        </Link>
      ),
    },
    {
      field: 'state',
      headerName: 'State',
      width: 170,
      // Computed server-side from three columns and a clock — there is no
      // `state` column to sort by (decommissions.py: "deliberately NOT in
      // this whitelist").
      sortable: false,
      renderCell: (params) => (
        <Chip
          size="small"
          label={STATE_LABELS[params.row.state]}
          color={STATE_COLORS[params.row.state]}
        />
      ),
    },
    {
      field: 'warned_at',
      headerName: 'Warned',
      width: 130,
      renderCell: (params) => formatDate(params.row.warned_at),
    },
    {
      field: 'scheduled_teardown_at',
      headerName: 'Scheduled teardown',
      width: 170,
      renderCell: (params) => formatDate(params.row.scheduled_teardown_at),
    },
    {
      field: 'reason',
      headerName: 'Reason',
      flex: 1,
      minWidth: 200,
      sortable: false,
    },
    {
      field: 'owner_username',
      headerName: 'Owner',
      width: 150,
      sortable: false, // joined from the user table, not a column on this row
      renderCell: (params) => params.row.owner_username ?? 'No owner on record',
    },
    {
      field: 'initiated_by_username',
      headerName: 'Initiated by',
      width: 150,
      sortable: false,
      renderCell: (params) => params.row.initiated_by_username ?? 'Someone no longer in this tenant',
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" fontWeight="bold" sx={{ mb: 1 }}>
        Decommissions
      </Typography>

      <Alert severity="info" sx={{ mb: 2 }} data-testid="worklist-advisory">
        Every environment decommission this tenant has raised. <strong>Due</strong> and{' '}
        <strong>Extension requested</strong> are the two states that need somebody to act — open
        the environment to sign a step, decide an extension, or tear it down.
      </Alert>

      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
          State
        </Typography>
        {STATE_FILTERS.map((f) => (
          <Chip
            key={f.value}
            label={f.label}
            clickable
            component="button"
            color={stateFilter === f.value ? 'primary' : 'default'}
            variant={stateFilter === f.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('state', f.value)}
          />
        ))}
      </Box>

      {worklistError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {worklistError}
        </Alert>
      )}

      <DataGrid
        rows={worklist}
        columns={columns}
        getRowId={(row) => row.id}
        getRowHeight={() => 'auto'}
        loading={worklistLoading && worklist.length === 0}
        rowCount={worklistTotal}
        paginationMode="server"
        sortingMode="server"
        // `worklist` is one windowed page, not the whole result set — a
        // browser-side column filter would filter the page and report a
        // total for the set.
        disableColumnFilter
        paginationModel={grid.paginationModel}
        onPaginationModelChange={grid.onPaginationModelChange}
        sortModel={grid.sortModel}
        onSortModelChange={grid.onSortModelChange}
        pageSizeOptions={[10, 25, 50, 100]}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />
    </Box>
  );
}
