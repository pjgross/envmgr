import api from './api';
import type {
  DeviceFlowStarted, DriftResult, GitHubStatus, PollResult, ScanResult,
} from '../types/githubIntegration';

export const githubIntegrationService = {
  status: (): Promise<GitHubStatus> =>
    api.get('/integrations/github').then((r) => r.data),

  connect: (): Promise<DeviceFlowStarted> =>
    api.post('/integrations/github/connect').then((r) => r.data),

  poll: (handle: string): Promise<PollResult> =>
    api.post(`/integrations/github/connect/${handle}/poll`).then((r) => r.data),

  disconnect: (): Promise<void> =>
    api.delete('/integrations/github').then(() => undefined),

  scan: (systemId: number): Promise<ScanResult> =>
    api.post(`/systems/${systemId}/github/scan`).then((r) => r.data),

  drift: (systemId: number): Promise<DriftResult> =>
    api.get(`/systems/${systemId}/github/drift`).then((r) => r.data),
};
