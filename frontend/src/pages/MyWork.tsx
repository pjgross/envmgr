/**
 * `/my-work` — "what is waiting on me?", answered by five queues composed
 * server-side under one clock (`GET /me/work`, Task 4).
 *
 * CARDS ARE NEVER HIDDEN, even an empty one — a hidden card is
 * indistinguishable from a queue this user is not a member of at all (§5).
 * And a FAILED queue is never rendered as an empty one — see
 * `QueueCard`'s docblock, the distinction this whole page exists to
 * preserve.
 *
 * Each "View all →" link points at the SAME worklist page every other part
 * of the app already uses, with the same filter this queue was computed
 * with — never a new page, since every worklist already reads its filters
 * from the URL. Two of the five queues cannot be reproduced exactly by a
 * single filter value the target page's own URL vocabulary supports
 * (see the per-link notes below); those link to the closest available
 * filter, documented at each `QUEUES` entry rather than silently dropped.
 */
import type { ReactNode } from 'react';
import { Box, CircularProgress, Container, Grid, Link as MuiLink, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';

import PageHeader from '../components/layout/PageHeader';
import QueueCard from '../components/mywork/QueueCard';
import { useMyWork } from '../hooks/useMyWork';
import type { MyWorkQueueKey, QueueResult, WorkItem } from '../types/myWork';

const EMPTY_QUEUE: QueueResult = { count: 0, items: [], failed: false };

interface QueueConfig {
  key: MyWorkQueueKey;
  title: string;
  /** The existing worklist page, filtered on the wire the same way this queue is. */
  viewAllHref: string;
}

const QUEUES: QueueConfig[] = [
  {
    key: 'environment_requests',
    title: 'Environment requests',
    // `?queue=team` -> `actionable=true` on the wire, EnvironmentRequestList's
    // own vocabulary for "requests my team must action" — exactly what
    // `_environment_requests_queue` counts via `actionable_for`.
    viewAllHref: '/environment-requests?queue=team',
  },
  {
    key: 'contentions',
    title: 'Contentions',
    // `?escalation_owner=me` -> `owner_user_id=<me>` on the wire, matching
    // this queue's ownership filter exactly. The queue also excludes
    // already-decided escalations (`decided_at IS NULL`), which
    // EscalationWorklist's `state` filter cannot express in one value (it
    // offers open/answered/expired, not "not answered") — narrowing to
    // `state=open` would UNDER-count by dropping expired-but-undecided
    // rows, so `state` is left at its default (any) rather than picked
    // wrong. The owner filter is the one that matters for "is this mine".
    viewAllHref: '/contentions?escalation_owner=me',
  },
  {
    key: 'decommissions',
    title: 'Decommissions',
    // No filter at all: `GET /decommissions` (the worklist endpoint) has no
    // membership-narrowing parameter on the wire — confirmed in
    // backend/tests/test_me_work_matches_worklists.py's own comment, which
    // says as much because this is the one queue of the five it cannot
    // assert X-Total-Count equivalence for. There is no URL value to pick
    // here, right or wrong.
    viewAllHref: '/decommissions',
  },
  {
    key: 'pir_actions',
    title: 'PIR actions',
    // `?action_owner=me` -> `owner_id=<me>` on the wire. The queue also
    // narrows to the two LIVE statuses (open, in_progress); PirActionList's
    // `status` filter takes exactly one value, so no single choice
    // reproduces "open or in_progress" — `status=open` would UNDER-count by
    // dropping in_progress rows. Left unset: a superset (also shows
    // done/cancelled actions of mine) rather than a silently short list.
    viewAllHref: '/pir-actions?action_owner=me',
  },
  {
    key: 'incidents',
    title: 'Incidents',
    // Exact match: `?status=open` is precisely what `_incidents_queue` asks
    // for, and IncidentList's `status` filter key is `status` itself.
    viewAllHref: '/incidents?status=open',
  },
];

function formatDue(due: string | null | undefined): string | null {
  if (!due) return null;
  const d = new Date(due);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString();
}

/** Shared across all five cards — every queue's rows carry the same shape
 * (title, optional subtitle, url, optional due date), so there is nothing
 * queue-specific to branch on here. */
function renderRow(item: WorkItem): ReactNode {
  const due = formatDue(item.due);
  return (
    <Stack spacing={0.25}>
      <MuiLink component={RouterLink} to={item.url} underline="hover">
        {item.title}
      </MuiLink>
      {item.subtitle && (
        <Typography variant="caption" color="text.secondary">
          {item.subtitle}
        </Typography>
      )}
      {due && (
        <Typography variant="caption" color="text.secondary">
          Due {due}
        </Typography>
      )}
    </Stack>
  );
}

export default function MyWork() {
  const { data, loading, error, refetch } = useMyWork();

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <PageHeader
        title="My work"
        subtitle={
          data ? `As of ${new Date(data.as_of).toLocaleString()}` : undefined
        }
      />
      {/* A transport-level failure of the whole call (never reached the
          per-queue try/except) — distinct from any single QueueCard's own
          `failed` state, which is what the per-card branches below handle. */}
      {error && !data && (
        <Typography color="error" sx={{ mb: 2 }}>
          {error}
        </Typography>
      )}
      {loading && !data ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Grid container spacing={3}>
          {QUEUES.map((cfg) => (
            <Grid item xs={12} md={6} lg={4} key={cfg.key}>
              <QueueCard
                title={cfg.title}
                queue={data?.queues[cfg.key] ?? EMPTY_QUEUE}
                viewAllHref={cfg.viewAllHref}
                renderRow={renderRow}
                onRetry={refetch}
              />
            </Grid>
          ))}
        </Grid>
      )}
    </Container>
  );
}
