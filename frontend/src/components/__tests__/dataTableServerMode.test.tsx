import { render, screen } from '@testing-library/react';
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
    const prune = vi.fn((stored: Record<string, boolean>) =>
      Object.fromEntries(Object.entries(stored).filter(([f]) => f === 'a'))
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
    // `a` was hidden by a real stored preference and survives pruning.
    expect(screen.queryByText('one')).not.toBeInTheDocument();
  });
});
