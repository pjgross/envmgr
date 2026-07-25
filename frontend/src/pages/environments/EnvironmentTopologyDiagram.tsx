import { useCallback, useEffect, useMemo, useState } from 'react';
import SubsystemNode from '../../components/topology/SubsystemNode';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import TopologyCanvas from '../../components/topology/TopologyCanvas';
import { colorForComponentType } from '../../components/topology/topologyColors';
import {
  fromEnvironmentTopologyResponse,
  byEnvSystem,
} from '../../components/topology/environmentTopologySource';
import { environmentService } from '../../services/environmentService';
import type { EnvironmentTopologyData } from '../../types/environment';

const nodeTypes = {
  subsystemNode: SubsystemNode,
  systemGroupNode: SystemGroupNode,
  collapsedSystemNode: CollapsedSystemNode,
};

interface Props {
  envId: number;
}

export default function EnvironmentTopologyDiagram({ envId }: Props) {
  const [data, setData] = useState<EnvironmentTopologyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    environmentService
      .getEnvironmentTopology(envId)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message ?? 'Failed to load topology');
        setLoading(false);
      });
  }, [envId]);

  const source = useMemo(() => (data ? fromEnvironmentTopologyResponse(data) : null), [data]);
  const graph = useMemo(() => source?.getGraph() ?? null, [source]);
  const envSystemIds = useMemo(
    () => new Set((data?.subsystems ?? []).map((s) => s.system_id)),
    [data],
  );
  const grouping = useMemo(
    () => byEnvSystem(source?.getSystemNames() ?? {}, envSystemIds),
    [source, envSystemIds],
  );
  const findDependency = useCallback(
    (id: number) =>
      [...(data?.dependencies ?? []), ...(data?.outside_dependencies ?? [])].find(
        (d) => d.id === id,
      ) ?? null,
    [data],
  );

  return (
    <TopologyCanvas
      graph={graph}
      grouping={grouping}
      loading={loading}
      error={error}
      colorFor={colorForComponentType}
      nodeTypes={nodeTypes}
      findDependency={findDependency}
      emptyMessage="No subsystems configured. Add systems with subsystems to see the topology."
    />
  );
}
