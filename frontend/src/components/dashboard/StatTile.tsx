import { useEffect, useState } from 'react';
import { Link, Paper, Skeleton, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';

export interface StatTileProps {
  /** The tile's heading, and the accessible name of the link it renders as. */
  label: string;
  /**
   * Where the tile links — filtered EXACTLY the same way `fetchCount`
   * counted. A tile whose link drops the filter sends the user to a list
   * that disagrees with the number they just clicked.
   */
  to: string;
  /**
   * Resolves to the server's unwindowed total — `X-Total-Count` on a
   * `limit=1` fetch of an existing list endpoint. Never `data.length`: a
   * `limit=1` fetch returns one row, so a tile reading the array length
   * would show "1" for every non-empty list.
   */
  fetchCount: () => Promise<number>;
}

/**
 * One dashboard tile. Self-fetches on mount so each tile owns its own
 * request and its own failure — one tile's list endpoint erroring must not
 * blank the other three.
 */
export default function StatTile({ label, to, fetchCount }: StatTileProps) {
  const [count, setCount] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setCount(null);
    setFailed(false);
    fetchCount()
      .then((n) => {
        if (!cancelled) setCount(n);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchCount]);

  return (
    <Paper variant="outlined" sx={{ height: '100%' }}>
      <Link
        component={RouterLink}
        to={to}
        underline="none"
        color="inherit"
        sx={{ display: 'block', p: 3, '&:hover': { bgcolor: 'action.hover' } }}
      >
        <Typography variant="h6" gutterBottom>
          {label}
        </Typography>
        {failed ? (
          <Typography variant="h3" color="text.secondary" aria-label={`${label}: couldn't load`}>
            —
          </Typography>
        ) : count === null ? (
          <Skeleton variant="text" width={60} height={48} />
        ) : (
          <Typography variant="h3">{count}</Typography>
        )}
      </Link>
    </Paper>
  );
}
