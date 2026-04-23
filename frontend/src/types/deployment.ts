// frontend/src/types/deployment.ts
export type DeploymentStatus =
  | 'pending'
  | 'in_progress'
  | 'success'
  | 'failed'
  | 'rolled_back';

export interface Deployment {
  id: number;
  tenant_id: number;
  build_id: number;
  environment_id: number;
  release_id: number | null;
  change_request_id: number;
  event_id: string;
  deployer_name: string | null;
  deployed_at: string;
  completed_at: string | null;
  status: DeploymentStatus;
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DeploymentFilters {
  environment_id?: number;
  release_id?: number;
  build_id?: number;
  status?: DeploymentStatus;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface DeploymentLinkChangeRequest {
  change_request_id: number;
}
