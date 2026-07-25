import { useCallback, useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import SubsystemNode from '../../components/topology/SubsystemNode';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import TopologyCanvas from '../../components/topology/TopologyCanvas';
import { bySystem } from '../../components/topology/topologyModel';
import { fromTopologyResponse } from '../../components/topology/topologySource';
import type { AppDispatch, RootState } from '../../store';
import { fetchTopology, clearTopology } from '../../store/topologySlice';

const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2',
  cache: '#f57c00',
  message_queue: '#7b1fa2',
  web_service: '#388e3c',
  api_gateway: '#00796b',
  worker: '#e64a19',
  frontend: '#303f9f',
  other: '#616161',
};

const nodeTypes = {
  subsystemNode: SubsystemNode,
  systemGroupNode: SystemGroupNode,
  collapsedSystemNode: CollapsedSystemNode,
};

const colorFor = (t: string) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other;

interface Props {
  systemId: number;
}

export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { data, loading, error } = useSelector((state: RootState) => state.topology);

  useEffect(() => {
    dispatch(fetchTopology(systemId));
    return () => {
      dispatch(clearTopology());
    };
  }, [systemId, dispatch]);

  const source = useMemo(() => (data ? fromTopologyResponse(data) : null), [data]);
  const graph = useMemo(() => source?.getGraph() ?? null, [source]);
  const grouping = useMemo(
    () => bySystem(source?.getSystemNames() ?? {}, systemId),
    [source, systemId]
  );

  const findDependency = useCallback(
    (id: number) =>
      [...(data?.dependencies ?? []), ...(data?.external_dependencies ?? [])].find(
        (d) => d.id === id
      ) ?? null,
    [data]
  );

  return (
    <TopologyCanvas
      graph={graph}
      grouping={grouping}
      loading={loading}
      error={error}
      colorFor={colorFor}
      nodeTypes={nodeTypes}
      findDependency={findDependency}
      emptyMessage="No subsystems yet. Add subsystems to see the topology diagram."
    />
  );
}
