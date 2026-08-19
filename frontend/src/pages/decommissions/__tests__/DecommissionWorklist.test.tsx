/**
 * The decommission worklist — every decommission a tenant can see, live and
 * terminal alike, following `EscalationWorklist` (A4's precedent): server
 * paged from the first render, `?state=` filtered on the wire with `any`
 * (never `all`) as the "no selection" sentinel, and the total read off
 * `X-Total-Count`, never `rows.length`.
 *
 * Unlike the escalation worklist, this page drives its fetch through the
 * REDUX THUNK (`fetchDecommissionWorklist`, already shipped with no UI
 * caller before this task) rather than calling the service directly — so
 * these tests mock `decommissionService.listWorklist`, the one seam the real
 * thunk/reducer sit behind, and let the real store apply the real reducer.
 *
 * jsdom cannot reliably render MUI DataGrid cells (a zero-width container
 * mounts almost none of them), so — following
 * `environmentIdleColumn.test.tsx` and `escalationWorklist.test.tsx` — the
 * DataGrid is replaced with an unvirtualized stand-in that renders every
 * column's cell for every row through the column's own renderCell, and
 * captures the props the page passed (needed for the
 * paginationMode/sortingMode/disableColumnFilter assertions, which have no
 * DOM form at all).
 */
import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import type { DecommissionWorklistRow } from '../../../types/decommission';

vi.mock('../../../services/decommissionService', () => ({
  decommissionService: {
    getForEnvironment: vi.fn(),
    initiate: vi.fn(),
    requestExtension: vi.fn(),
    decideExtension: vi.fn(),
    signAttestation: vi.fn(),
    tearDown: vi.fn(),
    cancel: vi.fn(),
    listSteps: vi.fn(),
    listWorklist: vi.fn(),
  },
}));

const { capturedGridProps } = vi.hoisted(() => ({
  capturedGridProps: { current: undefined as Record<string, unknown> | undefined },
}));

vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  return {
    ...actual,
    DataGrid: (props: Record<string, unknown>) => {
      capturedGridProps.current = props;
      const rows = props.rows as Array<Record<string, unknown>>;
      const columns = props.columns as Array<{
        field: string;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        renderCell?: (params: any) => ReactNode;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        valueGetter?: (params: any) => unknown;
      }>;
      return (
        <table>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)} data-testid={`row-${row.id}`}>
                {columns.map((col) => (
                  <td key={col.field}>
                    {col.renderCell
                      ? col.renderCell({ row, value: row[col.field], id: row.id })
                      : col.valueGetter
                        ? String(col.valueGetter({ row }))
                        : String(row[col.field] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    },
  };
});

import { decommissionService } from '../../../services/decommissionService';
import DecommissionWorklist from '../DecommissionWorklist';

function row(overrides: Partial<DecommissionWorklistRow> = {}): DecommissionWorklistRow {
  return {
    id: 501,
    environment_id: 42,
    reason: 'Project retired',
    warned_at: '2026-08-01T00:00:00Z',
    scheduled_teardown_at: '2026-08-15T00:00:00Z',
    initiated_by: 3,
    extension_requested_at: null,
    extension_reason: null,
    extension_until: null,
    extension_decided_at: null,
    extension_granted: null,
    torn_down_at: null,
    cancelled_at: null,
    cancel_reason: null,
    state: 'due',
    attestations: [],
    environment_name: 'Staging Alpha',
    initiated_by_username: 'alice',
    owner_username: 'bob',
    ...overrides,
  };
}

function renderPage(initialEntry = '/decommissions') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DecommissionWorklist />
      </MemoryRouter>
    </Provider>
  );
}

beforeEach(() => {
  capturedGridProps.current = undefined;
  vi.mocked(decommissionService.listWorklist)
    .mockReset()
    .mockResolvedValue({ rows: [row()], total: 1 });
});

describe('the worklist', () => {
  it('identifies each row by name — environment, owner, initiator — never a bare id', async () => {
    renderPage();

    const r = await screen.findByTestId('row-501');
    expect(r).toHaveTextContent('Staging Alpha');
    expect(r).toHaveTextContent('bob');
    expect(r).toHaveTextContent('alice');
    expect(r.textContent).not.toMatch(/#\s*501/);
    expect(r.textContent).not.toMatch(/Decommission #/);
  });

  it('shows the state the server computed, without re-deriving it', async () => {
    renderPage();

    const r = await screen.findByTestId('row-501');
    expect(r).toHaveTextContent(/due/i);
  });

  it('is server-paged and server-sorted from the first render, never filtered in the browser', async () => {
    renderPage();
    await screen.findByTestId('row-501');

    expect(decommissionService.listWorklist).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 25, offset: 0 })
    );
    expect(capturedGridProps.current?.paginationMode).toBe('server');
    expect(capturedGridProps.current?.sortingMode).toBe('server');
    // `rows` is one windowed page, not the whole result set — a browser-side
    // column filter would filter the page and report a total for the set.
    expect(capturedGridProps.current?.disableColumnFilter).toBe(true);
  });

  it('takes its row count from X-Total-Count, never from the page length', async () => {
    // DISCRIMINATION PROOF (b): derive rowCount from the array length instead
    // and this must fail. Twelve rows total, this page holds one.
    vi.mocked(decommissionService.listWorklist).mockResolvedValue({
      rows: [row()],
      total: 12,
    });
    renderPage();
    await screen.findByTestId('row-501');

    expect(capturedGridProps.current?.rowCount).toBe(12);
  });

  it('filters by state in the request, not in the browser', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-501');

    await user.click(screen.getByRole('button', { name: 'Due' }));

    await waitFor(() =>
      expect(decommissionService.listWorklist).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'due' })
      )
    );
  });

  it('sends no state at all for "All" — omission is the sentinel, not a value', async () => {
    // DISCRIMINATION PROOF (a): spell "no selection" `all` instead of `any`
    // and this must fail — `all` is `buildParams`' own sentinel, dropped
    // before a request is built, so both chips would build byte-identical
    // params and the grid would never refetch (never call `listWorklist` a
    // second time at all, let alone with `state` absent).
    //
    // Asserted via a JSON round-trip rather than `toHaveProperty` directly:
    // `fetchDecommissionWorklist` (the already-shipped thunk) always
    // destructures and re-passes a `state` KEY to `decommissionService
    // .listWorklist` — `undefined` when the page omits it from the
    // dispatch — so the raw call arg legitimately has an own `state`
    // property set to `undefined`. That is exactly what reaches the wire as
    // an omission: axios's query serializer drops `undefined`-valued keys,
    // same as `JSON.stringify` does, which is why the earlier discrimination
    // run (state spelled `all`) produced a call carrying `state: 'due'`
    // still — never `state: undefined` — while this run does not.
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-501');

    await user.click(screen.getByRole('button', { name: 'Due' }));
    await waitFor(() =>
      expect(decommissionService.listWorklist).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'due' })
      )
    );

    await user.click(screen.getByRole('button', { name: 'All' }));

    await waitFor(() => {
      const calls = vi.mocked(decommissionService.listWorklist).mock.calls;
      const last = calls[calls.length - 1]?.[0];
      expect(JSON.parse(JSON.stringify(last))).not.toHaveProperty('state');
    });
  });

  it('opens on the soonest scheduled teardown, sorted by the server', async () => {
    renderPage();
    await screen.findByTestId('row-501');

    expect(decommissionService.listWorklist).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'scheduled_teardown_at', sort_dir: 'asc' })
    );
  });

  it('offers no column the server would answer with a 422', async () => {
    const { default: whitelists } = await import('../../../constants/sortWhitelists.json');
    renderPage();
    await screen.findByTestId('row-501');

    const columns = capturedGridProps.current?.columns as Array<{
      field: string;
      sortable?: boolean;
    }>;
    const sortable = whitelists['decommissions' as keyof typeof whitelists].sortable;
    columns
      .filter((c) => c.sortable !== false)
      .forEach((c) => expect(sortable).toContain(c.field));
    // `state` above all — computed from three columns and a clock, never a
    // column `apply_sort` can order by.
    const stateColumn = columns.find((c) => c.field === 'state');
    expect(stateColumn?.sortable).toBe(false);
  });

  it('shows an error from the server, not a generic status-code message', async () => {
    vi.mocked(decommissionService.listWorklist).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'The decommission worklist could not be read' } },
    });
    renderPage();

    expect(
      await screen.findByText('The decommission worklist could not be read')
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
  });
});

describe('reachability', () => {
  it('is routed in the real App and linked from the real nav', async () => {
    const { default: appSource } = await import('../../../App.tsx?raw');
    const { navGroups } = await import('../../../components/navConfig');

    expect(appSource).toContain('path="/decommissions"');
    expect(appSource).toContain('pages/decommissions/DecommissionWorklist');

    const paths = navGroups.flatMap((g) => (g.children ?? []).map((c) => c.path));
    expect(paths).toContain('/decommissions');
  });
});
