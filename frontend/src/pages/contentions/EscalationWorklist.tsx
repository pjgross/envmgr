/**
 * The escalation worklist — what a named owner opens to see what they must
 * decide, and what everyone else opens to see that a clash they are party to
 * has been put to someone.
 *
 * SO IT FILTERS BY STATE **AND BY OWNER**, both on the wire. Everyone's queue
 * is not "what I must decide": with sixty escalations in a tenant the named
 * owner would page through everybody else's rows hunting their own username
 * down the *To decide* column, which is the one journey this page exists for.
 * Neither filter is a permission — the whole worklist stays readable, and who
 * may ANSWER a row is the Decide control's question.
 *
 * A4 ADVISES; IT NEVER ACTS. Recording a decision writes four columns on the
 * escalation and touches neither booking — not its status, not its dates, not
 * its lifecycle. Acting on the decision stays with the owning team, through the
 * ordinary transition path. The advisory line on the page says so, because a
 * queue of decisions reads like a queue of things that will happen by
 * themselves.
 *
 * AND WHERE A SIDE IS AN A2 GROUP BOOKING, THE ROW AND THE OPTION SAY SO, BY
 * NAME. That transition moves every member of the group atomically, so a
 * decision naming one member is a decision about all of them — and this page,
 * not the booking page, is where the decision is actually made. It is said per
 * row and per radio option rather than as a general caution on the page: a
 * hedge that fires on every row, most of which have no group, tells the reader
 * nothing about the one in front of them.
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
import PageHeader from '../../components/layout/PageHeader';

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

type OwnerFilter = 'anyone' | 'me';

const OWNER_FILTERS: { label: string; value: OwnerFilter }[] = [
  { label: 'Anyone', value: 'anyone' },
  { label: 'Mine', value: 'me' },
];

/**
 * THE FILTER THIS PAGE WAS BUILT FOR. Its stated purpose is what a NAMED OWNER
 * opens to see what they must decide, and with sixty escalations across a
 * tenant that is unreachable without narrowing: the decider pages through
 * everyone else's rows hunting their own username in the *To decide* column.
 *
 * A FILTER, NOT A PERMISSION. The whole worklist stays readable — a clash you
 * are party to being put to somebody is a fact you are entitled to see — and
 * who may ANSWER a row is the Decide control's question, not this one.
 *
 * Narrowed to `owner_user_id` ON THE WIRE, never by filtering the page in the
 * browser: `rows` is one windowed page, so a browser-side narrowing would
 * filter the page and leave the total describing the set.
 *
 * "Everyone's" is spelled `anyone`, never `all`, for the same reason `stateParam`
 * spells it `any`: `all` is `buildParams`' own "no selection" sentinel, so both
 * states would build byte-identical params and the grid would never refetch.
 */
function ownerParam(
  value: string | number | undefined,
  userId: number | undefined
): { owner_user_id?: number } {
  return value === 'me' && userId !== undefined ? { owner_user_id: userId } : {};
}

/** One side of a contention, as a human reads it. */
function sideLabel(environmentName: string | null, projectName: string | null): string {
  const project = projectName ?? 'no linked project';
  return environmentName ? `${project} on ${environmentName}` : project;
}

/**
 * WHAT MOVING THAT BOOKING WOULD ACTUALLY MOVE — said about THIS row, never in
 * general.
 *
 * A2 transitions a group booking ATOMICALLY: every member moves or none does.
 * So a decision naming one member of a five-environment group booking is a
 * decision about all five, and a line reading "Payments Rebuild on Staging
 * gives way" describes a consequence that is not the one that happens. This
 * page is where the decision is MADE, which makes the misreading worse here
 * than anywhere else A4 renders.
 *
 * Returns null for the ordinary case — no group, nothing to say. A blanket
 * advisory covering every row instead ("…and where that booking came from a
 * group…") hedges on the majority of rows that have no group and therefore
 * tells a reader nothing about the row in front of them; that is exactly what
 * this replaces. Wording matches `ContentionVerdict`'s group note, because a
 * reader who sees both should not have to work out whether they mean the same
 * thing.
 */
function groupNote(groupName: string | null, subject = 'that booking'): string | null {
  return groupName
    ? `Moving ${subject} moves every environment in ${groupName} — the group was booked as one unit and transitions together.`
    : null;
}

/**
 * A radio option in the Decide dialog: the side by name, and — where that side
 * is one member of a group booking — what choosing it would move.
 *
 * The note is part of the OPTION rather than a line under the question,
 * because the reader is choosing BETWEEN the two sides and only one of them
 * may be a group booking. It is the accessible name of the radio too, which is
 * what makes "I did not know that moved five environments" untrue by
 * construction.
 */
function optionLabel(label: string, groupName: string | null) {
  const note = groupNote(groupName, 'this booking');
  return (
    <Box sx={{ py: 0.5 }}>
      <Typography variant="body2">{label}</Typography>
      {note && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {note}
        </Typography>
      )}
    </Box>
  );
}

/** The group of whichever side a booking id names, or null. */
function groupNameOf(row: Escalation, bookingId: number): string | null {
  return bookingId === row.booking_id
    ? row.booking_group_name
    : row.other_booking_group_name;
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
    filterKeys: ['escalation_state', 'escalation_owner'],
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
          ...ownerParam(params.escalation_owner, user?.id),
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
  const ownerFilter = grid.filters.escalation_owner ?? 'anyone';

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
      // Composed from five fields on the row (both sides' project and
      // environment names, plus liveness); nothing single backs it, so it cannot be
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
      renderCell: (params) => {
        const row = params.row;
        const yields = row.decision_yields_booking_id;
        if (yields === null) return '—';
        // WHAT ACTING ON THIS DECISION WOULD ACTUALLY MOVE. The line below
        // names one environment; if that booking was made as one member of an
        // A2 group, the ordinary transition moves every member. Per row and by
        // name — a general hedge on the page says nothing about this row.
        const note = groupNote(groupNameOf(row, yields));
        return (
          <Box sx={{ py: 0.5 }}>
            <Typography variant="body2">
              {/* By name: which SIDE gives way, not which id. */}
              {yields === row.booking_id
                ? sideLabel(row.booking_environment_name, row.booking_project_name)
                : sideLabel(
                    row.other_booking_environment_name,
                    row.other_booking_project_name
                  )}{' '}
              gives way
            </Typography>
            {note && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                {note}
              </Typography>
            )}
            {row.decision_notes && (
              <Typography variant="caption" color="text.secondary">
                {row.decision_notes}
              </Typography>
            )}
            {row.decided_by_username && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                Recorded by {row.decided_by_username}
                {row.decided_at
                  ? ` on ${new Date(row.decided_at).toLocaleDateString()}`
                  : ''}
              </Typography>
            )}
          </Box>
        );
      },
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
      <PageHeader title="Contention escalations" />

      {/* WHAT THIS PAGE DOES, in general — and NOTHING about groups, which is
          a fact about a particular row and is now said on the rows and the
          options it applies to. A blanket "…and where that booking came from a
          group, moving it moves the whole group" fires on every row, most of
          which have no group, so it hedges instead of telling the reader
          anything about what is in front of them. */}
      <Alert severity="info" sx={{ mb: 2 }} data-testid="worklist-advisory">
        These are contentions somebody has been asked to decide. Recording a decision moves
        nothing: it names which booking should give way and who said so. Acting on it stays
        with the team that owns the booking.
      </Alert>

      <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap', alignItems: 'center' }}>
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
            onClick={() => grid.setFilter('escalation_state', f.value)}
          />
        ))}
      </Box>

      {/* WHOSE QUEUE. The page's stated purpose is what a named owner opens to
          see what they must decide, and everyone's queue is not that — with
          sixty escalations in a tenant the decider hunts their own username
          down the *To decide* column. Narrowed on the wire, never in the
          browser: `rows` is one windowed page. */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
          To decide
        </Typography>
        {OWNER_FILTERS.map((f) => (
          <Chip
            key={f.value}
            label={f.label}
            clickable
            component="button"
            color={ownerFilter === f.value ? 'primary' : 'default'}
            variant={ownerFilter === f.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('escalation_owner', f.value)}
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
            it does that through the ordinary transition.
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
                {/* Offered BY NAME. A radio labelled `8002` is unanswerable.
                    AND WITH WHAT CHOOSING IT WOULD MOVE: an option reading
                    "Payments Rebuild on Staging" for one member of a
                    five-environment A2 group booking asks the reader to choose
                    a consequence they have not been told about. */}
                <FormControlLabel
                  value={String(target.booking_id)}
                  control={<Radio />}
                  label={optionLabel(
                    sideLabel(
                      target.booking_environment_name,
                      target.booking_project_name
                    ),
                    target.booking_group_name
                  )}
                />
                <FormControlLabel
                  value={String(target.other_booking_id)}
                  control={<Radio />}
                  label={optionLabel(
                    sideLabel(
                      target.other_booking_environment_name,
                      target.other_booking_project_name
                    ),
                    target.other_booking_group_name
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
