import { describe, expect, it } from 'vitest';
import { packLanes, laneCount, type Interval } from '../bookingLanes';

const iv = (startMs: number, endMs: number): Interval => ({ startMs, endMs });

describe('packLanes', () => {
  it('returns an empty array for no intervals', () => {
    const lanes = packLanes([]);
    expect(lanes).toEqual([]);
    expect(laneCount(lanes)).toBe(0);
  });

  it('keeps non-overlapping intervals on a single lane', () => {
    const lanes = packLanes([iv(0, 10), iv(20, 30), iv(40, 50)]);
    expect(lanes).toEqual([0, 0, 0]);
    expect(laneCount(lanes)).toBe(1);
  });

  it('puts two overlapping intervals on separate lanes', () => {
    const lanes = packLanes([iv(0, 30), iv(10, 40)]);
    expect(laneCount(lanes)).toBe(2);
    expect(lanes[0]).not.toBe(lanes[1]);
  });

  it('uses three lanes when three intervals all overlap', () => {
    const lanes = packLanes([iv(0, 30), iv(5, 35), iv(10, 40)]);
    expect(laneCount(lanes)).toBe(3);
    expect(new Set(lanes).size).toBe(3);
  });

  it('reuses a freed lane after an interval ends', () => {
    // A(0-30) & B(10-40) overlap → 2 lanes. C(35-50) starts after A ends,
    // so it should reuse lane 0 rather than open a third lane.
    const lanes = packLanes([iv(0, 30), iv(10, 40), iv(35, 50)]);
    expect(laneCount(lanes)).toBe(2);
    expect(lanes[2]).toBe(0);
  });

  it('treats touching intervals (end === next start) as non-overlapping', () => {
    const lanes = packLanes([iv(0, 10), iv(10, 20)]);
    expect(laneCount(lanes)).toBe(1);
  });

  it('preserves input ordering in the result regardless of start order', () => {
    // Input given out of time order; result[i] must correspond to intervals[i].
    const lanes = packLanes([iv(10, 40), iv(0, 30)]);
    // The two overlap → 2 lanes; the earlier-starting one (index 1) packs first.
    expect(laneCount(lanes)).toBe(2);
    expect(lanes[0]).not.toBe(lanes[1]);
  });
});
