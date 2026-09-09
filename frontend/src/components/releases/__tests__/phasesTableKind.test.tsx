/**
 * PhasesTable — Phase 9 C6: phase `kind` ('test' | 'hypercare'), surfaced as
 * a grid column and sent on create/update. See `goNoGoTab.test.tsx` for the
 * `createDataGridMock`/`getLastDataGridProps` pattern this file reuses.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { SnackbarProvider } from 'notistack';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { store } from '../../../store';
import PhasesTable from '../PhasesTable';
import { releaseService } from '../../../services/releaseService';
import { getLastDataGridProps } from '../../../test/dataGridMock';
import type { TestPhaseResponse } from '../../../types/release';

vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  const { createDataGridMock } = await import('../../../test/dataGridMock');
  return { ...actual, ...createDataGridMock() };
});

vi.mock('../../../services/releaseService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/releaseService')>();
  return {
    ...actual,
    releaseService: { ...actual.releaseService, createPhase: vi.fn(), updatePhase: vi.fn() },
  };
});

function phase(over: Partial<TestPhaseResponse> = {}): TestPhaseResponse {
  return {
    id: 1,
    tenant_id: 1,
    release_id: 7,
    name: 'SIT',
    order: 1,
    start_date: null,
    end_date: null,
    status: 'planned',
    kind: 'test',
    ...over,
  };
}

function renderTable(phases: TestPhaseResponse[]) {
  return render(
    <Provider store={store}>
      <SnackbarProvider>
        <PhasesTable releaseId={7} phases={phases} />
      </SnackbarProvider>
    </Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(releaseService.createPhase).mockResolvedValue(
    phase({ id: 9, name: 'Hypercare Watch', kind: 'hypercare', order: 2 })
  );
  vi.mocked(releaseService.updatePhase).mockResolvedValue(phase());
});

describe('PhasesTable — phase kind', () => {
  it('shows a Kind column and sends kind on create', async () => {
    renderTable([
      phase({ id: 1, name: 'SIT', kind: 'test' }),
      phase({ id: 2, name: 'UAT', kind: 'test', order: 2 }),
    ]);

    const props = getLastDataGridProps() as { columns: { field: string }[] } | null;
    expect(props?.columns.map((c) => c.field)).toContain('kind');

    await userEvent.click(screen.getByRole('button', { name: /add phase/i }));
    const dialog = await screen.findByRole('dialog');

    await userEvent.type(within(dialog).getByLabelText(/^name/i), 'Hypercare Watch');
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Kind' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Hyper-care' }));

    await userEvent.click(within(dialog).getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(releaseService.createPhase).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ kind: 'hypercare' })
      )
    );
  });
});
