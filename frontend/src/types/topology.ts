import type { SubSystemResponse } from './system'
import type { ComponentDependencyResponse } from './dependency'

export interface TopologyResponse {
  subsystems: SubSystemResponse[]
  dependencies: ComponentDependencyResponse[]
}
