import type { ReactNode } from 'react';
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, Link as MuiLink, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';

import type { QueueResult, WorkItem } from '../../types/myWork';

export interface QueueCardProps {
  title: string;
  queue: QueueResult;
  /** The existing worklist, filtered on the wire the same way this queue is. */
  viewAllHref: string;
  /**
   * The link's own wording — e.g. "PIR actions", "environment requests".
   * NOT derived from `title` (`title.toLowerCase()` reads "pir actions"
   * directly under a card headed "PIR actions"), since a couple of these
   * are proper nouns/acronyms that don't lowercase cleanly.
   */
  viewAllLabel: string;
  /**
   * Shown under the link when it is NOT a narrowed view of "mine" — e.g.
   * decommissions has no owner-filter the target worklist can express, so
   * the link goes to the whole tenant's estate. Omit when the link is
   * either an exact match or a strict superset of what this card counted
   * (contentions/PIR actions widen only the status axis, so every item
   * this card counted still appears there — that needs no caption).
   */
  viewAllCaption?: string;
  renderRow: (item: WorkItem) => ReactNode;
  /** Re-runs the whole `/me/work` call — there is no narrower retry. */
  onRetry?: () => void;
}

/**
 * One "waiting on me" queue. THREE STATES, and they must never be conflated:
 *
 * 1. `queue.failed` — the underlying worklist query blew up. Rendered as an
 *    error with a retry, NEVER as an empty queue: telling a reader "nothing
 *    is waiting on you" when the truth is "we could not find out" is worse
 *    than no card at all (§5 — see `my_work_service.build`'s per-queue
 *    try/except, which is the whole reason this distinction exists).
 * 2. Empty (`count === 0`, not failed) — "Nothing waiting on you". The card
 *    itself is STILL RENDERED (never hidden): a hidden card is
 *    indistinguishable from a queue this user is not a member of at all.
 * 3. Rows — up to five (`ITEM_CAP` on the backend), with `queue.count`
 *    (the FULL count, not `items.length`) shown separately so a reader can
 *    tell there is more before clicking "View all".
 */
export default function QueueCard({
  title,
  queue,
  viewAllHref,
  viewAllLabel,
  viewAllCaption,
  renderRow,
  onRetry,
}: QueueCardProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardHeader
        title={
          <Typography component="h2" variant="h6">
            {title}
          </Typography>
        }
        action={
          !queue.failed && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1, mr: 1 }}>
              {typeof queue.overdue === 'number' && queue.overdue > 0 && (
                <Chip label={`${queue.overdue} overdue`} size="small" color="error" variant="outlined" />
              )}
              <Chip label={queue.count} size="small" color={queue.count > 0 ? 'primary' : 'default'} />
            </Stack>
          )
        }
      />
      <CardContent sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
        {queue.failed ? (
          <Alert
            severity="error"
            action={
              onRetry ? (
                <Button color="inherit" size="small" onClick={onRetry}>
                  Retry
                </Button>
              ) : undefined
            }
          >
            Couldn&apos;t load this queue.
          </Alert>
        ) : queue.items.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Nothing waiting on you
          </Typography>
        ) : (
          <Stack spacing={1.5} sx={{ flexGrow: 1 }}>
            {queue.items.map((item) => (
              <Box key={item.id} data-testid="queue-row">
                {renderRow(item)}
              </Box>
            ))}
          </Stack>
        )}
        <Box sx={{ mt: 2 }}>
          <MuiLink component={RouterLink} to={viewAllHref} underline="hover">
            View all {viewAllLabel} →
          </MuiLink>
          {viewAllCaption && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {viewAllCaption}
            </Typography>
          )}
        </Box>
      </CardContent>
    </Card>
  );
}
