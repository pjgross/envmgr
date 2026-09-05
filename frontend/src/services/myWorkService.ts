import api from './api';
import type { MyWorkResponse } from '../types/myWork';

/** `GET /me/work` — one round trip for all five "waiting on me" queues. */
export const myWorkService = {
  getMyWork: (): Promise<MyWorkResponse> =>
    api.get<MyWorkResponse>('/me/work').then((r) => r.data),
};
