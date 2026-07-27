import { useCallback, useEffect, useMemo, useState } from 'react';
import { ToggleButton, ToggleButtonGroup } from '@mui/material';
import SubsystemNode from '../../components/topology/SubsystemNode';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import TopologyCanvas from '../../components/topology/TopologyCanvas';
import { colorForComponentType } from '../../components/topology/topologyColors';
import {
  fromEnvironmentTopologyResponse,
  byEnvSystem,
  byHost,
} from '../../components/topology/environmentTopologySource';
import { buildHostGraph } from '../../components/topology/topologyHostTransform';
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
  const envSystemIds = useMemo(
    () => new Set((data?.subsystems ?? []).map((s) => s.system_id)),
    [data],
  );

  const [groupBy, setGroupBy] = useState<'system' | 'host'>('system');

  const hostGraph = useMemo(
    () => (source && groupBy === 'host' ? buildHostGraph(source.getGraph()) : null),
    [source, groupBy],
  );

  const graph = useMemo(
    () => (groupBy === 'host' ? hostGraph?.graph ?? null : source?.getGraph() ?? null),
    [groupBy, hostGraph, source],
  );

  const grouping = useMemo(
    () =>
      groupBy === 'host'
        ? byHost(hostGraph?.hostKeyById ?? new Map(), hostGraph?.hostMeta ?? new Map())
        : byEnvSystem(source?.getSystemNames() ?? {}, envSystemIds),
    [groupBy, hostGraph, source, envSystemIds],
  );

  const findDependency = useCallback(
    (id: number) => {
      const realId = groupBy === 'host' ? hostGraph?.edgeDepResolver.get(id) ?? null : id;
      if (realId === null) return null;
      return (
        [...(data?.dependencies ?? []), ...(data?.outside_dependencies ?? [])].find(
          (d) => d.id === realId,
        ) ?? null
      );
    },
    [groupBy, hostGraph, data],
  );

  const headerControls = (
    <ToggleButtonGroup
      size="small"
      exclusive
      value={groupBy}
      onChange={(_e, value: 'system' | 'host' | null) => value && setGroupBy(value)}
      aria-label="Group topology by"
    >
      <ToggleButton value="system">System</ToggleButton>
      <ToggleButton value="host">Host</ToggleButton>
    </ToggleButtonGroup>
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
      headerControls={headerControls}
      emptyMessage="No subsystems configured. Add systems with subsystems to see the topology."
    />
  );
}
