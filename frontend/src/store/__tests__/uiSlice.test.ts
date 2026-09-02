import { beforeEach, describe, expect, it } from 'vitest';
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

  it('survives corrupt localStorage', () => {
    localStorage.setItem(NAV_KEY, '{not json');
    const state = reducer(undefined, setNavGroupOpen({ key: 'app:Releases', open: true }));
    expect(state.navOpenGroups).toEqual({ 'app:Releases': true });
  });
});
