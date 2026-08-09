/**
 * The escalation worklist — what a named owner opens to see what they must
 * decide, and what everyone else opens to see that a clash they are party to
 * has been put to someone.
 *
 * A4 ADVISES; IT NEVER ACTS. Recording a decision writes four columns on the
 * escalation and touches neither booking — not its status, not its dates, not
 * its lifecycle. Acting on the decision stays with the owning team, through the
 * ordinary transition path, which for an A2 group booking moves the whole group
 * atomically. The advisory line on the page says so, because a queue of
 * decisions reads like a queue of things that will happen by themselves.
 *
 * EVERY ROW IS IDENTIFIED BY NAME. `booking_id` / `other_booking_id` are on the
 * response and are deliberately not rendered: a worklist is a list of
 * contentions the reader has never seen, so two integers identify nothing, and
 * `Booking #12` is the `#N` fallback this codebase does not do. The
 * environment and both project names travel with the row, batched server-side
 * by `contention_service.booking_labels`.
 *
 * `state` IS THE SERVER'S, NEVER RE-DERIVED. It is computed from `decided_at`
 * and `respond_by` against one clock per request, so a page cannot select a row
 * as open and render it expired — and a browser with a wrong clock cannot
 * manufacture a queue of expiries nobody can clear.
 */
import { useCallback, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';

import type { RootState } from '../../store';
import { contentionService } from '../../services/contentionService';
import { formatApiError } from '../../services/apiError';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { Escalation, EscalationState } from '../../types/contention';

const STATE_CHIP: Record<EscalationState, { label: string; color: 'info' | 'success' | 'warning' }> = {
  open: { label: 'Open', color: 'info' },
  answered: { label: 'Answered', color: 'success' },
  // A missed deadline, not a failure. Red here would read as "this booking is
  // in trouble", which is the claim A4 must never make.
  expired: { label: 'Expired', color: 'warning' },
};

type StateFilter = 'any' | EscalationState;

const STATE_FILTERS: { label: string; value: StateFilter }[] = [
  { label: 'All', value: 'any' },
  { label: 'Open', value: 'open' },
  { label: 'Answered', value: 'answered' },
  { label: 'Expired', value: 'expired' },
];

/**
 * "No filter" is spelled `any`, NEVER `all`.
 *
 * `all` is `buildParams`' own "no selection" sentinel and is dropped from the
 * request, so both "no filter" and a literal `all` selection would build
 * byte-identical params and the grid would never refetch — the hazard
 * `ScopeWindowsTable`'s `apiScopeWindow` exists to avoid, documented in
 * docs/pagination.md. The API agrees from its side: `GET
 * /contention-escalations` has no `all` value on the wire either, and OMISSION
 * is how you ask for everything.
 */
function stateParam(value: string | number | undefined): { state?: EscalationState } {
  return value === 'open' || value === 'answered' || value === 'expired'
    ? { state: value }
    : {};
}

/** One side of a contention, as a human reads it. */
function sideLabel(environmentName: string | null, projectName: string | null): string {
  const project = projectName ?? 'no linked project';
  return environmentName ? `${project} on ${environmentName}` : project;
}

export default function EscalationWorklist() {
  const user = useSelector((s: RootState) => s.auth.user);

  const [rows, setRows] = useState<Escalation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Drops a superseded response rather than letting a slow first page overwrite
  // a fast second one — the same guard ConflictsPanel carries.
  const generation = useRef(0);

  const [decideTarget, setDecideTarget] = useState<Escalation | null>(null);
  const [yieldsId, setYieldsId] = useState<number | ''>('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);

  const grid = useServerGrid({
    endpoint: 'contention-escalations',
    filterKeys: ['escalation_state'],
    onFetch: (params) => {
      const myGeneration = ++generation.current;
      setLoading(true);
      contentionService
        .list({
          limit: params.limit,
          offset: params.offset,
          sort_by: params.sort_by,
          sort_dir: params.sort_dir,
          ...stateParam(params.escalation_state),
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
          setLoadError(formatApiError(err, 'Failed to load escalations'));
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
  const stateFilter = grid.filters.escalation_state ?? 'any';

  /**
   * The named owner, or an Admin — mirroring `assert_may_decide`.
   *
   * THE ADMIN PATH IS NOT A CONVENIENCE. A4 ships no edit and no withdraw path
   * for an escalation, so a wrong owner or a deadline that has already passed
   * can only be resolved by somebody else being able to answer. Hiding this
   * from Admins would turn a recoverable mistake into a stuck one — B3b's
   * lesson, where gating solely on one person left a workflow permanently
   * blocked the day that person left.
   */
  const canDecide = useCallback(
    (row: Escalation): boolean =>
      Boolean(user) &&
      (user!.id === row.owner_user_id ||
        user!.role === 'Admin' ||
        user!.is_master_admin === true),
    [user]
  );

  const openDecide = (row: Escalation) => {
    setDecideTarget(row);
    setYieldsId(row.decision_yields_booking_id ?? '');
    setNotes(row.decision_notes ?? '');
    setDecideError(null);
  };

  const submitDecision = async () => {
    if (!decideTarget || yieldsId === '') return;
    setSaving(true);
    setDecideError(null);
    try {
      await contentionService.decide(decideTarget.id, {
        yields_booking_id: Number(yieldsId),
        // Empty is null, not "": a second decision passing null CLEARS the
        // first one's stated reason, which is `record_decision`'s documented
        // contract rather than an accident.
        notes: notes.trim() || null,
      });
      setDecideTarget(null);
      // Refetch rather than patching the row locally: `state` and the decision
      // are the server's answer, and this list is one windowed page.
      grid.refetch();
    } catch (err) {
      // formatApiError IN THIS CATCH — `contentionService.decide` has no slice
      // thunk in front of it to normalise the error, so `err.message` here is
      // the generic "Request failed with status code 400" and the server's
      // reason is in `response.data.detail`.
      setDecideError(formatApiError(err, 'Failed to record this decision'));
    } finally {
      setSaving(false);
    }
  };

  const columns: GridColDef<Escalation>[] = [
    {
      field: 'contention',
      headerName: 'Contention',
      flex: 1,
      minWidth: 260,
      // Composed from four columns; nothing single backs it, so it cannot be
      // whitelisted and a sortable header on it would 422 on click.
      sortable: false,
      renderCell: (params) => (
        <Box sx={{ py: 0.5 }}>
          <Typography variant="body2">
            {sideLabel(
              params.row.booking_environment_name,
              params.row.booking_project_name
            )}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            vs{' '}
            {sideLabel(
              params.row.other_booking_environment_name,
              params.row.other_booking_project_name
            )}
          </Typography>
          {!params.row.bookings_live && (
            <Typography variant="caption" color="text.secondary">
              No longer live — one or both bookings have closed or been removed
            </Typography>
          )}
        </Box>
      ),
    },
    {
      field: 'owner_username',
      headerName: 'To decide',
      width: 160,
      sortable: false, // joined from the user table, not a column on this row
      renderCell: (params) =>
        params.row.owner_username ?? 'Someone no longer in this tenant',
    },
    {
      field: 'escalated_by_username',
      headerName: 'Raised by',
      width: 150,
      sortable: false,
      renderCell: (params) =>
        params.row.escalated_by_username ?? 'Someone no longer in this tenant',
    },
    {
      field: 'respond_by',
      headerName: 'Respond by',
      width: 140,
      renderCell: (params) => new Date(params.row.respond_by).toLocaleDateString(),
    },
    {
      field: 'state',
      headerName: 'State',
      width: 120,
      // Computed server-side from two columns and a clock — there is no `state`
      // column to sort by.
      sortable: false,
      renderCell: (params) => (
        <Chip
          size="small"
          variant="outlined"
          label={STATE_CHIP[params.row.state].label}
          color={STATE_CHIP[params.row.state].color}
        />
      ),
    },
    {
      field: 'decided_at',
      headerName: 'Decision',
      flex: 1,
      minWidth: 200,
      renderCell: (params) =>
        params.row.decision_yields_booking_id === null ? (
          '—'
        ) : (
          <Box sx={{ py: 0.5 }}>
            <Typography variant="body2">
              {/* By name: which SIDE gives way, not which id. */}
              {params.row.decision_yields_booking_id === params.row.booking_id
                ? sideLabel(
                    params.row.booking_environment_name,
                    params.row.booking_project_name
                  )
                : sideLabel(
                    params.row.other_booking_environment_name,
                    params.row.other_booking_project_name
                  )}{' '}
              gives way
            </Typography>
            {params.row.decision_notes && (
              <Typography variant="caption" color="text.secondary">
                {params.row.decision_notes}
              </Typography>
            )}
            {params.row.decided_by_username && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                Recorded by {params.row.decided_by_username}
                {params.row.decided_at
                  ? ` on ${new Date(params.row.decided_at).toLocaleDateString()}`
                  : ''}
              </Typography>
            )}
          </Box>
        ),
    },
    {
      field: 'actions',
      headerName: '',
      width: 110,
      sortable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        canDecide(params.row) ? (
          <Button size="small" onClick={() => openDecide(params.row)}>
            Decide
          </Button>
        ) : null,
    },
  ];

  const target = decideTarget;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" fontWeight="bold" sx={{ mb: 1 }}>
        Contention Escalations
      </Typography>

      <Alert severity="info" sx={{ mb: 2 }} data-testid="worklist-advisory">
        These are contentions somebody has been asked to decide. Recording a decision moves
        nothing: it names which booking should give way and who said so. Acting on it stays
        with the team that owns the booking — and where that booking came from an environment
        group, moving it moves the whole group.
      </Alert>

      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {STATE_FILTERS.map((f) => (
          <Chip
            key={f.value}
            label={f.label}
            clickable
            component="button"
            color={stateFilter === f.value ? 'primary' : 'default'}
            variant={stateFilter === f.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('escalation_state', f.value)}
          />
        ))}
      </Box>

      {loadError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {loadError}
        </Alert>
      )}

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
        disableRowSelectionOnClick
      />

      <Dialog open={target !== null} onClose={() => setDecideTarget(null)} fullWidth maxWidth="sm">
        <DialogTitle>Record a decision</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            This records who should give way and why. It moves no booking — the team that owns
            it does that through the ordinary transition, and a booking made as part of an
            environment group moves with its group.
          </Typography>
          {decideError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {decideError}
            </Alert>
          )}
          {target && (
            <FormControl>
              <FormLabel id="yields-label">Which booking gives way?</FormLabel>
              <RadioGroup
                aria-labelledby="yields-label"
                value={yieldsId === '' ? '' : String(yieldsId)}
                onChange={(e) => setYieldsId(Number(e.target.value))}
              >
                {/* Offered BY NAME. A radio labelled `8002` is unanswerable. */}
                <FormControlLabel
                  value={String(target.booking_id)}
                  control={<Radio />}
                  label={sideLabel(
                    target.booking_environment_name,
                    target.booking_project_name
                  )}
                />
                <FormControlLabel
                  value={String(target.other_booking_id)}
                  control={<Radio />}
                  label={sideLabel(
                    target.other_booking_environment_name,
                    target.other_booking_project_name
                  )}
                />
              </RadioGroup>
            </FormControl>
          )}
          <TextField
            fullWidth
            size="small"
            multiline
            minRows={2}
            label="Notes"
            sx={{ mt: 2 }}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            helperText="Why. Clearing this on a later decision clears the reason on record."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDecideTarget(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={submitDecision}
            disabled={saving || yieldsId === ''}
          >
            Record decision
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
