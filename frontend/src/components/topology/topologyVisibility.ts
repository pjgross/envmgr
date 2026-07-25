import type { DependencyDirection } from '../../types/dependency';

/** Minimal-but-render-sufficient subsystem shape for visibility filtering. */
export interface VisibleSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
  is_mocked?: boolean;
}

/** Minimal-but-render-sufficient dependency shape for visibility filtering. */
export interface VisibleDependency {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
  dependency_type: string;
  direction: DependencyDirection;
  label: string | null;
}

export interface VisibilityInput {
  subsystems: VisibleSubsystem[];
  dependencies: VisibleDependency[];
  externalSubsystems: VisibleSubsystem[];
  externalDependencies: VisibleDependency[];
}

export interface VisibilityOptions {
  hiddenTypes: Set<string>;
}

/** The graph after applying visibility options (same shape as the input). */
export function computeVisibleGraph(
  input: VisibilityInput,
  options: VisibilityOptions
): VisibilityInput {
  const visible = (s: VisibleSubsystem) => !options.hiddenTypes.has(s.component_type);
  const subsystems = input.subsystems.filter(visible);
  const externalSubsystems = input.externalSubsystems.filter(visible);

  const survivingIds = new Set<number>([
    ...subsystems.map((s) => s.id),
    ...externalSubsystems.map((s) => s.id),
  ]);
  const bothSurvive = (d: VisibleDependency) =>
    survivingIds.has(d.from_subsystem_id) && survivingIds.has(d.to_subsystem_id);

  return {
    subsystems,
    externalSubsystems,
    dependencies: input.dependencies.filter(bothSurvive),
    externalDependencies: input.externalDependencies.filter(bothSurvive),
  };
}

/** Distinct component_type values across all (internal + external) subsystems, sorted. */
export function availableComponentTypes(input: VisibilityInput): string[] {
  const types = new Set<string>();
  for (const s of [...input.subsystems, ...input.externalSubsystems]) types.add(s.component_type);
  return [...types].sort();
}
