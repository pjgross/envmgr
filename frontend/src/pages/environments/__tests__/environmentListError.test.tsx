import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import EnvironmentList from '../EnvironmentList';

// No HTTP — this test is only about what the grid renders once the list
// fetch itself has failed.
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn(),
    deleteEnvironment: vi.fn(),
    updateEnvironment: vi.fn(),
    createEnvironment: vi.fn(),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}));

vi.mock('../../../services/environmentNamingPolicyService', () => ({
  environmentNamingPolicyService: {
    get: vi.fn().mockResolvedValue({
      is_enabled: false,
      name_pattern: null,
      name_pattern_example: null,
      required_attributes: [],
      grace_days: 14,
      effective_from: '2026-08-09T00:00:00Z',
    }),
  },
}));

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { environmentService } from '../../../services/environmentService';

function renderEnvironmentList() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/environments']}>
        <EnvironmentList />
      </MemoryRouter>
    </Provider>
  );
}

describe('EnvironmentList — a failed fetch is never an empty list', () => {
  it('renders the server reason, not an authoritative empty grid', async () => {
    vi.mocked(environmentService.listEnvironments).mockRejectedValueOnce(
      new Error('Upstream is unavailable')
    );

    renderEnvironmentList();

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Upstream is unavailable')
    );
    // The grid's emptyMessage states a fact the app does not know when the
    // request failed.
    expect(screen.queryByText('No environments match these filters.')).not.toBeInTheDocument();
  });
});
