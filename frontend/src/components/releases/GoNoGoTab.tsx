/**
 * GoNoGoTab — Phase 9 C3's Go/No-Go tab on the release detail page.
 *
 * Two things: the decision history (server-paged, sortable by `decided_at`/
 * `outcome` — the same whitelist `GO_NO_GO_SORTS` enforces server-side), and
 * the MOST RECENT decision ON THE LOADED PAGE's sign-offs, frozen snapshot
 * and conditions in full.
 *
 * That heading is deliberately NOT "the release's latest decision" (finding
 * 5 of the whole-branch review): `decisions` holds one server PAGE (default
 * 25), so past that many decisions, or with the grid re-sorted by outcome,
 * this panel would otherwise silently mean "newest on whatever page happens
 * to be loaded" while claiming to mean "newest, full stop" — and this is
 * the only place a condition can be closed, so a hidden true-latest would
 * make a condition unreachable through the product with no error at all.
 * Relabelling rather than fetching the true latest separately is the
 * deliberate choice here: `closeCondition.fulfilled` finds and patches a
 * decision IN `state.decisions` by id, so the "latest" shown here has to be
 * a member of that same array for the mark-met/reopen action beside a
 * condition to have anywhere to write its result.
 *
 * C3 RECORDS A DECISION A HUMAN TOOK; IT REFUSES NOTHING beyond input
 * validation — see backend/tests/test_c3_*.py. Nothing here disables a
 * control on the strength of any decision, condition or dissent.
 *
 * An outcome and its sign-offs are INDEPENDENT: a `go` decision can carry a
 * `no_go` sign-off with a dissent note, and recording that disagreement is
 * the whole point of a sign-off. Every sign-off renders exactly as recorded
 * — never filtered, hidden or summarised down to agreement with the
 * decision's own outcome.
 *
 * Recording a new decision is `RecordDecisionDialog`, opened from the
 * "Record decision" button beside the "Decision History" heading below. On
 * success it calls `grid.refetch()` — the same re-fetch-the-page pattern
 * `recordDecision`'s slice comment documents (no optimistic insert, since a
 * freshly recorded decision need not belong on whatever page/sort the grid
 * currently holds), reusing the grid's own current params rather than
 * re-deriving them.
 */
import { useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { AppDispatch, RootState } from '../../store';
import { closeCondition, fetchDecisions } from '../../store/goNoGoSlice';
import { formatBookingDateTime } from '../../utils/datetime';
import type { GoNoGoDecisionRead } from '../../types/goNoGo';
import RecordDecisionDialog from './RecordDecisionDialog';

interface Props {
  releaseId: number;
}

const OUTCOME_COLOR: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  go: 'success',
  conditional_go: 'warning',
  no_go: 'error',
};

const OUTCOME_LABEL: Record<string, string> = {
  go: 'Go',
  conditional_go: 'Conditional Go',
  no_go: 'No Go',
};

function outcomeLabel(value: string): string {
  return OUTCOME_LABEL[value] ?? value;
}

// Mirrors RollbackPanel.tsx's own REVERSIBILITY_COLOR/LABEL maps — a small,
// deliberate duplication (each component owns its own local vocabulary map,
// the established pattern in this codebase) rather than a shared import
// that would couple two unrelated features' rendering choices together.
const REVERSIBILITY_COLOR: Record<string, 'success' | 'warning' | 'error'> = {
  reversible: 'success',
  lossy: 'warning',
  irreversible: 'error',
};

const REVERSIBILITY_LABEL: Record<string, string> = {
  reversible: 'Reversible',
  lossy: 'Lossy',
  irreversible: 'Irreversible',
};

// The frozen sibling of RecordDecisionDialog.tsx's own `rehearsalAnswer`,
// which answers the question from a LIVE `ReleaseReadinessResponse`. This
// answers it from the decision's STORED `snapshot_rehearsal_state` — the
// finding type only, exactly as `go_no_go_service._rehearsal_state_from`
// emits it — so the wording is deliberately past-tense: this describes what
// was true at RECORD time, not now.
function rehearsalAnswerFromSnapshot(type: string | null): string {
  if (type === 'rehearsal_missing') {
    return 'No — no rollback rehearsal had been recorded at decision time.';
  }
  if (type === 'rehearsal_stale') {
    return 'Not currently — the rehearsal on record was stale at decision time.';
  }
  return 'Yes — a current rollback rehearsal was on record at decision time.';
}

// Copied from PirActionsTable.tsx's `formatDue` (which names this exact
// failure in its own comment) rather than shared, following that file's own
// precedent — MyWork.tsx and PirActionList.tsx each keep their own local
// copy too. `due_date` is a `sa.Date()` column, so the API emits a bare
// "2026-09-10"; `formatBookingDateTime` reads `getHours()` in LOCAL time on
// a value `new Date()` parses as UTC MIDNIGHT, so anyone west of Greenwich
// saw the day before.
function formatDue(due: string | null): string {
  if (!due) return '—';
  const d = new Date(due);
  return `${d.getUTCDate()} ${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })} ${d.getUTCFullYear()}`;
}

interface DecisionRow {
  id: number;
  decided_at: string;
  outcome: string;
  chaired_by_username: string;
  signoff_count: number;
  unmet_condition_count: number;
  snapshot_ok: boolean;
  snapshot_blocker_count: number;
  snapshot_warning_count: number;
}

// Only `decided_at`/`outcome` are backed by a single column on
// `GoNoGoDecision` (see `GO_NO_GO_SORTS` in `app/api/v1/releases.py`).
// `signoff_count` and `unmet_condition_count` are computed from the loaded
// page's own signoffs/conditions arrays and can never be whitelisted.
// eslint-disable-next-line react-refresh/only-export-components
export const goNoGoColumns: GridColDef<DecisionRow>[] = [
  {
    field: 'decided_at',
    headerName: 'Decided',
    width: 180,
    valueFormatter: (params) => formatBookingDateTime(params.value as string),
  },
  {
    field: 'outcome',
    headerName: 'Outcome',
    width: 150,
    renderCell: (params) => (
      <Chip
        size="small"
        label={outcomeLabel(params.value as string)}
        color={OUTCOME_COLOR[params.value as string] ?? 'default'}
      />
    ),
  },
  { field: 'chaired_by_username', headerName: 'Chaired by', width: 160, sortable: false },
  {
    field: 'signoff_count',
    headerName: 'Sign-offs',
    width: 110,
    sortable: false,
    align: 'center',
    headerAlign: 'center',
  },
  {
    field: 'unmet_condition_count',
    headerName: 'Unmet conditions',
    width: 160,
    sortable: false,
    align: 'center',
    headerAlign: 'center',
    renderCell: (params) =>
      (params.value as number) > 0 ? (
        <Chip size="small" color="warning" label={params.value as number} />
      ) : (
        <Typography variant="body2" color="text.secondary">
          0
        </Typography>
      ),
  },
  {
    field: 'snapshot_ok',
    headerName: 'Readiness at decision',
    width: 200,
    sortable: false,
    // `snapshot_ok` means "no BLOCKERS" only — it says nothing about
    // warnings, so a row with warnings but no blockers used to render the
    // identical "Was ready" chip as a row with neither. Finding 2 of the
    // whole-branch review: surface the frozen counts, here as well as on
    // the detail panel below.
    renderCell: (params) => {
      const { snapshot_blocker_count: blockers, snapshot_warning_count: warnings } = params.row;
      if (blockers > 0) {
        return (
          <Chip
            size="small"
            variant="filled"
            color="error"
            label={`${blockers} blocker${blockers === 1 ? '' : 's'}`}
          />
        );
      }
      if (warnings > 0) {
        return (
          <Chip
            size="small"
            variant="outlined"
            color="warning"
            label={`Ready, ${warnings} warning${warnings === 1 ? '' : 's'}`}
          />
        );
      }
      return <Chip size="small" variant="outlined" color="success" label="Was ready" />;
    },
  },
];

export default function GoNoGoTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const user = useSelector((s: RootState) => s.auth.user);
  // listLoading/listError are the ONLY state this grid and its Alert read —
  // fetchPerspectives (dispatched by the record-decision dialog on mount)
  // and closeCondition each write to their own, separate slot, so neither
  // can spin this grid or falsely announce a failed list load (finding 6).
  const { decisions, total, listLoading, listError, conditionError } = useSelector(
    (s: RootState) => s.goNoGo
  );
  const [dialogOpen, setDialogOpen] = useState(false);

  const grid = useServerGrid({
    endpoint: 'go-no-go',
    filterKeys: [],
    onFetch: (params) =>
      dispatch(
        fetchDecisions({
          releaseId,
          params: {
            limit: params.limit,
            offset: params.offset,
            sort_by: params.sort_by as 'decided_at' | 'outcome',
            sort_dir: params.sort_dir,
          },
        })
      ),
    total,
    totalPending: listLoading,
  });

  const rows: DecisionRow[] = useMemo(
    () =>
      decisions.map((d) => ({
        id: d.id,
        decided_at: d.decided_at,
        outcome: d.outcome,
        chaired_by_username: d.chaired_by_username ?? '—',
        signoff_count: d.signoffs.length,
        unmet_condition_count: d.unmet_condition_count,
        snapshot_ok: d.snapshot_ok,
        snapshot_blocker_count: d.snapshot_blockers.length,
        snapshot_warning_count: d.snapshot_warnings.length,
      })),
    [decisions]
  );

  const latest: GoNoGoDecisionRead | null = useMemo(() => {
    if (decisions.length === 0) return null;
    return decisions.reduce((acc, d) =>
      new Date(d.decided_at).getTime() > new Date(acc.decided_at).getTime() ? d : acc
    );
  }, [decisions]);

  const handleToggleCondition = (conditionId: number, currentlyMet: boolean) => {
    dispatch(closeCondition({ conditionId, met: !currentlyMet }));
  };

  return (
    <Box>
      {listError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {listError}
        </Alert>
      )}

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="h6">Decision History</Typography>
        <Button variant="contained" onClick={() => setDialogOpen(true)}>
          Record decision
        </Button>
      </Stack>

      <Paper variant="outlined" sx={{ mb: 3 }}>
        <DataTable<DecisionRow>
          storageKey="release-go-no-go"
          userId={user?.id ?? 'guest'}
          // The list is empty for one of two very different reasons — no
          // decisions have been recorded, or the fetch never came back at
          // all. Naming "no decisions" here when it's actually the latter
          // states as fact something the app does not know; the Alert
          // above already says what went wrong. Driven by `listError` only
          // — a failed closeCondition or perspective fetch must never flip
          // this to the load-failure message (finding 6).
          emptyMessage={
            listError
              ? 'Unable to load go/no-go decisions.'
              : 'No go/no-go decisions have been recorded for this release yet.'
          }
          rows={rows}
          columns={goNoGoColumns}
          autoHeight
          loading={listLoading}
          rowCount={total}
          paginationMode="server"
          sortingMode="server"
          disableColumnFilter
          paginationModel={grid.paginationModel}
          onPaginationModelChange={grid.onPaginationModelChange}
          sortModel={grid.sortModel}
          onSortModelChange={grid.onSortModelChange}
          pageSizeOptions={[10, 25, 50, 100]}
        />
      </Paper>

      {latest && (
        <Box>
          <Typography variant="h6" gutterBottom>
            Most recent decision on this page — {outcomeLabel(latest.outcome)} (
            {formatBookingDateTime(latest.decided_at)})
          </Typography>
          {latest.rationale && (
            <Typography color="text.secondary" sx={{ mb: 2, whiteSpace: 'pre-wrap' }}>
              {latest.rationale}
            </Typography>
          )}

          <Typography variant="body2" sx={{ mb: 2 }}>
            Attendees:{' '}
            {latest.attendee_usernames.length > 0
              ? latest.attendee_usernames.join(', ')
              : 'None recorded'}
          </Typography>

          <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
            <Typography variant="subtitle1" gutterBottom>
              Readiness snapshot frozen at this decision
            </Typography>
            {/* §4.1's own caveat, made visible: the snapshot is of the
                moment this decision was RECORDED, never of `decided_at`
                above — a backdated meeting still freezes the verdict as it
                stood when someone sat down to record it. */}
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Captured when this decision was recorded, not at the meeting date above — a
              backdated meeting still freezes the verdict as it stood at record time.
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
              <Chip
                size="small"
                variant={latest.snapshot_blockers.length === 0 ? 'outlined' : 'filled'}
                color={latest.snapshot_blockers.length === 0 ? 'success' : 'error'}
                label={
                  latest.snapshot_blockers.length === 0
                    ? 'No blockers'
                    : `${latest.snapshot_blockers.length} blocker${latest.snapshot_blockers.length === 1 ? '' : 's'}`
                }
              />
              <Chip
                size="small"
                variant="outlined"
                color={latest.snapshot_warnings.length === 0 ? 'default' : 'warning'}
                label={
                  latest.snapshot_warnings.length === 0
                    ? 'No warnings'
                    : `${latest.snapshot_warnings.length} warning${latest.snapshot_warnings.length === 1 ? '' : 's'}`
                }
              />
              {latest.snapshot_reversibility && (
                <Chip
                  size="small"
                  color={REVERSIBILITY_COLOR[latest.snapshot_reversibility] ?? 'default'}
                  label={`Reversibility: ${REVERSIBILITY_LABEL[latest.snapshot_reversibility] ?? latest.snapshot_reversibility}`}
                />
              )}
            </Stack>
            <Typography variant="body2" sx={{ mb: 1 }}>
              Rollback rehearsal: {rehearsalAnswerFromSnapshot(latest.snapshot_rehearsal_state)}
            </Typography>
            {latest.snapshot_blockers.length > 0 && (
              <Box sx={{ mb: 1 }}>
                <Typography variant="body2" fontWeight="bold">
                  Blockers at decision time
                </Typography>
                {latest.snapshot_blockers.map((b, i) => (
                  <Typography key={i} variant="body2" color="text.secondary">
                    • {b.detail ?? b.type}
                  </Typography>
                ))}
              </Box>
            )}
            {latest.snapshot_warnings.length > 0 && (
              <Box>
                <Typography variant="body2" fontWeight="bold">
                  Warnings at decision time
                </Typography>
                {latest.snapshot_warnings.map((w, i) => (
                  <Typography key={i} variant="body2" color="text.secondary">
                    • {w.detail ?? w.type}
                  </Typography>
                ))}
              </Box>
            )}
          </Paper>

          {conditionError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {conditionError}
            </Alert>
          )}

          <Typography variant="subtitle1" gutterBottom>
            Sign-offs
          </Typography>
          <TableContainer sx={{ mb: 3 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Perspective</TableCell>
                  <TableCell>Sign-off by</TableCell>
                  <TableCell>Verdict</TableCell>
                  <TableCell>Dissent note</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {/* Every sign-off is rendered here regardless of whether its
                    verdict agrees with `latest.outcome` above — a dissenting
                    sign-off (e.g. a `no_go` verdict on a `go` decision) must
                    never be hidden or reconciled away; it IS the record of
                    the disagreement. */}
                {latest.signoffs.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>{s.perspective_name ?? `#${s.perspective_id}`}</TableCell>
                    <TableCell>{s.username ?? `#${s.user_id}`}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={outcomeLabel(s.verdict)}
                        color={OUTCOME_COLOR[s.verdict] ?? 'default'}
                      />
                    </TableCell>
                    <TableCell>{s.dissent_note ?? '—'}</TableCell>
                  </TableRow>
                ))}
                {latest.signoffs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Typography color="text.secondary">No sign-offs recorded.</Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>

          <Typography variant="subtitle1" gutterBottom>
            Conditions
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Condition</TableCell>
                  <TableCell>Owner</TableCell>
                  <TableCell>Due date</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {latest.conditions.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{c.text}</TableCell>
                    <TableCell>{c.owner_username ?? '—'}</TableCell>
                    <TableCell>{formatDue(c.due_date)}</TableCell>
                    <TableCell>
                      {c.met_at ? (
                        <Chip
                          size="small"
                          color="success"
                          label={c.met_by_username ? `Met by ${c.met_by_username}` : 'Met'}
                        />
                      ) : (
                        <Chip size="small" color="warning" variant="outlined" label="Unmet" />
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        onClick={() => handleToggleCondition(c.id, c.met_at !== null)}
                      >
                        {c.met_at ? 'Reopen' : 'Mark met'}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {latest.conditions.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <Typography color="text.secondary">
                        No conditions attached to this decision.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {!latest && !listLoading && !listError && (
        <Typography color="text.secondary">
          Record a decision to see its sign-offs and conditions here.
        </Typography>
      )}

      <RecordDecisionDialog
        releaseId={releaseId}
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onRecorded={() => grid.refetch()}
      />
    </Box>
  );
}
