import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
});
