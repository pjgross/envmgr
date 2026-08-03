import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/githubIntegrationService', () => ({
  githubIntegrationService: { scan: vi.fn() },
}));

import { githubIntegrationService } from '../../../services/githubIntegrationService';
import ScanRepositoryDialog from '../ScanRepositoryDialog';

const RESULT = {
  ref: 'main',
  files_scanned: 2,
  truncated: false,
  stopped_early: false,
  detectors: [
    { detector: 'docker_compose', paths: ['docker-compose.yml'], subsystems_created: 3,
      subsystems_updated: 0, dependencies_written: 2, warnings: [], errors: [] },
  ],
};

describe('ScanRepositoryDialog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('reports what each detector found', async () => {
    vi.mocked(githubIntegrationService.scan).mockResolvedValue(RESULT);
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/docker_compose/)).toBeInTheDocument();
    expect(screen.getByText(/3 subsystems created/i)).toBeInTheDocument();
  });

  it('warns when the repository tree was truncated', async () => {
    // A partial scan must never look like a complete one.
    vi.mocked(githubIntegrationService.scan).mockResolvedValue({ ...RESULT, truncated: true });
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/too large to read in full/i)).toBeInTheDocument();
  });

  it('warns when the file cap stopped the scan early', async () => {
    vi.mocked(githubIntegrationService.scan).mockResolvedValue({
      ...RESULT, stopped_early: true,
    });
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/stopped after/i)).toBeInTheDocument();
  });

  it('shows a detector error without hiding the detectors that worked', async () => {
    vi.mocked(githubIntegrationService.scan).mockResolvedValue({
      ...RESULT,
      detectors: [
        ...RESULT.detectors,
        { detector: 'terraform_hcl', paths: ['main.tf'], subsystems_created: 0,
          subsystems_updated: 0, dependencies_written: 0, warnings: [],
          errors: ['main.tf: Invalid Terraform HCL'] },
      ],
    });
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/Invalid Terraform HCL/)).toBeInTheDocument();
    expect(screen.getByText(/3 subsystems created/i)).toBeInTheDocument();
  });
});
