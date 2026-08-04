export interface VersionResponse {
  id: number;
  environment_id: number;
  subsystem_id: number;
  subsystem_name: string;
  build_id: string;
  version_label: string;
  installed_at: string;
  tenant_id: number;
  created_at: string;
}

export interface VersionCreate {
  subsystem_id: number;
  build_id: string;
  version_label: string;
  installed_at?: string;
}

export interface VersionUpdate {
  build_id?: string;
  version_label?: string;
  installed_at?: string;
}

export interface ImportError {
  row: number;
  field: string;
  message: string;
}

export interface ImportResult {
  created: number;
  skipped: number;
  errors: ImportError[];
  // Rows imported successfully but with an assumption applied — a
  // mistyped/blank Type filed under the tenant's Other tier, or a row
  // imported without an owner because the importer isn't a member of the
  // target tenant. Same shape as `errors`. Always present (backend default
  // is `[]`); import paths that never produce one (e.g. systems) just send
  // an empty array.
  tier_fallbacks: ImportError[];
}
