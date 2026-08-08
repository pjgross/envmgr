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
  fetchProjectGapBookingCount,
} from '../../store/projectSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';

/**
 * Where the gap rollup below points: this project's bookings that no live
 * usage agreement covers.
 *
 * BOTH QUERY PARAMS ARE REAL, and that is the entire risk being managed here.
 * `BookingList` declares `filterKeys: ['booking_status', 'project_id',
 * 'agreement_gap']` and `useServerGrid` hydrates every one of them out of
 * `searchParams`, so a link carrying these two arrives filtered; `GET
 * /bookings` in turn declares both, and `agreement_gap`'s value vocabulary is
 * `'any' | 'true' | 'false'`, so `true` is a value it acts on rather than one
 * it drops. Nothing anywhere errors on a param that is not — FastAPI drops an
 * unknown query param silently, and `useServerGrid` simply never reads a key
 * absent from `filterKeys`. A1 shipped a count linking to a `?project_id=`
 * that `GET /environments` had never accepted; it rendered the whole estate as
 * one project's environments, with a test and the admin guide both asserting
 * it as correct.
 *
 * Exported so the link and the guard test are the SAME string — a test that
 * asserts a hand-written href against a hand-written href guards nothing.
 * `projectDetailGapLink.test.tsx` feeds this value to a real `BookingList` and
 * asserts the fetch it issues actually carries the filter.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function gapBookingsHref(projectId: number): string {
  return `/bookings/list?project_id=${projectId}&agreement_gap=true`;
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  // A route param is a string and nothing between the address bar and here
  // validates it. `Number('nope')` is NaN and `Number('1.5')` is 1.5, either of
  // which would reach `gapBookingsHref` and render a link carrying
  // `project_id=NaN` — and, because nothing is dispatched for a project that
  // cannot be fetched, would render it beside the PREVIOUS project's count,
  // which the slice still holds. One predicate, used by both the effect and
  // the render, so the two cannot drift apart.
  const projectIdIsValid = Number.isInteger(projectId) && projectId > 0;
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const {
    current: project,
    agreements,
    agreementTotal,
    gapBookingCount,
    gapBookingCountError,
    error: loadError,
  } = useSelector((s: RootState) => s.project);
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
    if (projectIdIsValid) {
      // Fetched directly rather than read off the list slice: a deep link or
      // a refresh on this route has never populated `projects`, and the list
      // is a server-paged window that may not even contain this project.
      dispatch(fetchProject(projectId));
      dispatch(fetchProjectAgreements(projectId));
      dispatch(fetchProjectGapBookingCount(projectId));
    }
  }, [dispatch, projectId, projectIdIsValid]);

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
    // The rollup is computed from these very rows: recording the missing
    // agreement is the ONLY thing that closes a gap, so a count left alone
    // here would keep reporting the gap the user just fixed, on the page they
    // fixed it on. Same reason it is refetched after a Remove.
    dispatch(fetchProjectGapBookingCount(projectId));
  };

  const handleRemoveAgreement = async (agreementId: number) => {
    setRemoveError(null);
    const result = await dispatch(deleteUsageAgreement({ projectId, agreementId }));
    if (deleteUsageAgreement.rejected.match(result)) {
      setRemoveError(result.payload ?? 'Failed to remove usage agreement');
      return;
    }
    dispatch(fetchProjectAgreements(projectId));
    dispatch(fetchProjectGapBookingCount(projectId));
  };

  // After every hook, so the hook order is unconditional. Nothing was fetched
  // for this address, so everything the page could render belongs to whichever
  // project was last viewed: the name, the agreements table, and — the one the
  // user might act on — a count of bookings in gap beside a link that would
  // send `project_id=NaN`, which `GET /bookings` answers with a 422 the user
  // never asked for. Say what is wrong instead of rendering another project's
  // numbers under this address.
  if (!projectIdIsValid) {
    return (
      <Box sx={{ p: 3 }}>
        <Button size="small" onClick={() => navigate('/tenant/projects')} sx={{ mb: 2 }}>
          Back to Projects
        </Button>
        <Alert severity="error">
          That address does not name a project. Pick one from the Projects list.
        </Alert>
      </Box>
    );
  }

  // The address names a project this tenant does not have — most often a
  // SOFT-DELETED one, which is a real id that `get_project` refuses because it
  // filters `deleted_at`. Everything below describes ONE project, and `current`
  // is the only thing on this page that says WHICH; without this the page
  // rendered "Project not found" above a working gap rollup — a correct,
  // clickable number under a banner saying the thing it counts for does not
  // exist. (The count really is correct: a booking request still points at the
  // deleted project, which is exactly why that booking is in gap.)
  //
  // GATED ON `current`, NOT ON `loadError`. `projectSlice`'s `error` is shared
  // with `fetchProjectAgreements`, whose `fulfilled` handler sets it to null, so
  // a banner is not something this page can rely on still being there — whereas
  // `current` is null until this project, specifically, loads. While the fetch
  // is in flight `current` is also null, which is why the branch renders no
  // claim of its own beyond the error the slice supplies.
  if (project == null) {
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
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Button size="small" onClick={() => navigate('/tenant/projects')} sx={{ mb: 2 }}>
        Back to Projects
      </Button>

      {/* Reachable with the project loaded: the agreements list or a write can
          fail on its own. */}
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
      {/* A3 warns; it never blocks. The old copy ended "enforcement is a
          separate, later piece of work" — true under A1, and false the moment
          the warning shipped. What has NOT changed is the half that matters:
          nothing here refuses a booking. */}
      <Alert severity="info" sx={{ mb: 2 }}>
        A usage agreement is a record of which environments this project is expected
        to use — it is not a rule. Nothing here stops this project booking an
        environment it has no agreement for: the booking is still created, and is
        flagged with a warning on the booking itself and in the bookings list.
        Recording the agreement here clears that warning on its own.
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

      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 2, mb: 1, flexWrap: 'wrap' }}>
        <Typography variant="subtitle2">
          {agreementTotal} agreement{agreementTotal === 1 ? '' : 's'}
        </Typography>
        {/* The other side of the same coin, beside the table it is computed
            against: agreements recorded here, bookings not covered by any of
            them there. Rendered only when the count is KNOWN — a failed
            rollup shows the caption below instead, never a silent 0, because
            "0 bookings in gap" and "nobody could tell you" are opposite
            answers (CLAUDE.md's partial-read rule). */}
        {gapBookingCount !== null && (
          <>
            <Link
              component={RouterLink}
              to={gapBookingsHref(projectId)}
              variant="subtitle2"
              color={gapBookingCount > 0 ? 'warning.main' : 'text.secondary'}
            >
              {gapBookingCount === 0
                ? 'No bookings in gap'
                : `${gapBookingCount} booking${gapBookingCount === 1 ? '' : 's'} in gap`}
            </Link>
            {/* The count is status-blind, and reads as current exposure if it
                does not say so: `gap_clause` looks at the project, the
                environment and the dates, NEVER at `Booking.status`, so ten
                closed bookings count exactly as much as two live ones. The
                linked list shows the same set for the same reason, so the two
                agree — but "12 bookings in gap" on a project with two live
                bookings is a number an admin would otherwise act on. Outside
                the Link deliberately: inside it, this text would join the
                link's accessible name. */}
            <Typography variant="caption" color="text.secondary">
              any status — drafts and closed included
            </Typography>
          </>
        )}
        {gapBookingCountError && (
          <Typography variant="caption" color="text.secondary">
            Bookings in gap: unavailable ({gapBookingCountError})
          </Typography>
        )}
      </Box>

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
