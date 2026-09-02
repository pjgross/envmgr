/**
 * The cross-release PIR action worklist.
 *
 * A PIR action is a process fix that outlives the release it came from, and
 * inside that release's own tab it is invisible the moment attention moves on.
 * This page is the point of the feature, so what it must get right is that
 * every filter reaches the SERVER and every row identifies itself by name.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import PirActionList from '../PirActionList';
import { store } from '../../../store';
import { pirService } from '../../../services/pirService';
import whitelists from '../../../constants/sortWhitelists.json';
import { getLastDataGridProps } from '../../../test/dataGridMock';

vi.mock('../../../services/pirService', () => ({ pirService: { listActions: vi.fn() } }));

// jsdom reports a zero-width container, so the real DataGrid mounts almost no
// cells. See src/test/dataGridMock.tsx.
vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  const { createDataGridMock } = await import('../../../test/dataGridMock');
  return { ...actual, ...createDataGridMock() };
});

const mocked = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;

const row = (over = {}) => ({
  id: 1, finding_id: 11, finding_title: 'No load test', release_id: 7,
  release_name: 'Release 24.3', pir_status: 'draft', title: 'Make the perf gate mandatory',
  detail: null, owner_id: 5, owner_username: 'alice', due_date: '2026-09-30T00:00:00Z',
  status: 'open', closed_at: null, closure_note: null, is_overdue: true, ...over,
});

beforeEach(() => {
  vi.resetAllMocks();
  mocked.listActions.mockResolvedValue({ rows: [row()], total: 1 });
});

const renderPage = (path = '/pir-actions') =>
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[path]}><PirActionList /></MemoryRouter>
    </Provider>,
  );

describe('PirActionList', () => {
  it('names the release and the finding, never their ids', async () => {
    renderPage();
    expect(await screen.findByText('Release 24.3')).toBeInTheDocument();
    expect(screen.getByText('No load test')).toBeInTheDocument();
    expect(screen.queryByText(/#7|release 7/i)).not.toBeInTheDocument();
  });

  it('links the release by name to the release itself', async () => {
    renderPage();
    expect(await screen.findByRole('link', { name: 'Release 24.3' }))
      .toHaveAttribute('href', '/releases/7');
  });

  it('names the owner rather than the owner id', async () => {
    renderPage();
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.queryByText(/#5/)).not.toBeInTheDocument();
  });

  it('sends the status filter to the server, not to a client-side filter', async () => {
    renderPage();
    await screen.findByText('Release 24.3');
    await userEvent.click(screen.getByLabelText(/status/i));
    await userEvent.click(await screen.findByRole('option', { name: /^open$/i }));
    await waitFor(() => expect(mocked.listActions).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'open' })));
  });

  it('omits the key entirely for no selection, and never sends the word all', async () => {
    renderPage();
    await screen.findByText('Release 24.3');
    const params = mocked.listActions.mock.calls[0][0];
    expect(params).not.toHaveProperty('status');
    expect(Object.values(params)).not.toContain('all');
  });

  it('reads its filters back off the URL so a shared link reproduces the queue',
    async () => {
      renderPage('/pir-actions?status=open&overdue=true');
      await waitFor(() => expect(mocked.listActions).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'open', overdue: true })));
    });

  it('takes the overdue flag from the server rather than comparing dates', async () => {
    mocked.listActions.mockResolvedValue({
      rows: [row({ due_date: '2099-01-01T00:00:00Z', is_overdue: true })], total: 1,
    });
    renderPage();
    // Queried by test id, not by text: the page's own advisory line and the
    // Overdue filter both contain the word, and matching those would pass with
    // the chip deleted entirely.
    expect(await screen.findByTestId('overdue-chip')).toBeInTheDocument();
  });

  it('does not call a row overdue when the server did not', async () => {
    // The complement, and the one that catches a chip hardcoded on.
    mocked.listActions.mockResolvedValue({
      rows: [row({ due_date: '2020-01-01T00:00:00Z', is_overdue: false })], total: 1,
    });
    renderPage();
    await screen.findByText('Release 24.3');
    expect(screen.queryByTestId('overdue-chip')).not.toBeInTheDocument();
  });

  it('shows the total from the server, not the length of the page', async () => {
    mocked.listActions.mockResolvedValue({ rows: [row()], total: 97 });
    renderPage();
    await screen.findByText('Release 24.3');
    await waitFor(() => expect(getLastDataGridProps()?.rowCount).toBe(97));
  });

  it('pages and sorts on the server, and never filters in the browser', async () => {
    renderPage();
    await screen.findByText('Release 24.3');
    const props = getLastDataGridProps();
    expect(props?.paginationMode).toBe('server');
    expect(props?.sortingMode).toBe('server');
    // `rows` is one windowed page — a browser-side column filter would filter
    // the page and report a total for the whole set.
    expect(props?.disableColumnFilter).toBe(true);
  });

  it('marks only whitelisted columns sortable', async () => {
    // A column left sortable whose field the backend does not whitelist gives
    // the user a header that looks clickable and 422s the moment they click it.
    renderPage();
    await screen.findByText('Release 24.3');
    const sortable = (whitelists as Record<string, { sortable: string[] }>)['pir-actions']
      .sortable;
    expect(sortable).toEqual(
      expect.arrayContaining(['title', 'status', 'due_date', 'release', 'owner']));
    expect(sortable).not.toContain('finding_title');
    expect(sortable).not.toContain('is_overdue');

    // And the grid agrees: every column the page marks sortable is a field the
    // whitelist carries. Asserting the JSON alone would pass while the grid
    // offered a sortable header the server refuses.
    const columns = (getLastDataGridProps()?.columns ?? []) as
      { field: string; sortable?: boolean }[];
    const offered = columns.filter((c) => c.sortable !== false).map((c) => c.field);
    expect(offered.every((f) => sortable.includes(f))).toBe(true);
  });
});
