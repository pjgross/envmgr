/**
 * Greedy interval-packing for booking swimlanes.
 *
 * Given a set of time intervals (one per booking, clamped to the visible
 * window), assign each to the lowest lane index whose previous interval has
 * already ended by the time this one starts. Two intervals share a lane only
 * when they do not overlap in time, so overlapping bookings are separated onto
 * their own lanes instead of colliding on a single line.
 */
export interface Interval {
  startMs: number;
  endMs: number;
}

/**
 * Returns the lane index for each input interval, positionally aligned to the
 * input array (result[i] is the lane for intervals[i]). Intervals are packed in
 * start-time order (ties broken by end time), but the returned array preserves
 * the caller's original ordering. Touching intervals (one ends exactly when the
 * next starts) are treated as non-overlapping and may share a lane.
 */
export function packLanes(intervals: Interval[]): number[] {
  const order = intervals
    .map((_, i) => i)
    .sort((a, b) => {
      const byStart = intervals[a].startMs - intervals[b].startMs;
      return byStart !== 0 ? byStart : intervals[a].endMs - intervals[b].endMs;
    });

  const laneEnds: number[] = []; // laneEnds[l] = endMs of the last interval in lane l
  const lane: number[] = new Array(intervals.length).fill(0);

  for (const idx of order) {
    const iv = intervals[idx];
    let assigned = -1;
    for (let l = 0; l < laneEnds.length; l++) {
      if (laneEnds[l] <= iv.startMs) {
        assigned = l;
        break;
      }
    }
    if (assigned === -1) {
      assigned = laneEnds.length;
      laneEnds.push(iv.endMs);
    } else {
      laneEnds[assigned] = iv.endMs;
    }
    lane[idx] = assigned;
  }

  return lane;
}

/** Number of lanes used by a lane assignment (0 for an empty set). */
export function laneCount(lanes: number[]): number {
  return lanes.reduce((max, l) => Math.max(max, l + 1), 0);
}
