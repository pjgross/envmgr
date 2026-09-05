/**
 * `/dashboard` — every user's landing page. Replaces the Phase-0 placeholder
 * (three tiles hardcoded to `0`).
 *
 * FOUR LIVE TILES, each a `limit=1` fetch of an EXISTING list endpoint,
 * reading the server's unwindowed total off `X-Total-Count` — never
 * `data.length`, which would read "1" for every non-empty list once the
 * fetch is capped at one row. No aggregation endpoint is invented; see
 * `StatTile`. Each tile links to the exact filtered list it counted:
 *
 * - Active environments  -> GET /environments?status=active&limit=1
 *                         -> /environments?status=active
 * - Bookings live now     -> GET /bookings/?start=<now>&end=<now>&active=true&limit=1
 *                         -> /bookings/list?start=<now>&end=<now>&active=true
 *   (`/bookings` itself redirects to the calendar — see the App.tsx route
 *   table — so the tile links at `/bookings/list`, BookingList's own route.
 *   `start`/`end`/`active` needed adding to BookingList's `filterKeys` for
 *   this link to actually filter rather than silently landing on the whole
 *   estate; see that page's own comment.
 *
 *   `active=true` EXCLUDES draft/rejected/closed bookings (the codebase's
 *   own `INACTIVE_BOOKING_STATUSES`). Without it, `?start=&end=` alone
 *   counts a booking nobody has submitted as an occupied environment —
 *   found live in the demo tenant, where 10 of 18 bookings are drafts.
 *   `active` is a new, OPT-IN query param on `GET /bookings/` itself
 *   (`booking_service.list_bookings`) rather than a client-side filter on
 *   the fetched page — the endpoint is bounded (`limit=1` for the tile,
 *   server-paged for the list), so a filter applied after the fetch would
 *   window the wrong set. Every other `/bookings/` consumer keeps its old
 *   behaviour (every status, unless it opts in) — this tile is the one
 *   caller that needs "genuinely live", so the tile and its link are the
 *   only two places that pass it.)
 * - Open releases         -> GET /releases?open=true&limit=1
 *                         -> /releases?open=true
 *   `open=true` resolves to "non-terminal" from EACH RELEASE'S OWN
 *   lifecycle template (a tenant may run several — Major/Minor/Emergency/
 *   Enterprise all at once) via `lifecycle_service.terminal_status_clause`,
 *   never a hardcoded status list.
 *
 *   THE TILE WAS PREVIOUSLY LABELLED "Releases in progress" and counted only
 *   `?status=in_progress` — a real status, but only one of five non-terminal
 *   ones (draft/submitted/approved/in_progress/ready_for_release), so it
 *   under-counted every release still in draft or awaiting approval. Now
 *   that a real "any non-terminal status" filter exists, the tile is
 *   relabelled "Open releases" to match what it actually counts, the same
 *   rule that renamed the incidents tile below.
 * - Open incidents        -> GET /incidents?open=true&limit=1
 *                         -> /incidents?open=true
 *   `open=true` replaced `?status=open` here 2026-09-04: "open" was never a
 *   real incident status (the seeded lifecycle names `new`/`investigating`/
 *   `identified`/`fix_scheduled`/`resolved`/`closed`/`cancelled`), so this
 *   tile read 0 forever in any tenant using the default template. See
 *   docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md §5.
 *
 * "Coming up" and "Needs attention" are previews, not tiles — they have no
 * X-Total-Count contract to keep, only "don't show something misleading".
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import {
  Box,
  Container,
  Grid,
  Link,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  Typography,
} from '@mui/material';

import PageHeader from '../components/layout/PageHeader';
import StatTile from '../components/dashboard/StatTile';
import ContentionHorizon from '../components/bookings/ContentionHorizon';
import HealthAlertBanner from '../components/environments/HealthAlertBanner';
import { environmentService } from '../services/environmentService';
import { bookingService } from '../services/bookingService';
import { releaseService } from '../services/releaseService';
import { incidentService } from '../services/incidentService';
import type { RootState } from '../store';
import type { BookingResponse } from '../types/booking';
import type { ReleaseCalendarEntry } from '../types/release';

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;
const FOURTEEN_DAYS_MS = 14 * 24 * 60 * 60 * 1000;
const PREVIEW_ROW_CAP = 5;

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
}

// ---------------------------------------------------------------------------
// Coming up: bookings starting in the next 7 days
// ---------------------------------------------------------------------------

/**
 * `bookingService.listBookings({ start, end, active: true })` is the OVERLAP
 * filter Task 1 added — a booking that started before `now` and merely runs
 * past it also matches, which is right for "live now" but not for "starting
 * soon". So the fetched window is narrowed further, client-side, to rows
 * whose own `start_date` actually falls in it. This is a preview list, not a
 * paginated grid — narrowing a fetched batch here does not window a count
 * the way it would on a page with a `limit`/`offset` contract
 * (docs/pagination.md's rule is about the FOUR TILES above, which have no
 * client-side filter at all).
 *
 * `active: true` excludes draft/rejected/closed bookings, the same fix the
 * "Bookings live now" tile got — without it, a draft nobody has submitted
 * showed up under "Bookings starting soon" as though it were scheduled.
 */
function ComingUpBookings() {
  const [rows, setRows] = useState<BookingResponse[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const now = new Date();
    const end = new Date(now.getTime() + SEVEN_DAYS_MS);
    bookingService
      .listBookings({
        start: now.toISOString(),
        end: end.toISOString(),
        active: true,
        limit: 50,
        sort_by: 'start_date',
        sort_dir: 'asc',
      })
      .then(({ rows: fetched }) => {
        if (cancelled) return;
        const nowMs = now.getTime();
        setRows(
          fetched
            .filter((b) => new Date(b.start_date).getTime() >= nowMs)
            .slice(0, PREVIEW_ROW_CAP)
        );
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <Typography variant="body2" color="text.secondary">
        Couldn&apos;t load upcoming bookings.
      </Typography>
    );
  }
  if (rows === null) return <Typography variant="body2">Loading…</Typography>;
  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No bookings starting in the next 7 days.
      </Typography>
    );
  }
  return (
    <List dense disablePadding>
      {rows.map((b) => (
        <ListItem key={b.id} disableGutters>
          <ListItemText
            primary={
              <Link component={RouterLink} to={`/bookings/${b.id}`}>
                {b.environment_name ?? `Environment ${b.environment_id}`}
              </Link>
            }
            secondary={`Starts ${formatDate(b.start_date)}`}
          />
        </ListItem>
      ))}
    </List>
  );
}

// ---------------------------------------------------------------------------
// Coming up: releases whose target date falls in the next 14 days
// ---------------------------------------------------------------------------

function ComingUpReleases() {
  const [rows, setRows] = useState<ReleaseCalendarEntry[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const now = new Date();
    const end = new Date(now.getTime() + FOURTEEN_DAYS_MS);
    releaseService
      .listCalendar(now.toISOString(), end.toISOString())
      .then((entries) => {
        if (cancelled) return;
        setRows(
          entries
            .filter((r) => r.start)
            .sort((a, b) => new Date(a.start as string).getTime() - new Date(b.start as string).getTime())
            .slice(0, PREVIEW_ROW_CAP)
        );
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <Typography variant="body2" color="text.secondary">
        Couldn&apos;t load upcoming releases.
      </Typography>
    );
  }
  if (rows === null) return <Typography variant="body2">Loading…</Typography>;
  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No releases due in the next 14 days.
      </Typography>
    );
  }
  return (
    <List dense disablePadding>
      {rows.map((r) => (
        <ListItem key={r.id} disableGutters>
          <ListItemText
            primary={
              <Link component={RouterLink} to={`/releases/${r.id}`}>
                {r.title}
              </Link>
            }
            secondary={`Due ${formatDate(r.start)}`}
          />
        </ListItem>
      ))}
    </List>
  );
}

// ---------------------------------------------------------------------------
// Needs attention: Admin-only governance line
// ---------------------------------------------------------------------------

/**
 * Counted the same `limit=1` + `X-Total-Count` way as the four tiles above,
 * but not a fifth tile: Admin-only, and folded into one line rather than
 * one more Grid cell.
 *
 * FAILURE IS NEVER RENDERED AS ZERO — the bug `StatTile` was already built
 * to avoid (finding 3 of the PR 3 whole-branch review). The old `catch(() =>
 * setGap(0))` produced "0 environments have a governance gap", an
 * affirmative false statement manufactured from a failed request. Each half
 * now tracks its own `failed` flag and renders a distinct "couldn't load"
 * span in its place instead of a clickable count.
 */
function GovernanceGapLine() {
  const [gap, setGap] = useState<number | null>(null);
  const [gapFailed, setGapFailed] = useState(false);
  const [quarantined, setQuarantined] = useState<number | null>(null);
  const [quarantinedFailed, setQuarantinedFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    environmentService
      .listEnvironments({ governance_gap: true, limit: 1 })
      .then((p) => {
        if (!cancelled) setGap(p.total);
      })
      .catch(() => {
        if (!cancelled) setGapFailed(true);
      });
    environmentService
      .listEnvironments({ quarantined: true, limit: 1 })
      .then((p) => {
        if (!cancelled) setQuarantined(p.total);
      })
      .catch(() => {
        if (!cancelled) setQuarantinedFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // "Settled" now means resolved OR failed — a failure must count as settled
  // too, or this line would wait forever rather than ever showing the
  // couldn't-load text.
  const gapSettled = gap !== null || gapFailed;
  const quarantinedSettled = quarantined !== null || quarantinedFailed;
  if (!gapSettled || !quarantinedSettled) return null;

  return (
    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
      {gapFailed ? (
        <Box component="span" aria-label="governance gap: couldn't load">
          Couldn&apos;t load governance gap
        </Box>
      ) : (
        <Link component={RouterLink} to="/environments?governance_gap=true">
          {gap} {gap === 1 ? 'environment has' : 'environments have'} a governance gap
        </Link>
      )}
      {' · '}
      {quarantinedFailed ? (
        <Box component="span" aria-label="quarantined count: couldn't load">
          couldn&apos;t load quarantined count
        </Box>
      ) : (
        <Link component={RouterLink} to="/environments?quarantined=true">
          {quarantined} quarantined
        </Link>
      )}
    </Typography>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const user = useSelector((s: RootState) => s.auth.user);
  const isAdmin = user?.role === 'Admin' || user?.is_master_admin === true;

  // One "now" per mount, shared between each tile's fetch and its link so
  // the two can never describe two different instants.
  const nowIso = useMemo(() => new Date().toISOString(), []);
  const bookingsHref = useMemo(
    () =>
      `/bookings/list?${new URLSearchParams({ start: nowIso, end: nowIso, active: 'true' }).toString()}`,
    [nowIso]
  );

  const fetchActiveEnvironments = useCallback(
    () => environmentService.listEnvironments({ status: 'active', limit: 1 }).then((p) => p.total),
    []
  );
  const fetchLiveBookings = useCallback(
    () =>
      bookingService
        .listBookings({ start: nowIso, end: nowIso, active: true, limit: 1 })
        .then((p) => p.total),
    [nowIso]
  );
  const fetchOpenReleases = useCallback(
    () => releaseService.list({ open: true, limit: 1 }).then((p) => p.total),
    []
  );
  const fetchOpenIncidents = useCallback(
    () => incidentService.list({ open: true, limit: 1 }).then((p) => p.total),
    []
  );

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <PageHeader title="Dashboard" />

      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} lg={3}>
          <StatTile
            label="Active environments"
            to="/environments?status=active"
            fetchCount={fetchActiveEnvironments}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <StatTile label="Bookings live now" to={bookingsHref} fetchCount={fetchLiveBookings} />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <StatTile
            label="Open releases"
            to="/releases?open=true"
            fetchCount={fetchOpenReleases}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <StatTile
            label="Open incidents"
            to="/incidents?open=true"
            fetchCount={fetchOpenIncidents}
            // `open` is non-terminal, and `resolved` is non-terminal in the default
            // lifecycle — only `closed`/`cancelled` are. So a resolved incident still
            // awaiting close-out counts here, and the label alone would not say so.
            hint="Includes resolved incidents not yet closed"
          />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper variant="outlined" sx={{ p: 3, height: '100%' }}>
            <Typography variant="h6" gutterBottom>
              Coming up
            </Typography>
            <Stack spacing={2}>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Bookings starting soon
                </Typography>
                <ComingUpBookings />
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Releases due soon
                </Typography>
                <ComingUpReleases />
              </Box>
            </Stack>
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper variant="outlined" sx={{ p: 3, height: '100%' }}>
            <Typography variant="h6" gutterBottom>
              Needs attention
            </Typography>
            <ContentionHorizon />
            <HealthAlertBanner />
            {isAdmin && <GovernanceGapLine />}
          </Paper>
        </Grid>
      </Grid>
    </Container>
  );
}
