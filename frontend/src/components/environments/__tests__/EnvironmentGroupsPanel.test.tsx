import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as environmentGroupServiceModule from '../../../services/environmentGroupService';
import EnvironmentGroupsPanel from '../EnvironmentGroupsPanel';
import environmentGroupReducer from '../../../store/environmentGroupSlice';

// No `renderWithStore` helper exists in this codebase — inlined the same way
// EnvironmentProjectsPanel.test.tsx does.
vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroupsForEnvironment: vi.fn(),
  },
}));

const { environmentGroupService } = environmentGroupServiceModule as unknown as {
  environmentGroupService: { listGroupsForEnvironment: ReturnType<typeof vi.fn> };
};

// group_id (5) deliberately coincides with an entry in `staleGroupsList` below
// that carries a DIFFERENT name. Task 7 had three fixtures where an id
// coincidence let a mutation pass via the wrong mechanism — a component that
// wrongly resolves `group_id` against a fetched list would render "Stale
// Name" here instead of the row's own `group_name`, and the test would still
// pass if the ids didn't collide on purpose.
const member = {
  id: 101,
  tenant_id: 1,
  group_id: 5,
  group_name: 'Payments Squad',
  environment_id: 3,
  environment_name: 'UAT-1',
  created_at: '2026-08-06T00:00:00Z',
};

const otherMember = {
  id: 102,
  tenant_id: 1,
  group_id: 9,
  group_name: 'Data Squad',
  environment_id: 3,
  environment_name: 'UAT-1',
  created_at: '2026-08-06T00:00:00Z',
};

function makeStore(preloadGroups = false) {
  const store = configureStore({
    reducer: { environmentGroup: environmentGroupReducer },
  });
  if (preloadGroups) {
    // Simulates the admin list slice having been populated earlier in the
    // session (e.g. the user visited /environment-groups first) with a
    // STALE name for the same group id this panel will render.
    store.dispatch({
      type: 'environmentGroup/fetch/fulfilled',
      payload: {
        rows: [{ id: 5, name: 'Stale Name', member_count: 1 }],
        total: 1,
      },
    });
  }
  return store;
}

function renderPanel(store = makeStore()) {
  return {
    store,
    ...render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/environments/3']}>
          <EnvironmentGroupsPanel environmentId={3} />
        </MemoryRouter>
      </Provider>
    ),
  };
}

describe('EnvironmentGroupsPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('names groups from the response row, never a separately fetched groups list', async () => {
    vi.mocked(environmentGroupService.listGroupsForEnvironment).mockResolvedValue({
      rows: [member],
      total: 1,
    });
    renderPanel(makeStore(true));

    await waitFor(() => expect(screen.getByText('Payments Squad')).toBeInTheDocument());
    // If a wrong implementation resolved group_id (5) against state
    // .environmentGroup.groups instead, this would render "Stale Name".
    expect(screen.queryByText('Stale Name')).not.toBeInTheDocument();
  });

  it('links each group to its admin detail page', async () => {
    vi.mocked(environmentGroupService.listGroupsForEnvironment).mockResolvedValue({
      rows: [member],
      total: 1,
    });
    renderPanel();

    await waitFor(() => expect(screen.getByText('Payments Squad')).toBeInTheDocument());
    expect(screen.getByText('Payments Squad').closest('a')).toHaveAttribute(
      'href',
      '/environment-groups/5'
    );
  });

  it('shows an empty state rather than a bare panel', async () => {
    vi.mocked(environmentGroupService.listGroupsForEnvironment).mockResolvedValue({
      rows: [],
      total: 0,
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/not a member of any environment group/i)).toBeInTheDocument()
    );
  });

  it('shows a failed load rather than looking like "no groups"', async () => {
    // Mock rejects with an AxiosError SHAPE: a real axios error's `.message`
    // is the generic "Request failed with status code 500" and the reason
    // lives only at response.data.detail. A plain Error carrying the final
    // text would pass against code that reads result.error.message.
    vi.mocked(environmentGroupService.listGroupsForEnvironment).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'Could not load environment groups' } },
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/could not load environment groups/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/not a member of any environment group/i)).not.toBeInTheDocument();
  });

  it('refetches and re-renders when the environment changes', async () => {
    // Task 9's review found two render-timing bugs that only a SECOND render
    // surfaced — a stale-effect bug and a referential-identity bug — because
    // those suites mounted once and asserted only the first paint. This test
    // changes props after the first paint and asserts the panel updates
    // rather than keeping the first environment's groups on screen.
    vi.mocked(environmentGroupService.listGroupsForEnvironment)
      .mockResolvedValueOnce({ rows: [member], total: 1 })
      .mockResolvedValueOnce({ rows: [otherMember], total: 1 });

    const store = makeStore();
    const { rerender } = render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/environments/3']}>
          <EnvironmentGroupsPanel environmentId={3} />
        </MemoryRouter>
      </Provider>
    );
    await waitFor(() => expect(screen.getByText('Payments Squad')).toBeInTheDocument());

    rerender(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/environments/4']}>
          <EnvironmentGroupsPanel environmentId={4} />
        </MemoryRouter>
      </Provider>
    );

    await waitFor(() => expect(screen.getByText('Data Squad')).toBeInTheDocument());
    expect(screen.queryByText('Payments Squad')).not.toBeInTheDocument();
    expect(environmentGroupService.listGroupsForEnvironment).toHaveBeenCalledTimes(2);
    expect(environmentGroupService.listGroupsForEnvironment).toHaveBeenNthCalledWith(2, 4);
  });

  it('shows the newer environment\'s groups when the OLDER request resolves LAST (Task 10 review finding)', async () => {
    // Unlike the test above (mockResolvedValueOnce, resolved in dispatch
    // order), this test controls resolution order by hand: the request for
    // environment 3 is dispatched FIRST but resolves SECOND, after the
    // request for environment 4 has already landed. Without request
    // sequencing in the slice, the stale environment-3 response wins because
    // it lands last, and the panel would show "Payments Squad" for an
    // environment the user has already navigated away from.
    let resolveFor3!: (value: { rows: typeof member[]; total: number }) => void;
    let resolveFor4!: (value: { rows: typeof otherMember[]; total: number }) => void;
    const for3 = new Promise<{ rows: typeof member[]; total: number }>((res) => {
      resolveFor3 = res;
    });
    const for4 = new Promise<{ rows: typeof otherMember[]; total: number }>((res) => {
      resolveFor4 = res;
    });
    vi.mocked(environmentGroupService.listGroupsForEnvironment)
      .mockReturnValueOnce(for3)
      .mockReturnValueOnce(for4);

    const store = makeStore();
    const { rerender } = render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/environments/3']}>
          <EnvironmentGroupsPanel environmentId={3} />
        </MemoryRouter>
      </Provider>
    );

    rerender(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/environments/4']}>
          <EnvironmentGroupsPanel environmentId={4} />
        </MemoryRouter>
      </Provider>
    );

    // Newer request (environment 4) resolves FIRST.
    resolveFor4({ rows: [otherMember], total: 1 });
    await waitFor(() => expect(screen.getByText('Data Squad')).toBeInTheDocument());

    // Older request (environment 3) resolves LAST.
    resolveFor3({ rows: [member], total: 1 });

    // Give the stale promise a turn to (wrongly) apply if the guard is
    // missing, then assert the newer environment's data is still what's shown.
    await new Promise((res) => setTimeout(res, 0));
    expect(screen.getByText('Data Squad')).toBeInTheDocument();
    expect(screen.queryByText('Payments Squad')).not.toBeInTheDocument();
  });
});
