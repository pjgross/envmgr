import type { SubSystemResponse } from './system'
import type { ComponentDependencyResponse } from './dependency'

export interface TopologyResponse {
  subsystems: SubSystemResponse[]
  dependencies: ComponentDependencyResponse[]
  external_subsystems: SubSystemResponse[]
  external_dependencies: ComponentDependencyResponse[]
  system_names: Record<string, string>
}
