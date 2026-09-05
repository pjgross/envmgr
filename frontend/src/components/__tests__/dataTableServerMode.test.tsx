import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DataTable from '../DataTable';

const columns = [{ field: 'name', headerName: 'Name' }];
const rows = [{ id: 1, name: 'alpha' }];

describe('DataTable server mode', () => {
  // Covers: the footer reflects the server-supplied `rowCount` (317) rather
  // than `rows.length` (1). Does NOT cover the `initialState` guard this
  // file is otherwise about — a controlled `paginationModel` prop (as
  // supplied here) wins over `initialState` at the selector level from the
  // very first render (`registerControlState` in @mui/x-data-grid's
  // useGridPaginationModel), so this test passes identically whether the
  // guard is present, reverted, or inverted. See the "uncontrolled
  // paginationModel" tests below for the case that does observe the guard.
  it('reports the server total rather than the row count', () => {
    render(
      <DataTable
        storageKey="test-grid"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        paginationModel={{ page: 0, pageSize: 25 }}
        onPaginationModelChange={vi.fn()}
      />
    );
    // The footer must say 317, not 1 — that difference is the whole point.
    expect(screen.getByText(/317/)).toBeInTheDocument();
  });

  // Covers: DataTable still renders a working client-side grid (default
  // `paginationMode`, no `rowCount`) with the forced pageSize=25 default in
  // play. Does NOT cover the server-mode guard — there's no server mode
  // here at all, so this test can't tell the guard apart from its absence.
  it('still works as a client-side grid when server props are omitted', () => {
    render(<DataTable storageKey="test-grid" rows={rows} columns={columns} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
  });

  // The two tests above render a real DataGrid but both supply a controlled
  // `paginationModel`, which makes the `initialState` guard unobservable
  // (see comments above). The tests below use the "uncontrolled"
  // shape instead — a server-mode caller that omits `paginationModel` /
  // `onPaginationModelChange` entirely. That shape is type-valid and
  // MUI-supported, and per `paginationStateInitializer` in
  // @mui/x-data-grid's useGridPagination, MUI only ignores `initialState`
  // once `props.paginationModel` is non-null — so with no controlled prop,
  // `initialState` (or its absence) is exactly what determines the
  // rendered page size. That makes the guard observable in the DOM.

  it('does not force the client pageSize default onto an uncontrolled server-mode grid', () => {
    render(
      <DataTable
        storageKey="test-grid-uncontrolled"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
      />
    );
    // With the guard intact, DataTable passes through no client default,
    // so MUI falls back to its own server-mode default page size (100):
    // "1–100 of 317". If the guard is reverted (or its condition
    // inverted), the forced client default of 25 leaks in and the footer
    // reads "1–25 of 317" instead.
    expect(screen.getByText('1–100 of 317')).toBeInTheDocument();
  });

  // Covers: a server-mode caller's own `initialState` reaches DataGrid and
  // takes effect, rather than being silently dropped — e.g. if the JSX
  // stopped spreading `{...rest}` onto <DataGrid>, or if `initialState`
  // were destructured out of `rest` without being forwarded. Does NOT
  // cover the specific literal mutation "replace the ternary's server
  // branch (`rest.initialState`) with a hardcoded `undefined`": verified
  // (with a temporary prop-capturing probe against the real DataGrid, not
  // just this test) that mutation is behaviorally inert given the current
  // JSX. In DataTable.tsx, `{...rest}` is spread onto <DataGrid> *after*
  // the computed `initialState` prop, and `rest` still carries the
  // caller's own `initialState` — so whenever a caller supplies one, that
  // spread always wins over the ternary's result regardless of what the
  // ternary computed. And when a caller supplies none, `rest.initialState`
  // is `undefined` in both the real ternary and the hardcoded-`undefined`
  // mutant, so there's nothing to tell apart. No test, black-box or
  // mock-based, can distinguish that mutation from the real code.
  it('still forwards a server-mode caller\'s own initialState', () => {
    render(
      <DataTable
        storageKey="test-grid-uncontrolled-initial-state"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        initialState={{ pagination: { paginationModel: { page: 0, pageSize: 50 } } }}
      />
    );
    // If the caller's initialState were silently dropped, MUI's server
    // default of 100 would win instead and the footer would read
    // "1–100 of 317".
    expect(screen.getByText('1–50 of 317')).toBeInTheDocument();
  });

  // Covers: a server-mode grid's rows are one windowed page of a much larger
  // result set. The toolbar's Filters panel filters only what's in `rows`
  // while the footer keeps showing the server-supplied `rowCount` — the grid
  // would lie about what it's showing. `disableColumnFilter` must default to
  // true for server mode so no column-filter entry point exists at all.
  it('disables column filtering by default in server mode', () => {
    render(
      <DataTable
        storageKey="test-grid-server-filter"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        paginationModel={{ page: 0, pageSize: 25 }}
        onPaginationModelChange={vi.fn()}
        showToolbar
      />
    );
    expect(screen.queryByRole('button', { name: /filters/i })).not.toBeInTheDocument();
  });

  // Covers: the server-mode default must not leak backwards onto client-mode
  // callers, who still filter (and export) exactly what's in `rows` — that's
  // correct there, since `rows` already is the whole result set.
  it('still offers column filtering by default in client mode', () => {
    render(
      <DataTable storageKey="test-grid-client-filter" rows={rows} columns={columns} showToolbar />
    );
    expect(screen.getByRole('button', { name: /filters/i })).toBeInTheDocument();
  });

  // Covers: `disableColumnFilter` gates the Filters panel but MUI wires
  // GridToolbarExport's csv/print export independently — it exports
  // whatever rows are currently in the grid (one windowed page) while the
  // footer keeps advertising the server-side `rowCount`. Same "the grid
  // lies about what it's showing" defect as the Filters panel, just for
  // export. `slotProps.toolbar.{csvOptions,printOptions}.disableToolbarButton`
  // must suppress the Export button entirely in server mode.
  it('offers no export button on a server-mode grid', () => {
    render(
      <DataTable
        storageKey="test-grid-server-export"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        paginationModel={{ page: 0, pageSize: 25 }}
        onPaginationModelChange={vi.fn()}
        showToolbar
      />
    );
    expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument();
  });

  // Covers: the server-mode export suppression must not leak backwards onto
  // client-mode callers — `rows` there already is the whole result set, so
  // export is correct as-is and must stay offered.
  it('still offers an export button on a client-mode grid', () => {
    render(
      <DataTable storageKey="test-grid-client-export" rows={rows} columns={columns} showToolbar />
    );
    expect(screen.getByRole('button', { name: /export/i })).toBeInTheDocument();
  });
});

describe('hideFooter does not silently cap client-mode rows at 25', () => {
  // `pagination: true` is a forced prop on the MIT DataGrid — `hideFooter`
  // only hides the pager UI, so before this fix a client-mode caller that
  // hides the footer to render every row (the enterprise rollup tabs:
  // MembersTab's three grids, SystemsRollupTab) was still paged by
  // DataTable's own `pageSize: 25` default, with no footer control left to
  // reach rows past the first page. With the guard, such a caller falls back
  // to MUI's own un-paged-looking client default (100) instead.
  //
  // Uses the same "uncontrolled paginationModel" shape as the server-mode
  // `initialState` tests above: with no controlled `paginationModel` prop,
  // `initialState` (or its absence) is what determines the rendered page
  // size, which is what makes the guard observable by rendering more than
  // 25 rows and checking they all appear (this component doesn't render a
  // footer to read a page-size figure from).
  const manyRows = Array.from({ length: 40 }, (_, i) => ({ id: i, name: `row-${i}` }));

  it('renders more than 25 rows when hideFooter is set, with no initialState of its own', () => {
    render(
      <DataTable
        storageKey="test-grid-hidefooter"
        rows={manyRows}
        columns={columns}
        hideFooter
        disableVirtualization
      />
    );
    // If the client-mode default of 25 leaked through, row 30 would not be
    // rendered at all — DataGrid drops rows past the current page rather
    // than merely hiding them, footer or not.
    expect(screen.getByText('row-30')).toBeInTheDocument();
  });

  it('still caps an ordinary client-mode grid (no hideFooter) at the 25-row default', () => {
    render(
      <DataTable
        storageKey="test-grid-no-hidefooter"
        rows={manyRows}
        columns={columns}
        disableVirtualization
      />
    );
    expect(screen.queryByText('row-30')).not.toBeInTheDocument();
    expect(screen.getByText('row-24')).toBeInTheDocument();
  });

  it('lets a hideFooter caller still supply its own initialState', () => {
    render(
      <DataTable
        storageKey="test-grid-hidefooter-initial-state"
        rows={manyRows}
        columns={columns}
        hideFooter
        disableVirtualization
        initialState={{ pagination: { paginationModel: { page: 0, pageSize: 5 } } }}
      />
    );
    expect(screen.getByText('row-4')).toBeInTheDocument();
    expect(screen.queryByText('row-5')).not.toBeInTheDocument();
  });

  it('does not disturb the existing server-mode branch of the same guard', () => {
    render(
      <DataTable
        storageKey="test-grid-hidefooter-server"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        hideFooter
        initialState={{ pagination: { paginationModel: { page: 0, pageSize: 50 } } }}
      />
    );
    // Server mode already skipped the client default before this fix — a
    // server-mode caller's own initialState must keep working unchanged
    // whether or not it also passes hideFooter.
    expect(screen.getByText('alpha')).toBeInTheDocument();
  });
});

describe('empty-state overlay is actually given room to render', () => {
  // MUI's DataGrid only reserves layout height for the noRows/noResults/
  // loading overlay when `autoHeight` is set (see DataTable.tsx's comment on
  // `hasNoRows` for the underlying MUI source paths) — without it, a grid
  // with zero rows collapses its virtual scroller to ~0px and the overlay's
  // text sits inside a box with no height. Confirmed in a real browser: the
  // overlay's `textContent` was present but its bounding rect was 0x0 on
  // `/pir-actions?overdue=true` and `/environments?search=zzzznomatch`
  // before this fix, and a real, painted rect on both afterwards.
  //
  // jsdom lays out nothing (every element reports a zero bounding rect
  // regardless of CSS), so no assertion here can observe the actual pixel
  // height the way the browser evidence above does. What CAN be observed in
  // jsdom is which code path MUI took: an `autoHeight` grid stamps its root
  // with the `MuiDataGrid-autoHeight` class (see GridRootStyles.js's
  // `&.${gridClasses.autoHeight}` rule) and a non-`autoHeight` grid does not.
  // That class is the mechanism this fix relies on, not a proxy for it, so
  // asserting its presence/absence *does* prove DataTable is choosing the
  // MUI code path this fix depends on for each case — it does not, by
  // itself, prove a real browser paints a non-zero box, which is why the
  // browser evidence above is recorded alongside it.
  it('switches the grid onto the autoHeight code path when there are no rows', () => {
    const { container } = render(
      <DataTable
        storageKey="test-grid-empty"
        rows={[]}
        columns={columns}
        emptyMessage="No rows match these filters."
      />
    );
    expect(screen.getByText('No rows match these filters.')).toBeInTheDocument();
    expect(container.querySelector('.MuiDataGrid-root')).toHaveClass('MuiDataGrid-autoHeight');
  });

  // Regression guard for the "must not change a working grid" constraint:
  // a populated grid must stay on the exact code path it already used before
  // this fix — no `autoHeight` class, no behaviour change.
  it('leaves a populated grid off the autoHeight code path', () => {
    const { container } = render(
      <DataTable storageKey="test-grid-populated" rows={rows} columns={columns} />
    );
    expect(container.querySelector('.MuiDataGrid-root')).not.toHaveClass('MuiDataGrid-autoHeight');
  });

  // A caller that sets `autoHeight` itself must still win, empty rows or not
  // — DataTable's default must be a default, not a forced override.
  it('lets a caller-supplied autoHeight override the default even with no rows', () => {
    const { container } = render(
      <DataTable
        storageKey="test-grid-empty-override"
        rows={[]}
        columns={columns}
        autoHeight={false}
      />
    );
    expect(container.querySelector('.MuiDataGrid-root')).not.toHaveClass('MuiDataGrid-autoHeight');
  });
});

describe('persisted column visibility', () => {
  beforeEach(() => localStorage.clear());

  it('re-reads storage when the key changes after mount', () => {
    // The saved model for user 7. A page whose `user` arrives from an async
    // auth fetch mounts with userId undefined and re-renders with 7; reading
    // storage only in the useState initialiser loses the preference silently.
    localStorage.setItem('grid-7', JSON.stringify({ b: false }));
    const rereadColumns = [
      { field: 'a', headerName: 'A' },
      { field: 'b', headerName: 'B' },
    ];
    const rereadRows = [{ id: 1, a: 'one', b: 'two' }];

    // `disableVirtualization` is load-bearing, not decoration: the real
    // DataGrid virtualizes columns by container width and jsdom reports zero
    // width, so column `b`'s cells might never mount at all — and this test
    // would then pass for the wrong reason, asserting the absence of
    // something that was never rendered. It passes through `{...rest}`.
    const { rerender } = render(
      <DataTable
        storageKey="grid"
        rows={rereadRows}
        columns={rereadColumns}
        showToolbar={false}
        disableVirtualization
      />
    );
    expect(screen.getByText('two')).toBeInTheDocument();

    rerender(
      <DataTable
        storageKey="grid"
        userId={7}
        rows={rereadRows}
        columns={rereadColumns}
        showToolbar={false}
        disableVirtualization
      />
    );
    expect(screen.queryByText('two')).not.toBeInTheDocument();
    expect(screen.getByText('one')).toBeInTheDocument();
  });

  it('applies pruneStoredVisibility to what it reads, and only to that', () => {
    localStorage.setItem('grid-prune', JSON.stringify({ a: false, gone: false }));
    const pruneColumns = [{ field: 'a', headerName: 'A' }];
    const pruneRows = [{ id: 1, a: 'one' }];
    // Deliberately FLIPS `a` from hidden to visible, and drops the stale
    // `gone` key. If the pruned *return value* were computed and then
    // discarded (state set from the raw stored model instead), `a` would
    // stay hidden and 'one' would not render — so this is the case that
    // tells "applied" apart from "computed but ignored", not just whether
    // `prune` was called.
    const prune = vi.fn((stored: Record<string, boolean>) =>
      Object.fromEntries(
        Object.entries({ ...stored, a: true }).filter(([f]) => f === 'a')
      )
    );

    render(
      <DataTable
        storageKey="grid-prune"
        rows={pruneRows}
        columns={pruneColumns}
        showToolbar={false}
        disableVirtualization
        pruneStoredVisibility={prune}
      />
    );

    expect(prune).toHaveBeenCalledWith({ a: false, gone: false });
    // Only true if the model returned by `prune` — not the raw stored one —
    // was actually applied to state.
    expect(screen.getByText('one')).toBeInTheDocument();
  });
});

describe('writes to the exact key a migrated page depends on', () => {
  beforeEach(() => localStorage.clear());

  // Task 7 moved BookingList/EnvironmentList/SystemCatalog off their own
  // hand-rolled loadColumnModel/saveColumnModel pair (which wrote
  // `<name>-columns-${userId ?? 'guest'}`) and onto this component, passing
  // e.g. storageKey="bookings-list-columns" and userId={user?.id ?? 'guest'}
  // specifically so DataTable's own key composition — `${storageKey}-${userId}`
  // — lands on that exact pre-existing entry. `storageKeys.test.ts` pins the
  // page-side half of that contract (the literal `storageKey` string and the
  // `userId={user?.id ?? 'guest'}` companion appear in the page's source) but
  // cannot see how DataTable itself turns those two props into a key. This
  // renders a REAL DataGrid (no mock), performs an actual column-visibility
  // toggle through the toolbar, and reads back what landed in localStorage —
  // so it fails if `fullKey` were ever composed differently (order swapped,
  // a separator changed, `userId` silently dropped), even though every
  // page's own JSX would still look correct.
  it('persists a real column-visibility change under `${storageKey}-${userId}`', async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        storageKey="bookings-list-columns"
        userId={7}
        rows={[{ id: 1, name: 'alpha' }]}
        columns={[{ field: 'name', headerName: 'Name' }]}
      />
    );

    await user.click(screen.getByRole('button', { name: /columns/i }));
    const nameToggle = await screen.findByRole('checkbox', { name: 'Name' });
    await user.click(nameToggle);

    // The exact historical key `bookings-list-columns-7` — not
    // `bookings-list-columns` (userId dropped) and not `7-bookings-list-columns`
    // (order swapped).
    expect(localStorage.getItem('bookings-list-columns-7')).toBe(
      JSON.stringify({ name: false })
    );
    expect(localStorage.getItem('bookings-list-columns')).toBeNull();
  });
});
