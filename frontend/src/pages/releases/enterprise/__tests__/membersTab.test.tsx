import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../../store';
import { MembersTab } from '../MembersTab';
import type { ReleaseResponse } from '../../../../types/release';

vi.mock('../../../../services/enterpriseMembershipService', () => ({
  enterpriseMembershipService: {
    list: vi.fn(),
    request: vi.fn(),
    accept: vi.fn(),
    reject: vi.fn(),
    withdraw: vi.fn(),
    remove: vi.fn(),
  },
}));

import { enterpriseMembershipService } from '../../../../services/enterpriseMembershipService';

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — the accepted-members grid's action column (the
// "Remove" IconButton, no Tooltip at all) would never mount. Same stand-in
// as lifecycleTemplatesPanel.test.tsx / environmentListServerGrid.test.tsx.
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

const RELEASE: ReleaseResponse = {
  id: 1,
  tenant_id: 1,
  name: 'Enterprise Release',
  description: null,
  release_type: 'enterprise',
  release_kind: 'enterprise',
  owning_project_id: null,
  owning_project_name: null,
  parent_release_id: null,
  template_id: null,
  lifecycle_template_id: 1,
  status: 'draft',
  target_date: null,
  actual_date: null,
  scope_deadline: null,
  custom_fields: null,
  raised_by: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function renderTab() {
  return render(
    <Provider store={store}>
      <MembersTab release={RELEASE} />
    </Provider>
  );
}

describe('MembersTab', () => {
  beforeEach(() => {
    vi.mocked(enterpriseMembershipService.list).mockResolvedValue([
      {
        id: 10,
        tenantId: 1,
        enterpriseReleaseId: 1,
        projectReleaseId: 2,
        projectReleaseName: 'Project A',
        projectReleaseStatus: 'in_progress',
        state: 'accepted',
        requestedBy: 5,
        requestedByUsername: 'bob',
        requestedAt: '2026-01-01T00:00:00Z',
        decidedBy: 6,
        decidedByUsername: 'alice',
        decidedAt: '2026-01-02T00:00:00Z',
        lateScope: false,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any,
    ]);
  });

  // No `Tooltip` wraps this button at all — unlike the EnvironmentList/
  // SystemCatalog/InfrastructureComponentList pairs, there is no MUI
  // fallback name here. Before this PR the button had no accessible name.
  it('names the accepted-member remove button for a screen reader', async () => {
    renderTab();
    expect(await screen.findByText('Project A')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^remove$/i })).toBeInTheDocument();
  });
});
