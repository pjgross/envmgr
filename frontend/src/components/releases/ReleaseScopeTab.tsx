/**
 * ReleaseScopeTab — manage the scope items (release changes) for this release.
 *
 * "Group by Epic" toggle is disabled — enabled in sub-project 3.
 */
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Box, FormControlLabel, Switch, Tooltip, Typography } from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseChanges } from '../../store/releaseSlice';
import ScopeTable from './ScopeTable';

interface Props {
  releaseId: number;
}

export default function ReleaseScopeTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { changes, loading } = useSelector((s: RootState) => ({
    changes: s.release.changes,
    loading: s.release.loading,
  }));

  useEffect(() => {
    dispatch(fetchReleaseChanges(releaseId));
  }, [dispatch, releaseId]);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="subtitle1" fontWeight="medium">
          Release Scope
        </Typography>
        <Tooltip title="Group by Epic is available in Sub-Project 3">
          <span>
            <FormControlLabel
              control={<Switch disabled />}
              label="Group by Epic"
            />
          </span>
        </Tooltip>
      </Box>

      <ScopeTable releaseId={releaseId} changes={changes} loading={loading} />
    </Box>
  );
}
