import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Link,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import {
  createUsageAgreement,
  deleteUsageAgreement,
  fetchProject,
  fetchProjectAgreements,
} from '../../store/projectSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { current: project, agreements, agreementTotal, error: loadError } = useSelector(
    (s: RootState) => s.project
  );
  // GET /projects/{id} and GET .../usage-agreements are open to any tenant
  // member; POST/DELETE on the agreement are require_tenant_admin() — the
  // same split as Projects.tsx and the same reasoning as UserGroupDetail.tsx.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const { environments, loading: environmentsLoading } = useAllEnvironments();

  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState<number | ''>('');
  const [startsAt, setStartsAt] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [notes, setNotes] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isNaN(projectId)) {
      // Fetched directly rather than read off the list slice: a deep link or
      // a refresh on this route has never populated `projects`, and the list
      // is a server-paged window that may not even contain this project.
      dispatch(fetchProject(projectId));
      dispatch(fetchProjectAgreements(projectId));
    }
  }, [dispatch, projectId]);

  const handleAddAgreement = async () => {
    if (!selectedEnvironmentId) return;
    setAddError(null);
    const result = await dispatch(
      createUsageAgreement({
        projectId,
        data: {
          environment_id: Number(selectedEnvironmentId),
          starts_at: startsAt || null,
          ends_at: endsAt || null,
          notes: notes.trim() || null,
        },
      })
    );
    if (createUsageAgreement.rejected.match(result)) {
      setAddError(result.payload ?? 'Failed to add usage agreement');
      return;
    }
    setSelectedEnvironmentId('');
    setStartsAt('');
    setEndsAt('');
    setNotes('');
    dispatch(fetchProjectAgreements(projectId));
  };

  const handleRemoveAgreement = async (agreementId: number) => {
    setRemoveError(null);
    const result = await dispatch(deleteUsageAgreement({ projectId, agreementId }));
    if (deleteUsageAgreement.rejected.match(result)) {
      setRemoveError(result.payload ?? 'Failed to remove usage agreement');
      return;
    }
    dispatch(fetchProjectAgreements(projectId));
  };

  return (
    <Box sx={{ p: 3 }}>
      <Button size="small" onClick={() => navigate('/tenant/projects')} sx={{ mb: 2 }}>
        Back to Projects
      </Button>

      {loadError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {loadError}
        </Alert>
      )}

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Typography variant="h5">{project?.name ?? 'Project'}</Typography>
        {project && (
          <Chip
            size="small"
            label={project.is_active ? 'Active' : 'Archived'}
            color={project.is_active ? 'success' : 'default'}
          />
        )}
      </Box>
      {project?.code && (
        <Typography color="text.secondary">Code: {project.code}</Typography>
      )}
      {project?.description && (
        <Typography color="text.secondary" sx={{ mb: 1 }}>
          {project.description}
        </Typography>
      )}
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Team:{' '}
        {project?.team_group_id ? (
          <Link component={RouterLink} to={`/tenant/groups/${project.team_group_id}`}>
            {project.team_group_name ?? `Group #${project.team_group_id}`}
          </Link>
        ) : (
          '— no team'
        )}
      </Typography>

      <Typography variant="h6" sx={{ mt: 3, mb: 1 }}>
        Usage Agreements
      </Typography>
      <Alert severity="info" sx={{ mb: 2 }}>
        A usage agreement is a record of which environments this project is expected
        to use — it is not a rule. Nothing here stops this project booking an
        environment it has no agreement for; enforcement is a separate, later
        piece of work.
      </Alert>

      {addError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {addError}
        </Alert>
      )}
      {removeError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {removeError}
        </Alert>
      )}

      {canWrite && (
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 2, flexWrap: 'wrap' }}>
          <TextField
            select
            label="Environment"
            size="small"
            disabled={environmentsLoading}
            value={selectedEnvironmentId}
            onChange={(e) =>
              setSelectedEnvironmentId(e.target.value ? Number(e.target.value) : '')
            }
            sx={{ minWidth: 220 }}
          >
            {environments.map((env) => (
              <MenuItem key={env.id} value={env.id}>
                {env.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Starts"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
          />
          <TextField
            label="Ends"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
          />
          <TextField
            label="Notes"
            size="small"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            sx={{ minWidth: 200 }}
          />
          <Button
            variant="contained"
            size="small"
            onClick={handleAddAgreement}
            disabled={!selectedEnvironmentId}
          >
            Add
          </Button>
        </Box>
      )}

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        {agreementTotal} agreement{agreementTotal === 1 ? '' : 's'}
      </Typography>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Environment</TableCell>
              <TableCell>Starts</TableCell>
              <TableCell>Ends</TableCell>
              <TableCell>Notes</TableCell>
              {canWrite && <TableCell />}
            </TableRow>
          </TableHead>
          <TableBody>
            {agreements.map((a) => (
              <TableRow key={a.id}>
                <TableCell>
                  <Link component={RouterLink} to={`/environments/${a.environment_id}`}>
                    {a.environment_name}
                  </Link>
                </TableCell>
                <TableCell>{a.starts_at ? new Date(a.starts_at).toLocaleDateString() : '—'}</TableCell>
                <TableCell>{a.ends_at ? new Date(a.ends_at).toLocaleDateString() : '—'}</TableCell>
                <TableCell>{a.notes ?? '—'}</TableCell>
                {canWrite && (
                  <TableCell align="right">
                    <Button size="small" color="error" onClick={() => handleRemoveAgreement(a.id)}>
                      Remove
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  );
}
