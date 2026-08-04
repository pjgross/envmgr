export interface GitHubStatus {
  connected: boolean;
  github_login: string | null;
  connected_at: string | null;
}

export interface DeviceFlowStarted {
  handle: string;
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

export type PollStatus = 'pending' | 'slow_down' | 'connected' | 'denied' | 'expired';

export interface PollResult {
  status: PollStatus;
  github_login?: string;
  interval?: number;
}

export interface DetectorReport {
  detector: string;
  paths: string[];
  subsystems_created: number;
  subsystems_updated: number;
  dependencies_written: number;
  warnings: string[];
  errors: string[];
  /** Paths this detector claimed that the file cap dropped before they were read. */
  paths_unread: number;
}

export interface ScanResult {
  ref: string;
  files_scanned: number;
  /** GitHub returned a partial tree — the scan saw only part of the repository. */
  truncated: boolean;
  /** The file cap stopped the scan before every match was read. */
  stopped_early: boolean;
  detectors: DetectorReport[];
}

export interface DriftSubsystem {
  name: string;
  component_type: string;
  technology: string | null;
  source_path: string;
}

export interface DriftChangedSubsystem {
  name: string;
  field: string;
  catalogue: string | null;
  declared: string | null;
  source_path: string;
}

export interface DriftEdge {
  from_name: string;
  to_name: string;
  port: number | null;
  source_path?: string;
}

export interface DriftChangedEdge {
  from_name: string;
  to_name: string;
  catalogue_port: number | null;
  declared_port: number | null;
  source_path: string;
}

/**
 * The code declares this edge, but the catalogue already has a row for the
 * same (from, to) pair under a DIFFERENT source (e.g. a hand-made "manual"
 * dependency the code also happens to declare). The unique constraint on
 * dependency edges is (from_subsystem_id, to_subsystem_id, tenant_id) — it
 * does NOT include source — so Scan cannot create this row: it would
 * collide with the existing one. Never fold this into missing_in_catalogue,
 * which the dialog reads as "Scan will create this".
 */
export interface DriftConflictingEdge {
  from_name: string;
  to_name: string;
  port: number | null;
  source_path: string;
  catalogue_source: string;
}

export interface DriftDetectorReport {
  detector: string;
  paths: string[];
  paths_unread: number;
  errors: string[];
  warnings: string[];
  /** False when the repository was read only in part. */
  absence_computed: boolean;
  absence_reason: string | null;
  has_drift: boolean;
  subsystems: {
    missing_in_catalogue: DriftSubsystem[];
    /** null — not [] — when absence could not be computed. */
    missing_in_code: string[] | null;
    changed: DriftChangedSubsystem[];
  };
  edges: {
    missing_in_catalogue: DriftEdge[];
    missing_in_code: DriftEdge[] | null;
    /** Always an array, never null — unlike missing_in_code above. */
    conflicting_source: DriftConflictingEdge[];
    changed: DriftChangedEdge[];
  };
}

export interface DriftResult {
  ref: string;
  files_scanned: number;
  truncated: boolean;
  stopped_early: boolean;
  has_drift: boolean;
  detectors: DriftDetectorReport[];
}
