export type Presence = 'both' | 'left_only' | 'right_only';
export type DifferenceKind = 'presence' | 'mocked' | 'version' | 'host_shape';

export interface HostShapeEntry {
  component_type: string;
  role: string | null;
  count: number;
}

export interface ComparedEnvironment {
  id: number;
  name: string;
  status: string;
}

export interface SystemPresence {
  system_id: number;
  name: string;
  presence: Presence;
}

export interface SubsystemSide {
  is_mocked: boolean;
  /** Displayed, never compared. */
  mock_notes: string | null;
  version: string | null;
  host_shape: HostShapeEntry[];
}

export interface SubsystemComparison {
  subsystem_id: number;
  name: string;
  system_id: number;
  system_name: string;
  presence: Presence;
  left: SubsystemSide | null;
  right: SubsystemSide | null;
  differences: DifferenceKind[];
}

export interface EnvironmentComparison {
  left: ComparedEnvironment;
  right: ComparedEnvironment;
  systems: SystemPresence[];
  subsystems: SubsystemComparison[];
  summary: {
    compared: number;
    differing: number;
    by_kind: Record<DifferenceKind, number>;
  };
}
