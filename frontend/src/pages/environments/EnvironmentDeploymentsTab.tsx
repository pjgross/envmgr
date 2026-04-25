import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import { Paper } from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeployments } from '../../store/deploymentSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { DeploymentStatus } from '../../types/deployment';

interface Props {
  envId: number;
}

export default function EnvironmentDeploymentsTab({ envId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.deployment);

  useEffect(() => {
    dispatch(fetchDeployments({ environment_id: envId }));
  }, [dispatch, envId]);

  const rows = items
    .filter((d) => d.environment_id === envId)
    .map((d) => ({
      id: d.id,
      build_sha_short: d.build_sha_short ?? '—',
      status: d.status,
      deployer_name: d.deployer_name ?? '—',
      deployed_at: new Date(d.deployed_at).toLocaleString(),
      release_name: d.release_name ?? '—',
      change_request_title: d.change_request_title ?? '—',
    }));

  const cols: GridColDef[] = [
    { field: 'build_sha_short', headerName: 'Build', width: 110 },
    {
      field: 'status', headerName: 'Status', width: 140,
      renderCell: (p) => <DeploymentStatusChip status={p.value as DeploymentStatus} />,
    },
    { field: 'deployer_name', headerName: 'Deployer', flex: 1 },
    { field: 'deployed_at', headerName: 'Deployed at', width: 200 },
    { field: 'release_name', headerName: 'Release', width: 160 },
    { field: 'change_request_title', headerName: 'Change request', width: 200 },
  ];

  return (
    <Paper variant="outlined">
      <DataGrid
        rows={rows}
        columns={cols}
        autoHeight
        loading={loading}
        onRowClick={(p: GridRowParams) => navigate(`/deployments/${p.id}`)}
        disableRowSelectionOnClick
      />
    </Paper>
  );
}
