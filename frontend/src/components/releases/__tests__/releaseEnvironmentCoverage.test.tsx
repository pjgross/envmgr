/**
 * Frontend IA PR 5 — the coverage matrix is the one table in the app whose
 * COLUMN COUNT is data-driven: `data.environments.map(...)` renders a column
 * per environment. Measured at 1024px: it fits at four environments (736px)
 * and overflows the page by 91px at five, then ~131px per environment. jsdom
 * performs no layout, so this asserts the STRUCTURE that makes the overflow
 * scroll inside the table instead of moving the document.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ReleaseEnvironmentCoverage from '../ReleaseEnvironmentCoverage';
import { releaseService } from '../../../services/releaseService';
import type { ReleaseEnvironmentCoverageResponse } from '../../../types/release';

vi.mock('../../../services/releaseService', () => ({
  releaseService: { getEnvironmentCoverage: vi.fn() },
}));

const coverage = (environmentCount: number): ReleaseEnvironmentCoverageResponse => ({
  needed_systems: [
    { system_id: 1, system_name: 'Customer', role: 'changing' },
    { system_id: 2, system_name: 'Mortgage', role: 'regression' },
  ],
  environments: Array.from({ length: environmentCount }, (_, i) => ({
    environment_id: i + 1,
    name: `Env_${i + 1}`,
    tier_name: 'SIT',
    status: 'active',
    covered_system_ids: [1, 2],
  })),
  uncovered_system_ids: [],
});

describe('ReleaseEnvironmentCoverage scrolls inside itself', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders its matrix inside a TableContainer, so a wide estate scrolls the table and not the page', async () => {
    vi.mocked(releaseService.getEnvironmentCoverage).mockResolvedValue(coverage(8));

    render(<ReleaseEnvironmentCoverage releaseId={1} onBook={vi.fn()} onBookMany={vi.fn()} />);

    const table = await screen.findByRole('table');
    expect(
      table.closest('.MuiTableContainer-root'),
      'the coverage matrix has no scroll container: at five or more environments it widens the DOCUMENT, ' +
        'and the fixed drawer then covers the System column that names each row',
    ).not.toBeNull();
  });

  it('still renders one column per environment', async () => {
    vi.mocked(releaseService.getEnvironmentCoverage).mockResolvedValue(coverage(8));

    render(<ReleaseEnvironmentCoverage releaseId={1} onBook={vi.fn()} onBookMany={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Env_8')).toBeInTheDocument());
    // 8 environments + the leading "System" column.
    expect(screen.getAllByRole('columnheader')).toHaveLength(9);
  });
});
