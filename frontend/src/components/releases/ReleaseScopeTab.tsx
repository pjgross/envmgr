/**
 * ReleaseScopeTab — manage the scope items (release changes) for this release.
 *
 * "Group by Epic" toggle is disabled — enabled in sub-project 3.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Box, Button, FormControlLabel, Switch, Tooltip, Typography } from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseChanges } from '../../store/releaseSlice';
import ScopeTable from './ScopeTable';
import ScopeImportDialog from './ScopeImportDialog';

interface Props {
  releaseId: number;
}

export default function ReleaseScopeTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { changes, loading } = useSelector((s: RootState) => ({
    changes: s.release.changes,
    loading: s.release.loading,
  }));

  const [importOpen, setImportOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchReleaseChanges(releaseId));
  }, [dispatch, releaseId]);

  const handleImported = () => {
    dispatch(fetchReleaseChanges(releaseId));
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="subtitle1" fontWeight="medium">
          Release Scope
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            size="small"
            startIcon={<UploadFileIcon />}
            onClick={() => setImportOpen(true)}
          >
            Import from spreadsheet
          </Button>
          <Tooltip title="Group by Epic is available in Sub-Project 3">
            <span>
              <FormControlLabel
                control={<Switch disabled />}
                label="Group by Epic"
              />
            </span>
          </Tooltip>
        </Box>
      </Box>

      <ScopeTable releaseId={releaseId} changes={changes} loading={loading} />

      <ScopeImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        releaseId={releaseId}
        onImported={handleImported}
      />
    </Box>
  );
}
