import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box, Button, Chip, CircularProgress, Divider, Paper, Stack,
  Tooltip, Typography,
} from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeploymentById, linkDeploymentChange } from '../../store/deploymentSlice';
import { fetchBuildById } from '../../store/buildSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import LinkChangeDialog from '../../components/deployments/LinkChangeDialog';
import { useSnackbar } from '../../hooks/useSnackbar';
import api from '../../services/api';

interface LinkedCr {
  id: number;
  title: string;
  status: string;
  lifecycle_id: number;
}

interface LifecycleTemplate {
  id: number;
  name: string;
}

export default function DeploymentDetail() {
  const { id } = useParams();
  const deploymentId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const deployment = useSelector((s: RootState) =>
    s.deployment.current?.id === deploymentId ? s.deployment.current : null,
  );
  const build = useSelector((s: RootState) =>
    deployment && s.build.current?.id === deployment.build_id ? s.build.current : null,
  );

  const [cr, setCr] = useState<LinkedCr | null>(null);
  const [crLifecycle, setCrLifecycle] = useState<LifecycleTemplate | null>(null);
  const [linkOpen, setLinkOpen] = useState(false);

  useEffect(() => {
    if (!Number.isNaN(deploymentId)) dispatch(fetchDeploymentById(deploymentId));
  }, [dispatch, deploymentId]);

  useEffect(() => {
    if (deployment) dispatch(fetchBuildById(deployment.build_id));
  }, [dispatch, deployment]);

  useEffect(() => {
    if (!deployment) {
      setCr(null);
      setCrLifecycle(null);
      return;
    }
    api.get<LinkedCr>(`/change-requests/${deployment.change_request_id}`)
      .then((r) => {
        setCr(r.data);
        return api.get<LifecycleTemplate>(`/lifecycle-templates/${r.data.lifecycle_id}`);
      })
      .then((r) => r && setCrLifecycle(r.data))
      .catch(() => {
        /* leave both null — button stays disabled */
      });
  }, [deployment]);

  if (!deployment || !build) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  const isAutoCr = crLifecycle?.name === 'Code Deployment';
  const linkButton = (
    <Button
      variant="outlined"
      size="small"
      disabled={!isAutoCr}
      onClick={() => setLinkOpen(true)}
    >
      Link a different change request
    </Button>
  );

  const handleLink = async (newCrId: number) => {
    try {
      await dispatch(linkDeploymentChange({
        id: deploymentId,
        data: { change_request_id: newCrId },
      })).unwrap();
      snackbar.success('Change request relinked');
      const r = await api.get<LinkedCr>(`/change-requests/${newCrId}`);
      setCr(r.data);
      const tpl = await api.get<LifecycleTemplate>(`/lifecycle-templates/${r.data.lifecycle_id}`);
      setCrLifecycle(tpl.data);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to link change request');
    }
  };

  const deploymentTitle = build.build_number
    ? `${deployment.environment_name ?? 'Unknown environment'} — Build ${build.build_number}`
    : `${deployment.environment_name ?? 'Unknown environment'} — ${build.git_sha.slice(0, 8)}`;

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="h5">{deploymentTitle}</Typography>
        <DeploymentStatusChip status={deployment.status} size="medium" />
      </Stack>
      <Stack direction="row" spacing={2} sx={{ color: 'text.secondary', mb: 3 }} flexWrap="wrap">
        <Typography variant="body2">Environment: {deployment.environment_name ?? '—'}</Typography>
        {deployment.release_name && (
          <Typography variant="body2">Release: {deployment.release_name}</Typography>
        )}
        <Typography variant="body2">
          Deployed {new Date(deployment.deployed_at).toLocaleString()}
        </Typography>
        {deployment.deployer_name && (
          <Typography variant="body2">by {deployment.deployer_name}</Typography>
        )}
      </Stack>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6">Build</Typography>
          <Button size="small" onClick={() => navigate(`/builds/${build.id}`)}>
            View full build
          </Button>
        </Stack>
        <Divider sx={{ mb: 1 }} />
        <Stack direction="row" spacing={3} flexWrap="wrap">
          <Typography variant="body2">SubSystem: {build.subsystem_name ?? '—'}</Typography>
          <Typography variant="body2">SHA: {build.git_sha.slice(0, 12)}</Typography>
          <Typography variant="body2">Branch: {build.git_branch ?? '—'}</Typography>
          {build.build_number && (
            <Typography variant="body2">Build: {build.build_number}</Typography>
          )}
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6">Change request</Typography>
          {isAutoCr
            ? linkButton
            : (
              <Tooltip title="This deployment is linked to a human-authored change request and cannot be relinked.">
                <span>{linkButton}</span>
              </Tooltip>
            )}
        </Stack>
        <Divider sx={{ mb: 1 }} />
        {cr ? (
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography
              variant="body2"
              sx={{ flex: 1, cursor: 'pointer', color: 'primary.main' }}
              onClick={() => navigate(`/change-requests/${cr.id}`)}
            >
              {cr.title}
            </Typography>
            <Chip size="small" label={cr.status} />
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">Loading…</Typography>
        )}
      </Paper>

      {Object.keys(deployment.custom_fields).length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Custom fields</Typography>
          {Object.entries(deployment.custom_fields).map(([k, v]) => (
            <Stack key={k} direction="row" spacing={2} sx={{ py: 0.5 }}>
              <Typography variant="body2" sx={{ minWidth: 180 }} color="text.secondary">
                {k}
              </Typography>
              <Typography variant="body2">{String(v)}</Typography>
            </Stack>
          ))}
        </Paper>
      )}

      <LinkChangeDialog
        open={linkOpen}
        onClose={() => setLinkOpen(false)}
        onSubmit={handleLink}
      />
    </Box>
  );
}
