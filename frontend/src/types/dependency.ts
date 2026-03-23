export type DependencyType = 'api_call' | 'database' | 'message_queue' | 'event' | 'file' | 'other';
export type DependencySource = 'manual' | 'terraform' | 'docker_compose';
export type DependencyDirection = 'one_way' | 'two_way';

export interface SystemDependencyResponse {
  id: number;
  from_system_id: number;
  to_system_id: number;
  dependency_type: DependencyType;
  direction: DependencyDirection;
  source: DependencySource;
  tenant_id: number;
  to_system: {
    id: number;
    name: string;
    description: string | null;
  };
  from_system?: {
    id: number;
    name: string;
    description?: string;
  };
  is_incoming: boolean;
}

export interface ComponentDependencyResponse {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
  dependency_type: DependencyType;
  direction: DependencyDirection;
  protocol: string | null;
  port: number | null;
  source: DependencySource;
  tenant_id: number;
  to_subsystem: {
    id: number;
    name: string;
    description: string | null;
    system_id: number;
  };
  from_subsystem?: {
    id: number;
    name: string;
    description?: string;
    system_id: number;
  };
  is_incoming: boolean;
}

export interface SystemDependencyCreate {
  to_system_id: number;
  dependency_type: DependencyType;
  direction?: DependencyDirection;
  source?: DependencySource;
}

export interface ComponentDependencyCreate {
  to_subsystem_id: number;
  dependency_type: DependencyType;
  direction?: DependencyDirection;
  protocol?: string;
  port?: number;
  source?: DependencySource;
}

export interface DependencyVerifyItem {
  to_system_id: number;
  to_system_name: string;
  dependency_type: DependencyType;
  status: 'satisfied' | 'mocked' | 'missing';
}

export interface SystemVerifyResult {
  system_id: number;
  system_name: string;
  dependencies: DependencyVerifyItem[];
}

export interface VerifyResponse {
  environment_id: number;
  total_dependencies: number;
  satisfied_count: number;
  mocked_count: number;
  missing_count: number;
  systems: SystemVerifyResult[];
}
