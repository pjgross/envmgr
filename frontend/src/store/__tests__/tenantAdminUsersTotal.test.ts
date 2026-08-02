import { describe, expect, it } from 'vitest';
import reducer, { fetchUsers } from '../tenantAdminSlice';

/**
 * GET /tenant/users is capped server-side. Three components read this slice —
 * two of them as a picker, and BookingForm filters it to active users, so the
 * number of visible options bears no relation to the cap. Without the total
 * there is no way to tell a complete user list from a truncated one.
 */
describe('tenantAdmin users total', () => {
  const initial = reducer(undefined, { type: '@@INIT' });

  it('keeps the server total alongside the rows', () => {
    const next = reducer(initial, {
      type: fetchUsers.fulfilled.type,
      payload: { rows: [{ id: 1, username: 'a' }], total: 900 },
    });
    expect(next.users).toHaveLength(1);
    expect(next.usersTotal).toBe(900);
  });

  it('starts at zero rather than undefined, so consumers can compare on first render', () => {
    // users.length < usersTotal must be false before the fetch resolves, not
    // NaN-ish — otherwise every picker flashes a truncation warning on mount.
    expect(initial.usersTotal).toBe(0);
    expect(initial.users.length < initial.usersTotal).toBe(false);
  });
});
