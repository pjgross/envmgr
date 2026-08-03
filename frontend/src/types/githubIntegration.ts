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
