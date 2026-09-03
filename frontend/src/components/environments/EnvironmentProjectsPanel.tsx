/**
 * EnvironmentProjectsPanel — "Projects using this environment", the
 * environment-direction read of the usage-agreement table A1 ships
 * (GET /environments/{id}/usage-agreements via fetchEnvironmentAgreements).
 *
 * Project names come from the agreement rows themselves, never resolved
 * against a separately-fetched (and capped) projects collection — a
 * `.find()` miss there renders `—` and loses information no truncation
 * banner can recover (docs/pagination.md).
 *
 * `fetchEnvironmentAgreements` is a read thunk, so a failed load leaves
 * `state.project.error` set for this panel to render — but it has no
 * `pending` handler in projectSlice, so `state.project.loading` never flips
 * for it. On the previous sub-project a detail page keyed its skeleton on a
 * `loading` flag only the *list* thunk ever set and rendered permanently
 * blank; loading is tracked locally here instead, never off the shared flag.
 *
 * The copy below is deliberate, not decorative: nothing in A1 stops a
 * project booking an environment it has no agreement for. Enforcement is
 * sub-project A3. Without this line the first person to see the panel will
 * assume it is already enforced.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
  Link,
} from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { fetchEnvironmentAgreements } from '../../store/projectSlice';

interface EnvironmentProjectsPanelProps {
  environmentId: number;
}

function formatWindow(startsAt: string | null, endsAt: string | null): string {
  // Finding M5: with neither date set this used to fall through to the
  // dash-built string below and render '— – —', which reads as a rendering
  // fault rather than the deliberate "no window" state an agreement is
  // allowed to be in.
  if (!startsAt && !endsAt) return 'No window set';
  const start = startsAt ? new Date(startsAt).toLocaleDateString() : '—';
  const end = endsAt ? new Date(endsAt).toLocaleDateString() : '—';
  return `${start} – ${end}`;
}

export default function EnvironmentProjectsPanel({
  environmentId,
}: EnvironmentProjectsPanelProps) {
  const dispatch = useDispatch<AppDispatch>();
  // Project names travel with the agreement rows themselves (`a.project_name`
  // below) — never read `state.project.projects`, which is a separately
  // fetched, capped collection this panel does not load.
  const agreements = useSelector((state: RootState) => state.project.agreements);
  const error = useSelector((state: RootState) => state.project.error);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    dispatch(fetchEnvironmentAgreements(environmentId)).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [dispatch, environmentId]);

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Projects using this environment
      </Typography>
      {/*
        `role="status"` rather than Alert's default `role="alert"`: this is a
        permanent disclaimer, not a transient notification, and `alert` is for
        the latter. It also collided with a page-level `queryByRole('alert')`
        absence check in EnvironmentDetailGovernanceForm.test.tsx. Overriding
        the role keeps both — the visual prominence ProjectDetail's identical
        copy already has, and a role assistive tech can actually announce.
        The error Alert below keeps the default role; a failed load IS what
        that role is for.
      */}
      <Alert severity="info" role="status" sx={{ mb: 2 }}>
        This is a record, not a rule — usage agreements are not enforced. A project may
        still book this environment with no agreement in place; nothing here warns or
        refuses it.
      </Alert>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {!loading && !error && agreements.length === 0 && (
        <Typography color="text.secondary">
          No projects have a usage agreement for this environment.
        </Typography>
      )}

      {agreements.length > 0 && (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Project</TableCell>
              <TableCell>Window</TableCell>
              <TableCell>Notes</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {agreements.map((a) => (
              <TableRow key={a.id}>
                <TableCell>
                  <Link component={RouterLink} to={`/projects/${a.project_id}`}>
                    {a.project_name}
                  </Link>
                </TableCell>
                <TableCell>{formatWindow(a.starts_at, a.ends_at)}</TableCell>
                <TableCell>{a.notes ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}
