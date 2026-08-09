/**
 * The priority rank on the project admin page — A4's only input.
 *
 * THE LABEL IS THE FEATURE. `priority_rank` is a bare integer whose direction
 * cannot be guessed: 1 is the HIGHEST priority, so a bigger number is a lower
 * one. An admin who guesses the other way round sets ranks that decide every
 * contention backwards, and nothing anywhere would tell them — the verdict
 * would be confidently wrong rather than obviously broken. The backend refuses
 * `0` and negatives (`ge=1`) for exactly that reason, but it cannot refuse a 9
 * that was meant to be a 1.
 *
 * A4 ADVISES; IT NEVER ACTS, and the page has to say so: an admin typing a
 * priority into a governance screen may reasonably expect the lower-priority
 * booking to be moved for them. It is not.
 *
 * The failure path rejects through the slice, which already calls
 * `formatApiError` in `updateProject`'s `rejectWithValue` — so this file
 * asserts the page reads `result.payload`, never `result.error.message`.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import { setCredentials } from '../../../store/authSlice';
import ProjectDetail from '../ProjectDetail';

vi.mock('../../../services/projectService', () => ({
  projectService: {
    getProject: vi.fn(),
    listAgreementsForProject: vi.fn(),
    createAgreement: vi.fn(),
    deleteAgreement: vi.fn(),
    updateProject: vi.fn(),
    listProjects: vi.fn(),
  },
}));
vi.mock('../../../services/bookingService', () => ({
  bookingService: { listBookings: vi.fn(), getAllowedTransitions: vi.fn() },
}));
vi.mock('../../../hooks/useAllEnvironments', () => {
  const value = { environments: [], loading: false, truncated: false };
  return { useAllEnvironments: () => value };
});

import { bookingService } from '../../../services/bookingService';
import { projectService } from '../../../services/projectService';

const PROJECT_ID = 7;

const project = (overrides: Record<string, unknown> = {}) => ({
  id: PROJECT_ID,
  tenant_id: 1,
  name: 'Mortgage Replatform',
  code: 'MTG',
  description: null,
  team_group_id: null,
  team_group_name: null,
  environment_count: 0,
  is_active: true,
  priority_rank: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

function signIn(role: string) {
  store.dispatch(
    setCredentials({
      user: {
        id: 1,
        username: 'admin',
        email: 'admin@test.com',
        role,
        tenant_id: 1,
        is_active: true,
        is_master_admin: false,
      } as never,
      token: 'test-token',
    })
  );
}

function renderPage() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/tenant/projects/${PROJECT_ID}`]}>
        <Routes>
          <Route path="/tenant/projects/:id" element={<ProjectDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(projectService.getProject).mockResolvedValue(project() as never);
  vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({ rows: [], total: 0 });
  vi.mocked(projectService.updateProject).mockResolvedValue(project() as never);
  vi.mocked(bookingService.listBookings).mockResolvedValue({ rows: [], total: 0 });
  signIn('Admin');
});

describe('the priority rank field', () => {
  it('says which direction is higher, right on the field', async () => {
    renderPage();

    const field = await screen.findByLabelText(/Priority rank/i);
    expect(field).toBeInTheDocument();
    // "1 is highest" beside the input itself, not buried in a paragraph
    // somewhere else on the page.
    expect(screen.getByTestId('priority-rank-help')).toHaveTextContent(/1 is highest/i);
  });

  it('says that a rank decides nothing on its own', async () => {
    // A4 ADVISES; IT NEVER ACTS. Nothing about setting a rank moves, refuses or
    // reschedules a booking, and a governance screen that does not say so
    // invites the opposite reading.
    renderPage();

    await screen.findByLabelText(/Priority rank/i);
    expect(screen.getByTestId('priority-rank-advisory').textContent).toMatch(
      /nothing is (moved|blocked|refused)|does not (move|block|refuse)|never (moves|blocks|refuses)/i
    );
  });

  it('shows the rank a project already has', async () => {
    vi.mocked(projectService.getProject).mockResolvedValue(project({ priority_rank: 2 }) as never);
    renderPage();

    await waitFor(() => expect(screen.getByLabelText(/Priority rank/i)).toHaveValue(2));
  });

  it('saves the rank an admin typed', async () => {
    const user = userEvent.setup();
    renderPage();

    const field = await screen.findByLabelText(/Priority rank/i);
    await user.clear(field);
    await user.type(field, '3');
    await user.click(screen.getByRole('button', { name: /Save rank/i }));

    await waitFor(() =>
      expect(projectService.updateProject).toHaveBeenCalledWith(PROJECT_ID, {
        priority_rank: 3,
      })
    );
  });

  it('clears a rank with an explicit null rather than omitting the key', async () => {
    // The backend keys on `model_fields_set`: an omitted key means "leave
    // alone", so only an explicit null unranks a project. An empty box that
    // sent nothing would silently keep the old rank — the contract B1 gave
    // `expires_at` and A1 gave `team_group_id`.
    const user = userEvent.setup();
    vi.mocked(projectService.getProject).mockResolvedValue(project({ priority_rank: 2 }) as never);
    renderPage();

    const field = await screen.findByLabelText(/Priority rank/i);
    await waitFor(() => expect(field).toHaveValue(2));
    await user.clear(field);
    await user.click(screen.getByRole('button', { name: /Save rank/i }));

    await waitFor(() =>
      expect(projectService.updateProject).toHaveBeenCalledWith(PROJECT_ID, {
        priority_rank: null,
      })
    );
  });

  it('refuses a draft that is not a whole number rather than silently clearing the rank', async () => {
    // `Number('1.5')` is 1.5 and `Number('abc')` is NaN — and NaN SERIALISES TO
    // JSON `null`, which is this field's wire form for "unrank this project".
    // Sending it would therefore CLEAR the rank of a project the admin was
    // trying to rank, with a 200 and no complaint: the same silent failure the
    // explicit null exists to prevent, arriving from the opposite direction.
    const user = userEvent.setup();
    vi.mocked(projectService.getProject).mockResolvedValue(project({ priority_rank: 2 }) as never);
    renderPage();

    const field = await screen.findByLabelText(/Priority rank/i);
    await waitFor(() => expect(field).toHaveValue(2));
    await user.clear(field);
    await user.type(field, '1.5');
    await user.click(screen.getByRole('button', { name: /Save rank/i }));

    expect(await screen.findByText(/whole number/i)).toBeInTheDocument();
    // Nothing was sent at all — emphatically not `{ priority_rank: null }`.
    expect(projectService.updateProject).not.toHaveBeenCalled();
  });

  it("shows the server's reason when a rank is refused", async () => {
    const user = userEvent.setup();
    vi.mocked(projectService.updateProject).mockRejectedValue({
      isAxiosError: true,
      name: 'AxiosError',
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { detail: [{ loc: ['body', 'priority_rank'], msg: 'Input should be >= 1' }] },
      },
    });
    renderPage();

    const field = await screen.findByLabelText(/Priority rank/i);
    await user.clear(field);
    await user.type(field, '0');
    await user.click(screen.getByRole('button', { name: /Save rank/i }));

    expect(await screen.findByText(/priority_rank: Input should be >= 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
  });

  it('shows a non-admin the rank without offering to change it', async () => {
    // Same read/write split as the rest of this page: GET /projects/{id} is
    // open to any tenant member, PATCH is require_tenant_admin().
    signIn('Developer');
    vi.mocked(projectService.getProject).mockResolvedValue(project({ priority_rank: 2 }) as never);
    renderPage();

    expect(await screen.findByTestId('priority-rank-readonly')).toHaveTextContent('2');
    expect(screen.getByTestId('priority-rank-readonly')).toHaveTextContent(/1 is highest/i);
    expect(screen.queryByRole('button', { name: /Save rank/i })).not.toBeInTheDocument();
  });

  it('tells a reader that an unranked project is unranked, not that it is rank zero', async () => {
    // Null is a REAL STATE — "no rank" — and A4 treats it as one: a ranked
    // project does NOT beat an unranked one, the verdict is `unranked` with its
    // own reason. Rendering it as `0` would read as the highest rank there is.
    signIn('Developer');
    renderPage();

    const line = await screen.findByTestId('priority-rank-readonly');
    expect(line).toHaveTextContent(/not ranked/i);
    expect(line.textContent).not.toMatch(/\b0\b/);
  });
});
