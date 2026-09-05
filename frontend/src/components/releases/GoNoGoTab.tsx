/**
 * GoNoGoTab — Phase 9 C3's Go/No-Go tab on the release detail page.
 *
 * Two things: the decision history (server-paged, sortable by `decided_at`/
 * `outcome` — the same whitelist `GO_NO_GO_SORTS` enforces server-side), and
 * the LATEST decision's sign-offs and conditions in full.
 *
 * "Latest" means the decision with the greatest `decided_at` among the
 * loaded page, independent of whatever the history grid happens to be
 * sorted by right now — sorting the grid by outcome must not change which
 * decision this panel calls the latest one.
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
 * Recording a new decision is Task 9's dialog — deliberately NOT built here.
 * TODO(Task 9): add a "Record decision" action to this tab (e.g. beside the
 * "Decision History" heading below) that opens `RecordGoNoGoDialog` and
 * calls `dispatch(fetchDecisions(...))` again on success — the same
 * re-fetch-the-page pattern `recordDecision`'s slice comment already
 * documents, since a freshly recorded decision need not belong on whatever
 * page/sort the grid currently holds.
 */
import { useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
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

interface DecisionRow {
  id: number;
  decided_at: string;
  outcome: string;
  chaired_by_username: string;
  signoff_count: number;
  unmet_condition_count: number;
  snapshot_ok: boolean;
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
    width: 180,
    sortable: false,
    renderCell: (params) => (
      <Chip
        size="small"
        variant={params.value ? 'outlined' : 'filled'}
        color={params.value ? 'success' : 'error'}
        label={params.value ? 'Was ready' : 'Had findings'}
      />
    ),
  },
];

export default function GoNoGoTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const user = useSelector((s: RootState) => s.auth.user);
  const { decisions, total, loading, error } = useSelector((s: RootState) => s.goNoGo);

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
    totalPending: loading,
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
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Typography variant="h6" gutterBottom>
        Decision History
      </Typography>

      <Paper variant="outlined" sx={{ mb: 3 }}>
        <DataTable<DecisionRow>
          storageKey="release-go-no-go"
          userId={user?.id ?? 'guest'}
          // The list is empty for one of two very different reasons — no
          // decisions have been recorded, or the fetch never came back at
          // all. Naming "no decisions" here when it's actually the latter
          // states as fact something the app does not know; the Alert
          // above already says what went wrong.
          emptyMessage={
            error
              ? 'Unable to load go/no-go decisions.'
              : 'No go/no-go decisions have been recorded for this release yet.'
          }
          rows={rows}
          columns={goNoGoColumns}
          autoHeight
          loading={loading}
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
            Latest decision — {outcomeLabel(latest.outcome)} ({formatBookingDateTime(latest.decided_at)})
          </Typography>
          {latest.rationale && (
            <Typography color="text.secondary" sx={{ mb: 2, whiteSpace: 'pre-wrap' }}>
              {latest.rationale}
            </Typography>
          )}

          <Typography variant="subtitle1" gutterBottom>
            Sign-offs
          </Typography>
          <TableContainer sx={{ mb: 3 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
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
                    <TableCell colSpan={3}>
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
                    <TableCell>
                      {c.due_date ? formatBookingDateTime(c.due_date) : '—'}
                    </TableCell>
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

      {!latest && !loading && !error && (
        <Typography color="text.secondary">
          Record a decision to see its sign-offs and conditions here.
        </Typography>
      )}
    </Box>
  );
}
