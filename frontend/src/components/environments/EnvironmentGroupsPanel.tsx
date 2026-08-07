/**
 * EnvironmentGroupsPanel — "Member of", the environment-direction read of
 * group membership (GET /environments/{id}/groups via
 * fetchGroupsForEnvironment). Without this line there is no way to discover,
 * from an environment, why it got booked as part of a group.
 *
 * Group names come from the member rows themselves (`m.group_name`), never
 * resolved against a separately fetched groups collection — `state
 * .environmentGroup.groups` is the admin list's own server-paged slice, may
 * hold a stale name for the same id, and may not be loaded on this page at
 * all. Same reasoning as EnvironmentProjectsPanel and docs/pagination.md.
 *
 * `fetchGroupsForEnvironment` is a read thunk that sets `state.error` on
 * failure but shares no `loading` flag with this panel — `state
 * .environmentGroup.loading` is set only by the LIST thunk
 * (`fetchEnvironmentGroups`), which this panel never dispatches. Keying a
 * skeleton on that flag renders a permanently blank panel, the exact bug a
 * previous sub-project shipped from a `loading` flag only the list thunk
 * set. Loading is tracked locally instead.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Chip, Paper, Skeleton, Typography } from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { fetchGroupsForEnvironment } from '../../store/environmentGroupSlice';

interface EnvironmentGroupsPanelProps {
  environmentId: number;
}

export default function EnvironmentGroupsPanel({ environmentId }: EnvironmentGroupsPanelProps) {
  const dispatch = useDispatch<AppDispatch>();
  const members = useSelector((state: RootState) => state.environmentGroup.members);
  const error = useSelector((state: RootState) => state.environmentGroup.error);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    dispatch(fetchGroupsForEnvironment(environmentId)).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [dispatch, environmentId]);

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Member of
      </Typography>

      {loading && <Skeleton variant="text" width={200} />}

      {!loading && error && <Alert severity="error">{error}</Alert>}

      {!loading && !error && members.length === 0 && (
        <Typography color="text.secondary">
          Not a member of any environment group.
        </Typography>
      )}

      {!loading && !error && members.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
          {members.map((m) => (
            <Chip
              key={m.id}
              label={m.group_name}
              component={RouterLink}
              to={`/tenant/environment-groups/${m.group_id}`}
              clickable
              size="small"
            />
          ))}
        </Box>
      )}
    </Paper>
  );
}
