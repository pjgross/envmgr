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
