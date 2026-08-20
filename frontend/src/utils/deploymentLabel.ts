import type { Deployment } from '../types/deployment';

/**
 * A one-line label identifying a deployment for a picker or a reference —
 * environment, build and date, e.g. "UAT · a1b2c3d · 14 Aug 2026". Shared
 * between `AddEvidenceDialog` (picking one) and `GateEvidenceList`
 * (naming the one an evidence row already cites) so the two never drift
 * into describing the same deployment two different ways.
 *
 * `Deployment` carries `build_sha_short`, not a component name or build
 * number — those live on `Build`/`Subsystem`, a join this label
 * deliberately does not make (it would cost a second request per row for
 * a label, not a fact anything here decides on).
 */
export function formatDeploymentLabel(d: Deployment): string {
  const env = d.environment_name ?? `env #${d.environment_id}`;
  const build = d.build_sha_short ?? `build #${d.build_id}`;
  const date = new Date(d.deployed_at).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
  return `${env} · ${build} · ${date}`;
}
