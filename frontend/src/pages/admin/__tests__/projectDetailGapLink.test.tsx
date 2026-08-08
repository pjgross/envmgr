// The real `App.tsx`, as text. `?raw` is Vite's own primitive (typed by
// `vite/client`, referenced from src/vite-env.d.ts) — deliberately not
// `node:fs` + `process.cwd()`, which work at runtime but are untyped in this
// package's tsconfig (no `@types/node`, `lib: ES2020`) and would fail
// `tsc --noEmit`. It is the REAL file, not a fixture: a fixture would only
// prove this test agrees with itself.
import appSource from '../../../App.tsx?raw';

import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import ProjectDetail from '../ProjectDetail';
import BookingList from '../../bookings/BookingList';

/**
 * The join between ProjectDetail's "bookings in gap" rollup and the list it
 * links to (Phase 7 A3, Task 7 Step 2).
 *
 * WHY THIS FILE EXISTS RATHER THAN AN href ASSERTION. A1 shipped a count
 * linking to `/environments?project_id=…`, a filter that endpoint has never
 * accepted; FastAPI drops an unknown query param silently, so the page showed
 * the entire estate as one project's environments — and a test asserting the
 * href against a hand-written copy of itself passed, as did the admin guide.
 * An href is only ever half the contract. The other half is that the consumer
 * READS those keys, and nothing on either side errors when it does not:
 * `useServerGrid` simply never hydrates a key absent from `filterKeys`, and
 * the grid then renders every booking in the tenant under a heading that says
 * otherwise.
 *
 * So this test takes the href ProjectDetail actually rendered, hands it to a
 * real `BookingList`, and asserts the request that page issues carries the
 * filter. It fails if `project_id` or `agreement_gap` is dropped from
 * `filterKeys`, if `apiAgreementGap` stops recognising `true`, if the href
 * changes shape — and, via the last test, if the route the href names is
 * renamed in `App.tsx`.
 */

vi.mock('../../../services/projectService', () => ({
  projectService: {
    getProject: vi.fn(),
    listAgreementsForProject: vi.fn(),
    createAgreement: vi.fn(),
    deleteAgreement: vi.fn(),
    // BookingList's Project filter picker (useAllProjects).
    listProjects: vi.fn(),
  },
}));

vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn(),
    getAllowedTransitions: vi.fn(),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn(),
  },
}));

// ONE object, returned by every call — not a fresh literal per render. Both
// ProjectDetail and the BookingForm dialog BookingList mounts read this hook,
// and a new `environments` array each render re-fires the effects keyed on it,
// which spins the render loop forever rather than failing.
vi.mock('../../../hooks/useAllEnvironments', () => {
  const value = { environments: [], loading: false, truncated: false };
  return { useAllEnvironments: () => value };
});

import { bookingService } from '../../../services/bookingService';
import { customFieldService } from '../../../services/customFieldService';
import { projectService } from '../../../services/projectService';

const PROJECT = {
  id: 7,
  tenant_id: 1,
  name: 'Mortgage',
  code: 'MTG',
  description: null,
  team_group_id: null,
  team_group_name: null,
  environment_count: 0,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(projectService.getProject).mockResolvedValue(PROJECT);
  vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({ rows: [], total: 0 });
  vi.mocked(projectService.listProjects).mockResolvedValue({ rows: [], total: 0 });
  vi.mocked(customFieldService.listDefinitions).mockResolvedValue([]);
  vi.mocked(bookingService.listBookings).mockResolvedValue({ rows: [], total: 3 });
  vi.mocked(bookingService.getAllowedTransitions).mockResolvedValue([]);
});

/** Render ProjectDetail and hand back the href of its gap rollup link. */
async function renderedGapHref(): Promise<string> {
  const view = render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/tenant/projects/7']}>
        <Routes>
          <Route path="/tenant/projects/:id" element={<ProjectDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
  const link = await screen.findByRole('link', { name: /in gap/i });
  const href = link.getAttribute('href') ?? '';
  view.unmount();
  return href;
}

describe("ProjectDetail's gap rollup link", () => {
  it('lands BookingList already filtered to this project AND to the gap', async () => {
    const href = await renderedGapHref();
    // Only ProjectDetail's own count has been issued so far; clear it so the
    // assertion below reads BookingList's request, not the rollup's.
    vi.mocked(bookingService.listBookings).mockClear();

    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={[href]}>
          <BookingList />
        </MemoryRouter>
      </Provider>
    );

    await vi.waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    const calls = vi.mocked(bookingService.listBookings).mock.calls;
    const params = calls[calls.length - 1]?.[0];
    // Not `toMatchObject` on a literal: these are the values the LINK carries,
    // read back out of it, so the two sides cannot drift apart in this test.
    const url = new URL(href, 'http://localhost');
    expect(params?.project_id).toBe(Number(url.searchParams.get('project_id')));
    expect(params?.agreement_gap).toBe(true);
  });

  it('names a route App.tsx actually declares', async () => {
    // The other way this link can silently stop working: the href stays
    // correct and the ROUTE moves. React Router renders nothing for an
    // unmatched path, so the user gets a blank page rather than an error, and
    // every test that mounts BookingList directly still passes. Read from the
    // real App.tsx rather than a fixture — a fixture would only prove this
    // test agrees with itself.
    const href = await renderedGapHref();
    const pathname = new URL(href, 'http://localhost').pathname;
    // Guard against the import silently resolving to nothing: an empty string
    // would make the `toContain` below vacuous rather than failing.
    expect(appSource).toContain('<Routes>');
    expect(appSource).toContain(`path="${pathname}"`);
  });
});
