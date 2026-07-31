import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import DataTable from '../DataTable';

const columns = [{ field: 'name', headerName: 'Name' }];
const rows = [{ id: 1, name: 'alpha' }];

describe('DataTable server mode', () => {
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

  it('still works as a client-side grid when server props are omitted', () => {
    render(<DataTable storageKey="test-grid" rows={rows} columns={columns} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
  });

  // The two tests above render a real DataGrid. That's a good regression
  // guard against `rowCount`/`paginationMode`/etc. getting re-added to the
  // `Omit` list, but it can't actually observe whether DataTable still
  // forces its client-side `initialState.pagination.paginationModel`
  // default onto a server-mode caller: MUI's controlled `paginationModel`
  // prop wins over `initialState` at the selector level from the very first
  // render (`registerControlState` in
  // @mui/x-data-grid's useGridPaginationModel), so the footer/page size
  // render identically either way once a controlled `paginationModel` is
  // supplied — which every real server-mode caller does. Assert on the
  // actual prop DataTable hands to DataGrid instead of on rendered output.
  it('does not force the client pageSize default into initialState when paginationMode is server', async () => {
    vi.resetModules();
    let capturedInitialState: unknown = 'not-called';
    vi.doMock('@mui/x-data-grid', async () => {
      const actual =
        await vi.importActual<typeof import('@mui/x-data-grid')>('@mui/x-data-grid');
      return {
        ...actual,
        DataGrid: (props: { initialState?: unknown }) => {
          capturedInitialState = props.initialState;
          return null;
        },
      };
    });

    const { default: MockedDataTable } = await import('../DataTable');
    render(
      <MockedDataTable
        storageKey="test-grid"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        paginationModel={{ page: 0, pageSize: 25 }}
        onPaginationModelChange={vi.fn()}
      />
    );

    // The caller passed no `initialState`, so DataTable must forward
    // `undefined` rather than inventing a `{ pageSize: 25 }` default.
    expect(capturedInitialState).toBeUndefined();

    vi.doUnmock('@mui/x-data-grid');
    vi.resetModules();
  });
});
