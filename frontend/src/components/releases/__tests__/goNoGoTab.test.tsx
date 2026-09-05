/**
 * GoNoGoTab — Phase 9 C3's Go/No-Go tab on the release detail page.
 *
 * `@mui/x-data-grid`'s `DataGrid` is replaced by the shared un-virtualized
 * stand-in (see `src/test/dataGridMock.tsx`): jsdom reports a zero-width
 * container, so the real grid would only mount cells for the first couple of
 * columns and hide the rest — exactly the columns these tests need to read
 * (`outcome`, `unmet_condition_count`).
 */
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { store } from '../../../store';
import GoNoGoTab from '../GoNoGoTab';
import type { GoNoGoDecisionRead } from '../../../types/goNoGo';
import { getLastDataGridProps } from '../../../test/dataGridMock';
import { formatBookingDateTime } from '../../../utils/datetime';

vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  const { createDataGridMock } = await import('../../../test/dataGridMock');
  return { ...actual, ...createDataGridMock() };
});

vi.mock('../../../services/goNoGoService', () => ({
  goNoGoService: {
    list: vi.fn(),
    record: vi.fn(),
    closeCondition: vi.fn(),
    listPerspectives: vi.fn().mockResolvedValue([]),
  },
}));

import { goNoGoService } from '../../../services/goNoGoService';

const mocked = goNoGoService as unknown as {
  list: ReturnType<typeof vi.fn>;
  closeCondition: ReturnType<typeof vi.fn>;
};

function decision(over: Partial<GoNoGoDecisionRead> = {}): GoNoGoDecisionRead {
  return {
    id: 1,
    tenant_id: 1,
    release_id: 42,
    outcome: 'go',
    rationale: 'Everything checked out.',
    decided_at: '2026-09-01T10:00:00Z',
    chaired_by_user_id: 1,
    chaired_by_username: 'alice',
    attendees: [],
    snapshot_ok: true,
    snapshot_blockers: [],
    snapshot_warnings: [],
    snapshot_reversibility: null,
    snapshot_rehearsal_state: null,
    signoffs: [],
    conditions: [],
    unmet_condition_count: 0,
    ...over,
  };
}

function renderTab() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/releases/42?tab=go-no-go']}>
        <GoNoGoTab releaseId={42} />
      </MemoryRouter>
    </Provider>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.list.mockResolvedValue({ rows: [], total: 0 });
});

describe('GoNoGoTab', () => {
  it('renders one history row per decision, each with its own outcome', async () => {
    mocked.list.mockResolvedValue({
      rows: [
        decision({ id: 1, outcome: 'go', decided_at: '2026-09-01T10:00:00Z' }),
        decision({ id: 2, outcome: 'no_go', decided_at: '2026-08-20T10:00:00Z' }),
      ],
      total: 2,
    });

    renderTab();

    await waitFor(() => expect(getLastDataGridProps()?.rows).toHaveLength(2));
    expect(screen.getByText('Go')).toBeInTheDocument();
    expect(screen.getByText('No Go')).toBeInTheDocument();
  });

  it('shows a dissenting sign-off alongside a disagreeing outcome — neither hides the other', async () => {
    mocked.list.mockResolvedValue({
      rows: [
        decision({
          id: 1,
          outcome: 'go',
          decided_at: '2026-09-01T10:00:00Z',
          signoffs: [
            {
              id: 5,
              decision_id: 1,
              perspective_id: 2,
              user_id: 9,
              username: 'security-lead',
              verdict: 'no_go',
              dissent_note: 'Open critical vulnerability, unresolved.',
            },
          ],
        }),
      ],
      total: 1,
    });

    renderTab();

    // The decision's own outcome — from the latest-decision heading, not the
    // grid, so this is independent of the DataGrid mock's column rendering.
    await screen.findByText(/Latest decision — Go/);
    // The dissenting sign-off's own (disagreeing) verdict...
    expect(screen.getByText('security-lead')).toBeInTheDocument();
    expect(screen.getAllByText('No Go').length).toBeGreaterThan(0);
    // ...and its dissent note. Both render; the outcome heading above did not
    // suppress or reconcile away the disagreement.
    expect(screen.getByText('Open critical vulnerability, unresolved.')).toBeInTheDocument();
  });

  it('renders an unmet condition with its owner and due date', async () => {
    mocked.list.mockResolvedValue({
      rows: [
        decision({
          id: 1,
          decided_at: '2026-09-01T10:00:00Z',
          unmet_condition_count: 1,
          conditions: [
            {
              id: 8,
              decision_id: 1,
              text: 'Confirm the database backup completed',
              owner_user_id: 3,
              owner_username: 'carol',
              due_date: '2026-09-10T00:00:00Z',
              met_at: null,
              met_by_user_id: null,
              met_by_username: null,
            },
          ],
        }),
      ],
      total: 1,
    });

    renderTab();

    await screen.findByText('Confirm the database backup completed');
    expect(screen.getByText('carol')).toBeInTheDocument();
    expect(screen.getByText('Unmet')).toBeInTheDocument();
    expect(
      screen.getByText(formatBookingDateTime('2026-09-10T00:00:00Z'))
    ).toBeInTheDocument();
  });

  it('a failed fetch renders an Alert and never an authoritative empty message', async () => {
    mocked.list.mockRejectedValueOnce(new Error('Network unavailable'));

    renderTab();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Network unavailable')
    );

    // The entity-specific "nothing recorded" message would state as fact
    // something the app does not actually know — it must not be the message
    // wired into the grid when the fetch itself failed.
    await waitFor(() => {
      const props = getLastDataGridProps() as { emptyMessage?: string } | null;
      const message = (
        props as unknown as { slots?: { noRowsOverlay?: () => { props: { message: string } } } }
      )?.slots?.noRowsOverlay?.().props.message;
      expect(message).toBe('Unable to load go/no-go decisions.');
    });
    expect(
      screen.queryByText('No go/no-go decisions have been recorded for this release yet.')
    ).not.toBeInTheDocument();
  });
});
