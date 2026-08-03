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
