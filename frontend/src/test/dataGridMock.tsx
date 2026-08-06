import type { ReactNode } from 'react';

/**
 * The un-virtualized `<DataGrid>` stand-in used by grid page tests.
 *
 * The real DataGrid virtualizes columns by container width, and jsdom always
 * reports zero width — only the first few columns' cells would mount, which
 * hides whatever columns a test asserts on further to the right. This
 * stand-in renders every column's cell for every row instead, exactly what a
 * real DataGrid would eventually put in the DOM once scrolled into view.
 *
 * It resolves a cell through **both** `renderCell` and `valueGetter`, in that
 * order, falling back to the raw row value. A `renderCell`-only version is
 * not just weaker — for a column that is `valueGetter`-only (e.g.
 * `EnvironmentRequestList`'s `target` column), it renders every cell in that
 * column blank, so a test asserting on that column's content fails outright,
 * not just loses coverage.
 *
 * Usage:
 * ```ts
 * vi.mock('@mui/x-data-grid', async (importOriginal) => {
 *   const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
 *   const { createDataGridMock } = await import('../../../test/dataGridMock');
 *   return { ...actual, ...createDataGridMock() };
 * });
 * ```
 * (a dynamic import inside the factory, not a top-level import, because
 * `vi.mock` factories are hoisted above other imports)
 *
 * Only `environmentRequestList.test.tsx` uses this today.
 * `environmentListServerGrid.test.tsx` and `userGroups.test.tsx` still carry
 * their own local copies (the latter is `renderCell`-only) and were
 * deliberately left alone when this was extracted.
 */
export function createDataGridMock() {
  return {
    DataGrid: (props: Record<string, unknown>) => {
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
              <tr key={String(row.id)}>
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
}
