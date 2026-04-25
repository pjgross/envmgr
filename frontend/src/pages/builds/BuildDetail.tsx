import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box, Chip, CircularProgress, Divider, Paper, Stack, Typography,
} from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchBuildById } from '../../store/buildSlice';
import { fetchDeploymentsByBuild } from '../../store/deploymentSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { PipelineStep } from '../../types/build';
import type { DeploymentStatus } from '../../types/deployment';

function formatDuration(start: string | null, end: string | null): string {
  if (!start || !end) return '—';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

function PipelineStepRow({ step }: { step: PipelineStep }) {
  return (
    <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 1 }}>
      <Chip size="small" label={step.status} />
      <Typography variant="body2" sx={{ flex: 1 }}>{step.name}</Typography>
      <Typography variant="caption" color="text.secondary">
        {formatDuration(step.started_at, step.finished_at)}
      </Typography>
    </Stack>
  );
}

export default function BuildDetail() {
  const { id } = useParams();
  const buildId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const build = useSelector((s: RootState) =>
    s.build.current?.id === buildId ? s.build.current : null,
  );
  const deployments = useSelector(
    (s: RootState) => s.deployment.byBuild[buildId] ?? [],
  );

  useEffect(() => {
    if (!Number.isNaN(buildId)) {
      dispatch(fetchBuildById(buildId));
      dispatch(fetchDeploymentsByBuild(buildId));
    }
  }, [dispatch, buildId]);

  if (!build) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5">
        Build {build.build_number ?? build.git_sha.slice(0, 8)}
      </Typography>
      <Stack direction="row" spacing={2} sx={{ mt: 1, color: 'text.secondary' }} flexWrap="wrap">
        <Typography variant="body2">SubSystem: {build.subsystem_name ?? '—'}</Typography>
        <Typography variant="body2">Branch: {build.git_branch ?? '—'}</Typography>
        <Typography variant="body2">SHA: {build.git_sha.slice(0, 12)}</Typography>
        {build.release_name && (
          <Typography variant="body2">Release: {build.release_name}</Typography>
        )}
        <Typography variant="body2">
          Committed {new Date(build.commit_timestamp).toLocaleString()}
        </Typography>
      </Stack>

      <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>Pipeline steps</Typography>
        <Divider sx={{ mb: 1 }} />
        {build.pipeline_steps.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No pipeline steps recorded.</Typography>
        ) : (
          build.pipeline_steps.map((step, i) => (
            <PipelineStepRow key={i} step={step} />
          ))
        )}
      </Paper>

      {build.jira_tickets.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Jira tickets</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {build.jira_tickets.map((t) => (
              <Chip key={t} label={t} size="small" />
            ))}
          </Stack>
        </Paper>
      )}

      {Object.keys(build.custom_fields).length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Custom fields</Typography>
          {Object.entries(build.custom_fields).map(([k, v]) => (
            <Stack key={k} direction="row" spacing={2} sx={{ py: 0.5 }}>
              <Typography variant="body2" sx={{ minWidth: 180 }} color="text.secondary">
                {k}
              </Typography>
              <Typography variant="body2">{String(v)}</Typography>
            </Stack>
          ))}
        </Paper>
      )}

      <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>Deployments</Typography>
        <Divider sx={{ mb: 1 }} />
        {deployments.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No deployments yet.</Typography>
        ) : (
          deployments.map((d) => (
            <Stack
              key={d.id}
              direction="row"
              spacing={2}
              alignItems="center"
              sx={{ py: 1, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' }, px: 1 }}
              onClick={() => navigate(`/deployments/${d.id}`)}
            >
              <Typography variant="body2" sx={{ flex: 1 }}>
                {d.environment_name ?? '—'}
              </Typography>
              <DeploymentStatusChip status={d.status as DeploymentStatus} />
              <Typography variant="caption" color="text.secondary">
                {new Date(d.deployed_at).toLocaleString()}
              </Typography>
            </Stack>
          ))
        )}
      </Paper>
    </Box>
  );
}
