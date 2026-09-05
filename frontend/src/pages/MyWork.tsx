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
import type { MyWorkQueueKey, MyWorkResponse, QueueResult, WorkItem } from '../types/myWork';

const EMPTY_QUEUE: QueueResult = { count: 0, items: [], failed: false };

// The fallback fed to EVERY card when the whole `/me/work` call failed
// (network error, or a 5xx before any per-queue try/except on the backend
// even ran) — as opposed to `data.queues[key].failed`, which is a single
// queue's own worklist query failing while the rest of the response is
// fine. Without this, `data` stays `null` and `data?.queues[key] ??
// EMPTY_QUEUE` would hand every card an *empty*, non-failed queue: five
// confident "Nothing waiting on you"s built from a response that never
// arrived. Same rule as `QueueCard`'s own failed-vs-empty distinction, one
// level up.
const WHOLE_RESPONSE_FAILED_QUEUE: QueueResult = { count: 0, items: [], failed: true };

/**
 * Reads one queue out of `data` defensively (finding 4 of the PR 3
 * whole-branch review). `data?.queues[key]` throws the moment `data` is
 * non-null but `queues` is missing or malformed — a `/me/work` 200 with a
 * body that does not match `MyWorkResponse` — and this page is reached by
 * clicking the nav badge that already rendered from that same response, so
 * the malformed-body case is not hypothetical. Falls back the same way a
 * missing response does: `WHOLE_RESPONSE_FAILED_QUEUE` when there is an
 * `error` to explain it, `EMPTY_QUEUE` otherwise.
 */
function queueFor(
  data: MyWorkResponse | null,
  key: MyWorkQueueKey,
  error: string | null
): QueueResult {
  // Cast, not a structural assignment: the type system already guarantees
  // `queues` is well-shaped when the response really is a `MyWorkResponse` —
  // the runtime check right below is for the case it ISN'T, which `tsc`
  // cannot see from here.
  const queues = data?.queues as Record<string, QueueResult> | undefined;
  const queue = queues && typeof queues === 'object' ? queues[key] : undefined;
  if (queue) return queue;
  return error ? WHOLE_RESPONSE_FAILED_QUEUE : EMPTY_QUEUE;
}

interface QueueConfig {
  key: MyWorkQueueKey;
  title: string;
  /** The existing worklist page, filtered on the wire the same way this queue is. */
  viewAllHref: string;
  /** The link's own wording — see `QueueCardProps.viewAllLabel`. */
  viewAllLabel: string;
  /** See `QueueCardProps.viewAllCaption`. */
  viewAllCaption?: string;
}

const QUEUES: QueueConfig[] = [
  {
    key: 'environment_requests',
    title: 'Environment requests',
    // `?queue=team` -> `actionable=true` on the wire, EnvironmentRequestList's
    // own vocabulary for "requests my team must action" — exactly what
    // `_environment_requests_queue` counts via `actionable_for`.
    viewAllHref: '/environment-requests?queue=team',
    viewAllLabel: 'environment requests',
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
    // wrong. The owner filter is the one that matters for "is this mine",
    // and it is exact, so every item this card counted still shows up
    // there — a strict superset, never a fewer-rows surprise. No caption.
    viewAllHref: '/contentions?escalation_owner=me',
    viewAllLabel: 'contentions',
  },
  {
    key: 'decommissions',
    title: 'Decommissions',
    // `?mine=true` -> `member_user_id=<me>` on the wire — the SAME
    // membership predicate `_decommissions_queue` already used privately
    // (`environment_decommission_service.worklist_query`'s own
    // `member_user_id`), now exposed on `GET /decommissions` itself (PR 3's
    // dashboard fix wave, finding 6 — spec §5's amendment said this
    // endpoint would gain the capability, and only the service seam had
    // it until now). This is still not an EXACT match: the card additionally
    // excludes `cancelled`/`torn_down` (terminal, computed per row), which
    // the worklist's own `state=` filter can express only one at a time —
    // so `?mine=true` alone is a superset (mine, any state) rather than
    // the identical filtered set. No caption: the estate-wide disclosure
    // this used to need no longer applies now the link actually narrows by
    // membership.
    viewAllHref: '/decommissions?mine=true',
    viewAllLabel: 'decommissions',
  },
  {
    key: 'pir_actions',
    title: 'PIR actions',
    // `?action_owner=me` -> `owner_id=<me>` on the wire. The queue also
    // narrows to the two LIVE statuses (open, in_progress); PirActionList's
    // `status` filter takes exactly one value, so no single choice
    // reproduces "open or in_progress" — `status=open` would UNDER-count by
    // dropping in_progress rows. Left unset: a superset (also shows
    // done/cancelled actions of mine) rather than a silently short list —
    // the owner filter is exact, so nothing this card counted is missing
    // there. No caption.
    viewAllHref: '/pir-actions?action_owner=me',
    viewAllLabel: 'PIR actions',
  },
  {
    key: 'incidents',
    title: 'Incidents',
    // Exact match: `?open=true` is precisely what `_incidents_queue` asks
    // for (`incident_service.list_incidents(..., {"open": True})`), and
    // IncidentList's `open` filter key is `open` itself (added to its
    // `filterKeys` for exactly this link). This replaced `?status=open`
    // 2026-09-04 — "open" was never a real incident status, so that link
    // always landed on an empty list regardless of this card's count.
    viewAllHref: '/incidents?open=true',
    viewAllLabel: 'incidents',
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
                // `data`'s per-queue `failed` flag when the response arrived;
                // WHOLE_RESPONSE_FAILED_QUEUE when it never did (`error` set,
                // `data` still null) — never EMPTY_QUEUE in that case, or a
                // total failure renders as five confident empty queues (see
                // the constant's own comment above). `queueFor` also covers
                // the case `data` arrived but `queues` did not match the
                // expected shape — see its own comment.
                queue={queueFor(data, cfg.key, error)}
                viewAllHref={cfg.viewAllHref}
                viewAllLabel={cfg.viewAllLabel}
                viewAllCaption={cfg.viewAllCaption}
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
