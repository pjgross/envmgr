import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import api from '../../services/api';
import Dashboard from '../Dashboard';
import authReducer, { setCredentials } from '../../store/authSlice';
import contentionForecastReducer from '../../store/contentionForecastSlice';

// No `renderWithStore` helper exists in this codebase for a bare `api.get`
// mock (checked before writing this) — inlined the way
// environmentServicePaged.test.ts / bookingServicePaged.test.ts do.
vi.mock('../../services/api', () => ({
  default: { get: vi.fn() },
}));

const mockedGet = vi.mocked(api.get);

const oneRow = { id: 1, name: 'row-1' };

interface RouteResponse {
  data: unknown;
  headers?: Record<string, string>;
}

/**
 * The Dashboard fires several concurrent GETs (four tiles, the calendar
 * previews, the health overview, the contention-horizon widget, and — for
 * an Admin — two more environment fetches). `mockGet` registers ONE route by
 * URL prefix; the longest registered prefix wins so a specific route (e.g.
 * `/environments/health`) never loses to a shorter one a test also
 * registered (e.g. `/environments`). Anything not explicitly registered
 * falls back to an empty-but-valid response, so every other in-flight
 * fetch a test doesn't care about resolves quietly instead of throwing.
 */
let routes: { pattern: string; response: RouteResponse }[] = [];

function mockGet(pattern: string, response: RouteResponse) {
  routes.push({ pattern, response });
}

const DEFAULT_RESPONSE: RouteResponse = { data: [], headers: { 'x-total-count': '0' } };

beforeEach(() => {
  routes = [];
  mockedGet.mockReset();
  mockedGet.mockImplementation((url: string) => {
    const u = String(url);
    const hit = [...routes].sort((a, b) => b.pattern.length - a.pattern.length).find((r) => u.startsWith(r.pattern));
    const resp = hit?.response ?? DEFAULT_RESPONSE;
    return Promise.resolve({ data: resp.data, headers: resp.headers ?? {} });
  });
});

function renderDashboard(role: string = 'Developer') {
  const store = configureStore({
    reducer: { auth: authReducer, contentionForecast: contentionForecastReducer },
  });
  store.dispatch(
    setCredentials({
      user: { id: 1, username: 'u', email: 'u@example.com', role, tenant_id: 1, is_master_admin: false },
      token: 'test-token',
    })
  );
  return render(
    <Provider store={store}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </Provider>
  );
}

describe('Dashboard', () => {
  it('reads each tile count from X-Total-Count, not from the row array', async () => {
    // The tiles fetch limit=1; a tile that counted `data.length` would show 1.
    mockGet('/environments', { data: [oneRow], headers: { 'x-total-count': '42' } });
    renderDashboard();
    expect(await screen.findByText('42')).toBeInTheDocument();
  });

  it('each tile links to the list with the same filter', async () => {
    renderDashboard();
    expect(await screen.findByRole('link', { name: /active environments/i })).toHaveAttribute(
      'href',
      '/environments?status=active'
    );
  });

  it('renders no Phase-0 placeholder text', async () => {
    renderDashboard();
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByText(/Phase 0/i)).not.toBeInTheDocument();
  });

  it('the releases tile links to the same status it counted', async () => {
    mockGet('/releases', { data: [oneRow], headers: { 'x-total-count': '7' } });
    renderDashboard();
    const link = await screen.findByRole('link', { name: /releases in flight/i });
    expect(link).toHaveAttribute('href', '/releases?status=in_progress');
    expect(await screen.findByText('7')).toBeInTheDocument();
  });

  it('the incidents tile links to the same status it counted', async () => {
    mockGet('/incidents', { data: [oneRow], headers: { 'x-total-count': '3' } });
    renderDashboard();
    const link = await screen.findByRole('link', { name: /open incidents/i });
    expect(link).toHaveAttribute('href', '/incidents?status=open');
    expect(await screen.findByText('3')).toBeInTheDocument();
  });

  it('the bookings tile links at BookingList’s own route, not /bookings (which redirects to the calendar)', async () => {
    mockGet('/bookings/', { data: [oneRow], headers: { 'x-total-count': '5' } });
    renderDashboard();
    const link = await screen.findByRole('link', { name: /bookings live now/i });
    const href = link.getAttribute('href') ?? '';
    expect(href.startsWith('/bookings/list?')).toBe(true);
    expect(href).toContain('start=');
    expect(href).toContain('end=');
    expect(await screen.findByText('5')).toBeInTheDocument();
  });

  it('does not render the Admin-only governance line for a non-Admin', async () => {
    renderDashboard('Developer');
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByText(/governance gap/i)).not.toBeInTheDocument();
  });

  it('renders the Admin-only governance line for an Admin', async () => {
    mockGet('/environments', { data: [], headers: { 'x-total-count': '2' } });
    renderDashboard('Admin');
    expect(await screen.findByText(/governance gap/i)).toBeInTheDocument();
    expect(screen.getByText(/quarantined/i)).toBeInTheDocument();
  });

  it('a tile whose fetch fails renders a dash instead of a stale count', async () => {
    mockedGet.mockReset();
    mockedGet.mockImplementation((url: string) => {
      const u = String(url);
      if (u.startsWith('/environments/health') || u.startsWith('/bookings/contention-horizon')) {
        return Promise.resolve({ data: [], headers: {} });
      }
      return Promise.reject(new Error('network down'));
    });
    renderDashboard();
    const link = await screen.findByRole('link', { name: /active environments/i });
    // All four tiles' own list fetches are rejected above, so several tiles
    // render the failure dash — assert at least one rather than an exact
    // count, which would make this test about how many tiles exist rather
    // than about the failure path.
    expect((await screen.findAllByText('—')).length).toBeGreaterThan(0);
    expect(link).toHaveAttribute('href', '/environments?status=active');
  });
});
