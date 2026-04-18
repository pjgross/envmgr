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
}
