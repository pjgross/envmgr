export type InfrastructureComponentType =
  | 'server'
  | 'container_runtime'
  | 'kubernetes_cluster'
  | 'managed_database'
  | 'load_balancer'
  | 'network'
  | 'cdn'
  | 'queue'
  | 'cache'
  | 'other';

export type InfrastructureComponentSource = 'manual' | 'terraform' | 'docker_compose';

export interface InfrastructureComponentResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  component_type: InfrastructureComponentType;
  provider: string | null;
  region: string | null;
  location: string | null;
  source: InfrastructureComponentSource;
  external_id: string | null;
  custom_fields: Record<string, unknown> | null;
  tags: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface InfrastructureComponentCreate {
  name: string;
  description?: string;
  component_type: InfrastructureComponentType;
  provider?: string;
  region?: string;
  location?: string;
  source?: InfrastructureComponentSource;
  external_id?: string;
  custom_fields?: Record<string, unknown>;
  tags?: Record<string, unknown>;
}

export interface InfrastructureComponentUpdate {
  name?: string;
  description?: string;
  component_type?: InfrastructureComponentType;
  provider?: string;
  region?: string;
  location?: string;
  source?: InfrastructureComponentSource;
  external_id?: string;
  custom_fields?: Record<string, unknown>;
  tags?: Record<string, unknown>;
}

export interface InfrastructureComponentSummary {
  id: number;
  name: string;
  component_type: InfrastructureComponentType;
  provider: string | null;
  region: string | null;
}

export interface HostAttachment {
  infrastructure_component_id: number;
  role?: string | null;
}

export interface EnvironmentSubSystemHostResponse {
  id: number;
  environment_subsystem_id: number;
  infrastructure_component_id: number;
  infrastructure_component: InfrastructureComponentSummary;
  role: string | null;
}

export interface EnvironmentSubSystemHostsResponse {
  hosts: EnvironmentSubSystemHostResponse[];
}

export interface HostImpactMatch {
  host_id: number;
  host_name: string;
  role: string | null;
}

export interface HostImpactSubsystem {
  subsystem_id: number;
  subsystem_name: string;
  system_name: string;
  is_mocked: boolean;
  matches: HostImpactMatch[];
}

export interface HostImpactEnvironment {
  environment_id: number;
  environment_name: string;
  subsystems: HostImpactSubsystem[];
}

export interface HostImpactResponse {
  host_ids: number[];
  environments: HostImpactEnvironment[];
}

export const COMPONENT_TYPE_OPTIONS: { value: InfrastructureComponentType; label: string }[] = [
  { value: 'server', label: 'Server / VM' },
  { value: 'container_runtime', label: 'Container runtime' },
  { value: 'kubernetes_cluster', label: 'Kubernetes cluster' },
  { value: 'managed_database', label: 'Managed database' },
  { value: 'load_balancer', label: 'Load balancer' },
  { value: 'network', label: 'Network' },
  { value: 'cdn', label: 'CDN' },
  { value: 'queue', label: 'Queue' },
  { value: 'cache', label: 'Cache' },
  { value: 'other', label: 'Other' },
];

export const SOURCE_OPTIONS: { value: InfrastructureComponentSource; label: string }[] = [
  { value: 'manual', label: 'Manual' },
  { value: 'terraform', label: 'Terraform' },
  { value: 'docker_compose', label: 'Docker Compose' },
];
