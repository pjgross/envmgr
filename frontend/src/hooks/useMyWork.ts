import { useCallback, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import type { AppDispatch, RootState } from '../store';
import { fetchMyWork, selectMyWorkTotal } from '../store/myWorkSlice';
import type { MyWorkResponse } from '../types/myWork';

/**
 * `/my-work`'s data source, and Task 7's nav badge count.
 *
 * `total` is the sum across all five queues (via `selectMyWorkTotal`) — a
 * badge that read `data.queues` itself would need updating the day a sixth
 * queue is added; this does not.
 *
 * `refetch` re-runs the WHOLE `/me/work` call. There is no per-queue retry
 * endpoint — the backend composes all five under one clock in one request —
 * so a failed queue's "Retry" button is this, not a narrower call.
 */
export function useMyWork(): {
  data: MyWorkResponse | null;
  loading: boolean;
  error: string | null;
  total: number;
  refetch: () => void;
} {
  const dispatch = useDispatch<AppDispatch>();
  const { data, loading, error } = useSelector((s: RootState) => s.myWork);
  const total = useSelector(selectMyWorkTotal);

  const refetch = useCallback(() => {
    dispatch(fetchMyWork());
  }, [dispatch]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, total, refetch };
}
