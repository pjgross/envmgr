export type MembershipState =
  | "pending_request"
  | "accepted"
  | "rejected"
  | "withdrawn"
  | "removed";

export interface ReleaseMembership {
  id: number;
  tenantId: number;
  enterpriseReleaseId: number;
  projectReleaseId: number;
  projectReleaseName?: string | null;
  projectReleaseStatus?: string | null;
  enterpriseReleaseName?: string | null;
  state: MembershipState;
  requestedBy: number;
  requestedByUsername?: string | null;
  requestedAt: string;
  decidedBy?: number | null;
  decidedByUsername?: string | null;
  decidedAt?: string | null;
  removedBy?: number | null;
  removedByUsername?: string | null;
  removedAt?: string | null;
  removalReason?: string | null;
  lateScope: boolean;
  notes?: string | null;
}

export interface MembershipSummary {
  pending: number;
  accepted: number;
  rejected: number;
  withdrawn: number;
  removed: number;
}

export interface MembershipCreatePayload {
  project_release_id: number;
  notes?: string;
}

export interface MembershipRejectPayload { notes: string; }
export interface MembershipRemovePayload { reason: string; }

// ── Wire shapes ───────────────────────────────────────────────────────────
// Raw snake_case payloads, so the service mappers take a typed input.

export interface ApiReleaseMembership {
  id: number;
  tenant_id: number;
  enterprise_release_id: number;
  project_release_id: number;
  project_release_name?: string | null;
  project_release_status?: string | null;
  enterprise_release_name?: string | null;
  state: MembershipState;
  requested_by: number;
  requested_by_username?: string | null;
  requested_at: string;
  decided_by?: number | null;
  decided_by_username?: string | null;
  decided_at?: string | null;
  removed_by?: number | null;
  removed_by_username?: string | null;
  removed_at?: string | null;
  removal_reason?: string | null;
  late_scope: boolean;
  notes?: string | null;
}

export interface ApiProjectMembership {
  current: ApiReleaseMembership | null;
  history?: ApiReleaseMembership[] | null;
}
