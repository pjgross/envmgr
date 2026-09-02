export type PirStatus = 'draft' | 'complete';
export type PirFindingKind = 'went_well' | 'went_wrong';
export type PirActionStatus = 'open' | 'in_progress' | 'done' | 'cancelled';

export interface PirCitation {
  incident_id: number;
  incident_title: string;
  severity: string;
  status: string;
  note: string | null;
}

export interface PirAction {
  id: number;
  finding_id: number;
  seq: number;
  title: string;
  detail: string | null;
  owner_id: number | null;
  /** Resolved server-side and travelling with the row — never looked up here. */
  owner_username: string | null;
  due_date: string | null;
  status: PirActionStatus;
  closed_at: string | null;
  closure_note: string | null;
  /** The server's verdict, from one clock per request. Never re-derived here:
   *  a browser with a wrong clock would otherwise manufacture overdue rows. */
  is_overdue: boolean;
}

export interface PirFinding {
  id: number;
  kind: PirFindingKind;
  seq: number;
  title: string;
  detail: string | null;
  root_cause: string | null;
  created_at: string;
  actions: PirAction[];
  incidents: PirCitation[];
}

export interface PIR {
  id: number;
  release_id: number;
  summary: string | null;
  status: PirStatus;
  completed_at: string | null;
  findings: PirFinding[];
}

export interface PIRWrite {
  summary?: string | null;
  status?: PirStatus;
}

export interface PirFindingWrite {
  kind?: PirFindingKind;
  title?: string;
  detail?: string | null;
  root_cause?: string | null;
}

export interface PirActionWrite {
  title?: string;
  detail?: string | null;
  owner_id?: number | null;
  due_date?: string | null;
  status?: PirActionStatus;
  closure_note?: string | null;
}

/** One row of the cross-release worklist. */
export interface PirActionRow extends PirAction {
  finding_title: string;
  release_id: number;
  release_name: string;
  pir_status: PirStatus;
}
