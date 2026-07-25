import { useCallback, useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import SubsystemNode from '../../components/topology/SubsystemNode';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import TopologyCanvas from '../../components/topology/TopologyCanvas';
import { colorForComponentType } from '../../components/topology/topologyColors';
import { bySystem } from '../../components/topology/topologyModel';
import { fromTopologyResponse } from '../../components/topology/topologySource';
import type { AppDispatch, RootState } from '../../store';
import { fetchTopology, clearTopology } from '../../store/topologySlice';

const nodeTypes = {
  subsystemNode: SubsystemNode,
  systemGroupNode: SystemGroupNode,
  collapsedSystemNode: CollapsedSystemNode,
};

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
      colorFor={colorForComponentType}
      nodeTypes={nodeTypes}
      findDependency={findDependency}
      emptyMessage="No subsystems yet. Add subsystems to see the topology diagram."
    />
  );
}
