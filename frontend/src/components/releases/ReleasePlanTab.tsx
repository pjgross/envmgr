/**
 * ReleasePlanTab — Gates & Test Phases tab.
 *
 * Layout:
 *   - PhaseGanttEditor (read-only CSS Gantt; drag-and-drop deferred)
 *   - PhasesTable (editable; drives Gantt date updates)
 *   - GatesTable (create + gate decision)
 */
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Box, Divider, Typography } from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchPhases, fetchGates } from '../../store/releaseSlice';
import PhaseGanttEditor from './PhaseGanttEditor';
import PhasesTable from './PhasesTable';
import GatesTable from './GatesTable';

interface Props {
  releaseId: number;
}

export default function ReleasePlanTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const phases = useSelector((s: RootState) => s.release.phases);
  const gates = useSelector((s: RootState) => s.release.gates);
  const release = useSelector((s: RootState) => s.release.detail);

  useEffect(() => {
    dispatch(fetchPhases(releaseId));
    dispatch(fetchGates(releaseId));
  }, [dispatch, releaseId]);

  const refresh = () => {
    dispatch(fetchGates(releaseId));
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="subtitle1" fontWeight="medium" sx={{ mb: 1 }}>
          Phase Timeline
        </Typography>
        <PhaseGanttEditor
          phases={phases}
          releaseTargetDate={release?.target_date}
        />
      </Box>

      <Divider />

      <PhasesTable releaseId={releaseId} phases={phases} />

      <Divider />

      <GatesTable
        releaseId={releaseId}
        gates={gates}
        onRefresh={refresh}
      />
    </Box>
  );
}
