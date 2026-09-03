import { beforeEach, describe, expect, it, vi } from 'vitest';
import reducer, { setLastAppRoute, setNavGroupOpen } from '../uiSlice';

const NAV_KEY = 'ui.navOpenGroups';

describe('uiSlice nav state', () => {
  beforeEach(() => localStorage.clear());

  it('defaults lastAppRoute to /dashboard and navOpenGroups to empty', () => {
    const state = reducer(undefined, { type: 'init' });
    expect(state.lastAppRoute).toBe('/dashboard');
    expect(state.navOpenGroups).toEqual({});
  });

  it('records the last app route', () => {
    const state = reducer(undefined, setLastAppRoute('/releases/calendar?x=1'));
    expect(state.lastAppRoute).toBe('/releases/calendar?x=1');
  });

  it('persists group open state to localStorage', () => {
    const state = reducer(undefined, setNavGroupOpen({ key: 'app:Bookings', open: false }));
    expect(state.navOpenGroups['app:Bookings']).toBe(false);
    expect(JSON.parse(localStorage.getItem(NAV_KEY) ?? '{}')).toEqual({ 'app:Bookings': false });
  });

  it('survives corrupt localStorage', async () => {
    // initialState is built once at module load (see the sibling test below),
    // so the corrupt value must be in place BEFORE the module is (re-)imported
    // or readNavGroups() never sees it.
    localStorage.setItem(NAV_KEY, '{not json');
    vi.resetModules();
    const fresh = (await import('../uiSlice')).default;
    const state = fresh(undefined, { type: 'init' });
    expect(state.navOpenGroups).toEqual({});
  });

  it('restores collapsed groups from localStorage on a fresh module load', async () => {
    // initialState is built once at module load, so a second configureStore in
    // the same module instance would reuse it rather than re-reading storage —
    // vi.resetModules() forces the initializer to run again against what's there.
    localStorage.setItem('ui.navOpenGroups', JSON.stringify({ 'app:Catalogue': false }));
    vi.resetModules();
    const fresh = (await import('../uiSlice')).default;
    const state = fresh(undefined, { type: 'init' });
    expect(state.navOpenGroups).toEqual({ 'app:Catalogue': false });
  });
});
