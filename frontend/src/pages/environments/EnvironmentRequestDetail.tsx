/**
 * EnvironmentRequestDetail — a single environment request: its fields, the
 * transitions this actor may make, an admin-only operating-group picker for
 * a draft new-environment request, and the Welcome Pack once fulfilled.
 *
 * Route: /environment-requests/:id
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchAllowedTransitions,
  fetchEnvironmentRequest,
  transitionEnvironmentRequest,
  updateEnvironmentRequest,
} from '../../store/environmentRequestSlice';
import { fetchUserGroups } from '../../store/userGroupSlice';
import WelcomePack from '../../components/environments/WelcomePack';
import DetailPageHeader from '../../components/layout/DetailPageHeader';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'info',
  fulfilled: 'success',
  rejected: 'error',
  cancelled: 'default',
};

// A sentinel distinct from every real group id (which start at 1), so the
// Select can represent "no group" as a real, selectable option — not just
// the picker's own initial/unset state. Without this an admin could ASSIGN
// a group but never CLEAR one back to null, even though the backend accepts
// an explicit `operations_group_id: null` PATCH.
const NO_GROUP = 'none' as const;
type GroupSelection = number | typeof NO_GROUP;

export default function EnvironmentRequestDetail() {
  const { id } = useParams<{ id: string }>();
  const requestId = Number(id);
  const dispatch = useDispatch<AppDispatch>();

  const { current, allowedTransitions, error } = useSelector(
    (state: RootState) => state.environmentRequest
  );
  const user = useSelector((state: RootState) => state.auth.user);
  const groups = useSelector((state: RootState) => state.userGroup.groups);

  const [actionError, setActionError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);

  const [groupId, setGroupId] = useState<GroupSelection>(NO_GROUP);
  const [groupError, setGroupError] = useState<string | null>(null);
  const [savingGroup, setSavingGroup] = useState(false);

  const load = () => {
    dispatch(fetchEnvironmentRequest(requestId));
    dispatch(fetchAllowedTransitions(requestId));
  };

  useEffect(() => {
    dispatch(fetchEnvironmentRequest(requestId));
    dispatch(fetchAllowedTransitions(requestId));
  }, [dispatch, requestId]);

  useEffect(() => {
    setGroupId(current?.operations_group_id ?? NO_GROUP);
  }, [current?.operations_group_id]);

  const isAdmin = user?.role === 'Admin' || user?.is_master_admin === true;

  // C1: an approved new-environment request with no operations group was
  // otherwise unrecoverable — fulfilment 409s forever on the null group,
  // the seeded template gives 'approved' exactly one outgoing edge
  // (approved -> fulfilled), and the request is never terminal so it sits in
  // the admin queue permanently. environment_request_service.update_request
  // now carves out operations_group_id ALONE, for an Admin, on a
  // new_environment request, from 'draft', 'submitted' OR 'approved' — so
  // the picker must offer all three, not just 'draft'.
  const showGroupPicker =
    isAdmin &&
    current?.kind === 'new_environment' &&
    (current?.status === 'draft' || current?.status === 'submitted' || current?.status === 'approved');

  useEffect(() => {
    if (showGroupPicker) dispatch(fetchUserGroups({}));
  }, [dispatch, showGroupPicker]);

  // Minor: the Select's `value` must always match one of its MenuItems, or
  // MUI logs an out-of-range warning. `groups` is fetched separately and can
  // still be empty/loading on first render, so the currently-assigned group
  // (if any) is added back in as a fallback option whenever `groups` hasn't
  // caught up with it yet — once the real fetch resolves and includes it,
  // this option is simply not added (no duplicate).
  const groupOptions =
    typeof groupId === 'number' && !groups.some((g) => g.id === groupId)
      ? [{ id: groupId, name: current?.operations_group_name ?? 'Loading…' }, ...groups]
      : groups;

  const handleTransition = async (toState: string) => {
    setTransitioning(true);
    setActionError(null);
    const result = await dispatch(transitionEnvironmentRequest({ id: requestId, toState }));
    setTransitioning(false);
    if (transitionEnvironmentRequest.rejected.match(result)) {
      // `result.payload`, never `result.error.message` — the 403/409 here
      // names WHY a transition was refused.
      setActionError(result.payload ?? 'Failed to update the request state');
      return;
    }
    setActionError(null);
    // The allowed set changes with the state — re-fetch both rather than
    // trust the slice's own transitionEnvironmentRequest.fulfilled handler,
    // which only updates `current`.
    load();
  };

  // Not `if (!groupId) return` any more (minor): that made a group
  // ASSIGNABLE but never CLEARABLE, even though the backend accepts an
  // explicit `operations_group_id: null` PATCH — NO_GROUP is a real,
  // selectable value now, so there is nothing left to early-return on.
  const handleGroupSave = async () => {
    setSavingGroup(true);
    setGroupError(null);
    const result = await dispatch(
      updateEnvironmentRequest({
        id: requestId,
        data: { operations_group_id: groupId === NO_GROUP ? null : groupId },
      })
    );
    setSavingGroup(false);
    if (updateEnvironmentRequest.rejected.match(result)) {
      setGroupError(result.payload ?? 'Failed to set the operations group');
      return;
    }
    setGroupError(null);
    dispatch(fetchEnvironmentRequest(requestId));
  };

  // I1: fetchEnvironmentRequest.pending now sets `loading` (it used to be
  // set ONLY by the list thunk, so a direct navigation here left `loading`
  // false and `!current` rendered an empty document — no skeleton, no error,
  // nothing). `error` is checked before `loading`/absence-of-`current`
  // generically, so a page that hasn't started fetching yet (the render that
  // happens before the mount effect has run) falls through to the skeleton
  // rather than flashing a spurious "failed to load" with nothing to retry.
  if (!current) {
    if (error) {
      return (
        <Box sx={{ p: 3 }}>
          <Alert
            severity="error"
            action={
              <Button color="inherit" size="small" onClick={load}>
                Retry
              </Button>
            }
          >
            {error}
          </Alert>
        </Box>
      );
    }
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  const target =
    current.kind === 'access'
      ? (current.environment_name ?? '—')
      : `${current.proposed_name ?? '—'} (new)`;

  return (
    <Box sx={{ p: 3 }}>
      <DetailPageHeader
        back={{ to: '/environment-requests', label: 'Environment Requests' }}
        title={target}
        status={
          <Chip label={current.status} size="small" color={STATUS_COLORS[current.status] ?? 'default'} />
        }
      />

      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack spacing={1.5} divider={<Divider />}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Kind
            </Typography>
            <Typography variant="body2">
              {current.kind === 'access' ? 'Access' : 'New environment'}
            </Typography>
          </Box>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Requested by
            </Typography>
            <Typography variant="body2">{current.requester_username ?? '—'}</Typography>
          </Box>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Justification
            </Typography>
            <Typography variant="body2">{current.justification}</Typography>
          </Box>
          {current.kind === 'access' ? (
            <Box>
              <Typography variant="overline" color="text.secondary">
                Environment
              </Typography>
              <Typography variant="body2">{current.environment_name ?? '—'}</Typography>
            </Box>
          ) : (
            <>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Proposed name
                </Typography>
                <Typography variant="body2">{current.proposed_name ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Tier
                </Typography>
                <Typography variant="body2">{current.tier_name ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Expiry
                </Typography>
                <Typography variant="body2">
                  {current.expires_at ? new Date(current.expires_at).toLocaleDateString() : '—'}
                </Typography>
              </Box>
            </>
          )}
          <Box>
            <Typography variant="overline" color="text.secondary">
              Needed by
            </Typography>
            <Typography variant="body2">
              {current.needed_by ? new Date(current.needed_by).toLocaleDateString() : '—'}
            </Typography>
          </Box>
          {/* M7: an access request's operating team comes from its TARGET
              environment, not the request row itself (operations_group_id
              is only ever set on a new_environment request) — this row
              always read "— no group" for an access request, which looks
              like a data problem rather than "not applicable here". */}
          {current.kind === 'new_environment' && (
            <Box>
              <Typography variant="overline" color="text.secondary">
                Operations group
              </Typography>
              <Typography variant="body2">{current.operations_group_name ?? '— no group'}</Typography>
            </Box>
          )}
        </Stack>
      </Paper>

      {showGroupPicker && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Operations Group
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            A new-environment request cannot be fulfilled until an operating team is assigned.
            Set it now, or fix it here later if it was missed before approval.
          </Typography>
          {groupError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {groupError}
            </Alert>
          )}
          <Stack direction="row" spacing={2} alignItems="center">
            <FormControl sx={{ minWidth: 240 }}>
              <InputLabel id="request-operations-group-label">Operations Group</InputLabel>
              <Select
                labelId="request-operations-group-label"
                label="Operations Group"
                value={groupId}
                onChange={(e) =>
                  setGroupId(e.target.value === NO_GROUP ? NO_GROUP : Number(e.target.value))
                }
              >
                <MenuItem value={NO_GROUP}>
                  <em>No group</em>
                </MenuItem>
                {groupOptions.map((g) => (
                  <MenuItem key={g.id} value={g.id}>
                    {g.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" onClick={handleGroupSave} disabled={savingGroup}>
              Save
            </Button>
          </Stack>
        </Paper>
      )}

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Actions
        </Typography>
        {actionError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {actionError}
          </Alert>
        )}
        {allowedTransitions.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No actions are available to you for this request right now.
          </Typography>
        ) : (
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {allowedTransitions.map((t) => (
              <Button
                key={t.to_state}
                variant="contained"
                disabled={transitioning}
                onClick={() => handleTransition(t.to_state)}
              >
                {t.label}
              </Button>
            ))}
          </Stack>
        )}
      </Paper>

      {current.status === 'fulfilled' && <WelcomePack requestId={requestId} />}
    </Box>
  );
}
