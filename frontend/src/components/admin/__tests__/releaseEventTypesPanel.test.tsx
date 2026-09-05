import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ReleaseEventTypesPanel from '../ReleaseEventTypesPanel';
import releaseEventTypeReducer from '../../../store/releaseEventTypeSlice';
import { releaseEventTypeService } from '../../../services/releaseEventTypeService';

vi.mock('../../../services/releaseEventTypeService', () => ({
  releaseEventTypeService: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — the actions column's Edit/Delete buttons never mount.
// Same stand-in as lifecycleTemplatesPanel.test.tsx / environmentListServerGrid.test.tsx.
vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  return {
    ...actual,
    DataGrid: (props: Record<string, unknown>) => {
      const rows = props.rows as Array<Record<string, unknown>>;
      const columns = props.columns as Array<{
        field: string;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        renderCell?: (params: any) => ReactNode;
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

function renderPanel() {
  const store = configureStore({
    reducer: { releaseEventType: releaseEventTypeReducer },
  });
  return render(
    <Provider store={store}>
      <ReleaseEventTypesPanel />
    </Provider>
  );
}

describe('ReleaseEventTypesPanel', () => {
  beforeEach(() => {
    vi.mocked(releaseEventTypeService.list).mockResolvedValue([
      { id: 1, tenant_id: 1, name: 'Code Freeze', display_color: null, is_system: true },
      { id: 2, tenant_id: 1, name: 'Custom Milestone', display_color: null, is_system: false },
    ]);
  });

  // The Delete button's Tooltip is CONDITIONAL — "Delete" on a non-system row,
  // "System types cannot be deleted" on a system row — so without an explicit,
  // constant aria-label, MUI's own Tooltip-to-aria-label fallback would hand
  // the system row's button a *different* accessible name than the non-system
  // row's, even though it is the same control in both rows. Both must read
  // "Delete".
  it('names both Delete buttons "Delete" regardless of the row being a system type', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getByText('Code Freeze')).toBeInTheDocument());
    expect(screen.getByText('Custom Milestone')).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole('button', { name: /^delete$/i });
    expect(deleteButtons).toHaveLength(2);

    // The system row's button is disabled but still named "Delete", not the
    // disabled-reason text a sighted user sees in the tooltip.
    expect(deleteButtons.some((b) => b.hasAttribute('disabled'))).toBe(true);
    expect(deleteButtons.some((b) => !b.hasAttribute('disabled'))).toBe(true);
  });
});
