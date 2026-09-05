/**
 * RecordDecisionDialog — Phase 9 C3's "Record decision" dialog, opened from
 * GoNoGoTab's Decision History heading.
 *
 * C3 RECORDS A DECISION A HUMAN TOOK; IT REFUSES NOTHING beyond input
 * validation — see backend/tests/test_c3_records_never_refuses.py. Nothing
 * here disables Record on the strength of a blocker, a missing sign-off or
 * an empty perspective list; a `no_go` snapshot is exactly the case worth
 * recording alongside a `go` outcome and a dissenting sign-off.
 *
 * Two things this dialog deliberately shows but never sends:
 *
 * - The LIVE readiness verdict (`GET /releases/{id}/readiness`), fetched
 *   fresh every time the dialog opens, so the chair sees what they are
 *   about to sign over. The server freezes its OWN snapshot at record time
 *   by calling `release_readiness_service.evaluate` again
 *   (`go_no_go_service.record_decision`) — this preview can be a few
 *   seconds stale by the time Record is pressed, and that is fine, because
 *   `GoNoGoDecisionCreate` carries no snapshot fields for a client to send.
 * - The rollback-rehearsal answer to §2.11's "have you tested the
 *   rollback?" — read from the SAME verdict's `rehearsal_missing`/
 *   `rehearsal_stale` finding, mirroring `go_no_go_service.
 *   _rehearsal_state_from` exactly (scan warnings, then blockers — a tenant
 *   with `require_current_rehearsal=True` routes the finding to blockers,
 *   and scanning only warnings would misreport that tenant as having no
 *   rehearsal concern at all). Nothing here re-asks the question as a free
 *   text field for a human to retype what the system already computed.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';

import api from '../../services/api';
import { releaseService } from '../../services/releaseService';
import { useSharedList } from '../../hooks/useSharedList';
import type { AppDispatch, RootState } from '../../store';
import { fetchPerspectives, recordDecision } from '../../store/goNoGoSlice';
import { toDateTimeLocal } from '../../utils/datetime';
import type {
  GoNoGoConditionCreate,
  GoNoGoDecisionCreate,
  GoNoGoOutcome,
  GoNoGoSignoffCreate,
} from '../../types/goNoGo';
import type { ReleaseReadinessResponse } from '../../types/gateReadiness';

interface UserLite {
  id: number;
  username: string;
}

// `/tenant/users/lite` carries its own larger contract (default 1000, max
// 5000) precisely so a picker never silently drops a user — see
// docs/pagination.md and CLAUDE.md's note on `users/lite`. Asked for
// explicitly, module-level so `useSharedList` can safely keep it out of its
// effect deps (a fresh closure each render would re-fire the fetch).
const USERS_LITE_LIMIT = 1000;
const loadUsersLite = () =>
  api
    .get<UserLite[]>('/tenant/users/lite', { params: { limit: USERS_LITE_LIMIT } })
    .then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    }));

const OUTCOME_OPTIONS: { value: GoNoGoOutcome; label: string }[] = [
  { value: 'go', label: 'Go' },
  { value: 'conditional_go', label: 'Conditional Go' },
  { value: 'no_go', label: 'No Go' },
];

function outcomeLabel(value: string): string {
  return OUTCOME_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

// Mirrors `go_no_go_service._rehearsal_state_from` exactly: scan warnings
// before blockers, and only these two finding types are ever rehearsal
// findings. Do not evaluate a rehearsal question anywhere else — this is
// the one place the app answers it, the same way `environment_compliance_
// service.name_matches` is the one place a naming pattern is evaluated.
const REHEARSAL_FINDING_TYPES = new Set(['rehearsal_missing', 'rehearsal_stale']);

function rehearsalFindingType(readiness: ReleaseReadinessResponse | null): string | null {
  if (!readiness) return null;
  for (const finding of [...readiness.warnings, ...readiness.blockers]) {
    if (REHEARSAL_FINDING_TYPES.has(finding.type)) return finding.type;
  }
  return null;
}

function rehearsalAnswer(readiness: ReleaseReadinessResponse | null): string {
  const type = rehearsalFindingType(readiness);
  if (type === 'rehearsal_missing') return 'No — no rollback rehearsal has been recorded.';
  if (type === 'rehearsal_stale') return 'Not currently — the rehearsal on record is stale.';
  if (!readiness) return 'Unknown — the readiness check has not loaded.';
  return 'Yes — a current rollback rehearsal is on record.';
}

interface SignoffDraft {
  userId: number | null;
  verdict: GoNoGoOutcome;
  dissentNote: string;
}

interface ConditionDraft {
  key: number;
  text: string;
  ownerUserId: number | null;
  dueDate: string;
}

interface Props {
  releaseId: number;
  open: boolean;
  onClose: () => void;
  onRecorded: () => void;
}

export default function RecordDecisionDialog({ releaseId, open, onClose, onRecorded }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const perspectives = useSelector((s: RootState) => s.goNoGo.perspectives);
  const activePerspectives = perspectives.filter((p) => p.is_active);

  const { rows: users, truncated: usersTruncated } = useSharedList<UserLite>(
    'go-no-go-users-lite',
    loadUsersLite
  );

  const [outcome, setOutcome] = useState<GoNoGoOutcome>('go');
  const [rationale, setRationale] = useState('');
  const [decidedAt, setDecidedAt] = useState('');
  const [attendeeIds, setAttendeeIds] = useState<number[]>([]);
  const [signoffs, setSignoffs] = useState<Record<number, SignoffDraft>>({});
  const [conditions, setConditions] = useState<ConditionDraft[]>([]);
  const [conditionKeySeq, setConditionKeySeq] = useState(0);

  const [readiness, setReadiness] = useState<ReleaseReadinessResponse | null>(null);
  const [readinessFailed, setReadinessFailed] = useState(false);
  const [readinessLoading, setReadinessLoading] = useState(false);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-render, don't just mount: fetch fresh every time the dialog opens
  // (not once on the tab's own mount) so the verdict shown is the one about
  // to be frozen, and reset every field — a stale draft from a previous
  // open must never leak into this one.
  useEffect(() => {
    if (!open) return;
    setOutcome('go');
    setRationale('');
    setDecidedAt(toDateTimeLocal(new Date()));
    setAttendeeIds([]);
    setSignoffs({});
    setConditions([]);
    setError(null);

    dispatch(fetchPerspectives(false));

    setReadinessLoading(true);
    setReadinessFailed(false);
    releaseService
      .getReadiness(releaseId)
      .then((r) => setReadiness(r))
      .catch(() => {
        setReadiness(null);
        setReadinessFailed(true);
      })
      .finally(() => setReadinessLoading(false));
  }, [open, releaseId, dispatch]);

  const handleSignoffUserChange = (perspectiveId: number, user: UserLite | null) => {
    setSignoffs((prev) => ({
      ...prev,
      [perspectiveId]: {
        userId: user ? user.id : null,
        verdict: prev[perspectiveId]?.verdict ?? outcome,
        dissentNote: prev[perspectiveId]?.dissentNote ?? '',
      },
    }));
  };

  const handleSignoffVerdictChange = (perspectiveId: number, verdict: GoNoGoOutcome) => {
    setSignoffs((prev) => ({
      ...prev,
      [perspectiveId]: {
        userId: prev[perspectiveId]?.userId ?? null,
        verdict,
        dissentNote: prev[perspectiveId]?.dissentNote ?? '',
      },
    }));
  };

  const handleSignoffNoteChange = (perspectiveId: number, dissentNote: string) => {
    setSignoffs((prev) => ({
      ...prev,
      [perspectiveId]: {
        userId: prev[perspectiveId]?.userId ?? null,
        verdict: prev[perspectiveId]?.verdict ?? outcome,
        dissentNote,
      },
    }));
  };

  const handleAddCondition = () => {
    setConditions((prev) => [
      ...prev,
      { key: conditionKeySeq, text: '', ownerUserId: null, dueDate: '' },
    ]);
    setConditionKeySeq((n) => n + 1);
  };

  const handleRemoveCondition = (key: number) => {
    setConditions((prev) => prev.filter((c) => c.key !== key));
  };

  const updateCondition = (key: number, patch: Partial<ConditionDraft>) => {
    setConditions((prev) => prev.map((c) => (c.key === key ? { ...c, ...patch } : c)));
  };

  const canSave = Boolean(decidedAt) && rationale.trim() !== '';

  const handleRecord = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);

    // Only a row where a signatory was actually picked becomes a real
    // sign-off — an active perspective with nobody assigned yet is not the
    // same as a signed-off `go`, and the server would 422 on a null user_id
    // in any case. A perspective this tenant has since deactivated is
    // dropped from the payload too, whether or not it once had a draft.
    const signoffPayload: GoNoGoSignoffCreate[] = activePerspectives.flatMap((p) => {
      const draft = signoffs[p.id];
      if (!draft || draft.userId == null) return [];
      return [
        {
          perspective_id: p.id,
          user_id: draft.userId,
          verdict: draft.verdict,
          dissent_note: draft.dissentNote.trim() || null,
        },
      ];
    });

    const conditionPayload: GoNoGoConditionCreate[] = conditions.flatMap((c) => {
      const text = c.text.trim();
      if (!text) return [];
      return [
        {
          text,
          owner_user_id: c.ownerUserId,
          due_date: c.dueDate || null,
        },
      ];
    });

    // outcome, rationale, decided_at, attendees, signoffs, conditions — and
    // NOTHING else. The readiness snapshot above is display-only; sending a
    // client-supplied snapshot would be a client-supplied audit record.
    const payload: GoNoGoDecisionCreate = {
      outcome,
      rationale: rationale.trim(),
      decided_at: new Date(decidedAt).toISOString(),
      attendees: attendeeIds,
      signoffs: signoffPayload,
      conditions: conditionPayload,
    };

    const result = await dispatch(recordDecision({ releaseId, data: payload }));
    setSaving(false);
    if (recordDecision.rejected.match(result)) {
      setError(result.payload ?? 'Failed to record the decision');
      return;
    }
    onRecorded();
    onClose();
  };

  const handleClose = () => {
    if (saving) return;
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Record a Go/No-Go Decision</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
        <Alert severity="info">
          This records the decision a human took at this meeting. It refuses nothing on the
          strength of the readiness verdict below, a missing sign-off or an unmet condition — a
          No Go with open blockers is exactly the case worth recording.
        </Alert>
        {error && <Alert severity="error">{error}</Alert>}

        <Box>
          <Typography variant="subtitle1" gutterBottom>
            Readiness verdict you are about to freeze
          </Typography>
          {readinessLoading && (
            <Typography color="text.secondary">Loading the current readiness check…</Typography>
          )}
          {!readinessLoading && readinessFailed && (
            <Alert severity="warning">
              Could not load the current readiness check. Recording will still capture whatever
              the server can compute at that moment.
            </Alert>
          )}
          {!readinessLoading && !readinessFailed && readiness && (
            <Alert severity={readiness.blockers.length > 0 ? 'warning' : 'success'}>
              <Typography variant="body2" fontWeight="medium">
                {/* Gated on blockers.length === 0 && warnings.length === 0,
                    NOT on readiness.ok: `ok` is server-defined as
                    `len(blockers) == 0` alone (release_readiness_service.py)
                    and says nothing about warnings. Both C4 policy flags
                    default off, so a release with a missing/stale rehearsal
                    ordinarily reads ok=True with a `rehearsal_missing`
                    WARNING — gating this text on `ok` would print "No
                    blockers or warnings" directly above a rehearsal answer
                    saying otherwise, on the one screen that exists to show
                    the chair the true state before they sign. */}
                {readiness.blockers.length === 0 && readiness.warnings.length === 0
                  ? 'No blockers or warnings in the current verdict.'
                  : `${readiness.blockers.length} blocker(s), ${readiness.warnings.length} warning(s) in the current verdict.`}
              </Typography>
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                Rollback rehearsal tested? {rehearsalAnswer(readiness)}
              </Typography>
            </Alert>
          )}
        </Box>

        <TextField
          label="Outcome"
          select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as GoNoGoOutcome)}
          disabled={saving}
          fullWidth
        >
          {OUTCOME_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>

        <TextField
          label="Rationale"
          required
          multiline
          minRows={3}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          disabled={saving}
          fullWidth
        />

        <TextField
          label="Decided at"
          type="datetime-local"
          value={decidedAt}
          onChange={(e) => setDecidedAt(e.target.value)}
          disabled={saving}
          InputLabelProps={{ shrink: true }}
          fullWidth
        />

        <Autocomplete
          multiple
          options={users}
          getOptionLabel={(u) => u.username}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          value={users.filter((u) => attendeeIds.includes(u.id))}
          onChange={(_, v) => setAttendeeIds(v.map((u) => u.id))}
          disabled={saving}
          renderInput={(params) => (
            <TextField
              {...params}
              label="Attendees"
              helperText={usersTruncated ? 'The tenant user list is truncated.' : undefined}
            />
          )}
        />

        <Box>
          <Typography variant="subtitle1" gutterBottom>
            Sign-offs
          </Typography>
          {activePerspectives.length === 0 ? (
            <Alert severity="info">
              No active Go/No-Go perspectives are configured for this tenant. An admin can add
              one under Admin → Go/No-Go Perspectives — this decision can still be recorded
              without any sign-offs.
            </Alert>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Perspective</TableCell>
                    <TableCell>Signed off by</TableCell>
                    <TableCell>Verdict</TableCell>
                    <TableCell>Dissent note</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {activePerspectives.map((p) => {
                    const draft = signoffs[p.id];
                    return (
                      <TableRow key={p.id}>
                        <TableCell>{p.name}</TableCell>
                        <TableCell sx={{ minWidth: 180 }}>
                          <Autocomplete
                            options={users}
                            getOptionLabel={(u) => u.username}
                            isOptionEqualToValue={(a, b) => a.id === b.id}
                            value={users.find((u) => u.id === draft?.userId) ?? null}
                            onChange={(_, v) => handleSignoffUserChange(p.id, v)}
                            disabled={saving}
                            renderInput={(params) => (
                              <TextField {...params} label={`Sign-off — ${p.name}`} size="small" />
                            )}
                          />
                        </TableCell>
                        <TableCell sx={{ minWidth: 140 }}>
                          <TextField
                            select
                            size="small"
                            fullWidth
                            label={`Verdict — ${p.name}`}
                            value={draft?.verdict ?? outcome}
                            onChange={(e) =>
                              handleSignoffVerdictChange(p.id, e.target.value as GoNoGoOutcome)
                            }
                            disabled={saving}
                          >
                            {OUTCOME_OPTIONS.map((o) => (
                              <MenuItem key={o.value} value={o.value}>
                                {o.label}
                              </MenuItem>
                            ))}
                          </TextField>
                        </TableCell>
                        <TableCell sx={{ minWidth: 200 }}>
                          <TextField
                            size="small"
                            fullWidth
                            label={`Dissent note — ${p.name}`}
                            value={draft?.dissentNote ?? ''}
                            onChange={(e) => handleSignoffNoteChange(p.id, e.target.value)}
                            disabled={saving}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>

        <Box>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="subtitle1">Conditions</Typography>
            <Button size="small" startIcon={<AddIcon />} onClick={handleAddCondition} disabled={saving}>
              Add condition
            </Button>
          </Stack>
          {conditions.length === 0 ? (
            <Typography color="text.secondary" variant="body2">
              No conditions attached.
            </Typography>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Condition</TableCell>
                    <TableCell>Owner</TableCell>
                    <TableCell>Due date</TableCell>
                    <TableCell align="right" />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {conditions.map((c) => (
                    <TableRow key={c.key}>
                      <TableCell sx={{ minWidth: 220 }}>
                        <TextField
                          size="small"
                          fullWidth
                          label="Text"
                          value={c.text}
                          onChange={(e) => updateCondition(c.key, { text: e.target.value })}
                          disabled={saving}
                        />
                      </TableCell>
                      <TableCell sx={{ minWidth: 180 }}>
                        <Autocomplete
                          options={users}
                          getOptionLabel={(u) => u.username}
                          isOptionEqualToValue={(a, b) => a.id === b.id}
                          value={users.find((u) => u.id === c.ownerUserId) ?? null}
                          onChange={(_, v) =>
                            updateCondition(c.key, { ownerUserId: v ? v.id : null })
                          }
                          disabled={saving}
                          renderInput={(params) => (
                            <TextField {...params} label="Owner" size="small" />
                          )}
                        />
                      </TableCell>
                      <TableCell sx={{ minWidth: 160 }}>
                        <TextField
                          size="small"
                          fullWidth
                          type="date"
                          label="Due date"
                          value={c.dueDate}
                          onChange={(e) => updateCondition(c.key, { dueDate: e.target.value })}
                          disabled={saving}
                          InputLabelProps={{ shrink: true }}
                        />
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          aria-label={`Remove condition ${c.text || conditions.indexOf(c) + 1}`}
                          size="small"
                          onClick={() => handleRemoveCondition(c.key)}
                          disabled={saving}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleRecord} disabled={!canSave || saving}>
          {saving ? 'Recording…' : `Record ${outcomeLabel(outcome)}`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
