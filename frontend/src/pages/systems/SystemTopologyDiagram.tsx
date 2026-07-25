import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  type ElkRenderContext,
  type RenderSubsystem,
} from '../../components/topology/topologyElkGraph';
import { computeCollapseModel, bySystem } from '../../components/topology/topologyModel';
import { layoutTopology } from '../../components/topology/topologyLayout';
import SubsystemNode, { NODE_WIDTH, NODE_HEIGHT } from '../../components/topology/SubsystemNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import { computeFocusSet, type SearchableComponent } from '../../components/topology/topologyFocus';
import { computeVisibleGraph, availableComponentTypes } from '../../components/topology/topologyVisibility';
import { fromTopologyResponse } from '../../components/topology/topologySource';
import TopologyToolbar from '../../components/topology/TopologyToolbar';
import { Box, Typography, CircularProgress, Alert } from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import FloatingEdge from '../../components/topology/FloatingEdge';
import DependencyDetailPane from '../../components/topology/DependencyDetailPane';
import { fetchTopology, clearTopology } from '../../store/topologySlice';

// Color mapping by component_type
const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2', // blue
  cache: '#f57c00', // amber
  message_queue: '#7b1fa2', // purple
  web_service: '#388e3c', // green
  api_gateway: '#00796b', // teal
  worker: '#e64a19', // orange
  frontend: '#303f9f', // indigo
  other: '#616161', // grey
};

const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode, collapsedSystemNode: CollapsedSystemNode };
const edgeTypes = { floating: FloatingEdge };

interface Props {
  systemId: number;
}

export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { data, loading, error } = useSelector((state: RootState) => state.topology);
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const rfRef = useRef<ReactFlowInstance | null>(null);

  useEffect(() => {
    dispatch(fetchTopology(systemId));
    return () => {
      dispatch(clearTopology());
    };
  }, [systemId, dispatch]);

  // Clear selection when topology data changes (e.g. system switch)
  useEffect(() => {
    setSelectedDepId(null);
    setFocusedId(null);
    setCollapsedGroups(new Set());
  }, [data]);

  const selectedDep = useMemo(() => {
    if (selectedDepId === null || !data) return null;
    return (
      [...data.dependencies, ...(data.external_dependencies ?? [])].find(
        (d) => d.id === selectedDepId
      ) ?? null
    );
  }, [selectedDepId, data]);

  const source = useMemo(() => (data ? fromTopologyResponse(data) : null), [data]);

  const visibleGraph = useMemo(() => {
    if (!source) return null;
    return computeVisibleGraph(source.getGraph(), { hiddenTypes });
  }, [source, hiddenTypes]);

  const renderedComponents = useMemo(() => {
    if (!visibleGraph) return [];
    return [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems].filter(
      (s) => !collapsedGroups.has(String(s.system_id))
    );
  }, [visibleGraph, collapsedGroups]);

  const visibleIds = useMemo(
    () => (visibleGraph ? new Set(renderedComponents.map((s) => String(s.id))) : null),
    [visibleGraph, renderedComponents]
  );

  const [layout, setLayout] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });
  const [layingOut, setLayingOut] = useState(false);

  useEffect(() => {
    if (!visibleGraph || !source) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const grouping = bySystem(source.getSystemNames(), systemId);
    const model = computeCollapseModel(visibleGraph, { collapsedGroups, grouping });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems]) subsystems.set(s.id, s);

    const ctx: ElkRenderContext = {
      subsystems,
      colorFor: (t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other,
    };

    layoutTopology(model, ctx)
      .then((rf) => {
        if (!cancelled) setLayout(rf);
      })
      .catch(() => {
        if (!cancelled) setLayout({ nodes: [], edges: [] });
      })
      .finally(() => {
        if (!cancelled) setLayingOut(false);
      });

    return () => {
      cancelled = true;
    };
  }, [visibleGraph, systemId, source, collapsedGroups]);

  const focusSet = useMemo(() => {
    if (!focusedId || !visibleGraph) return null;
    const deps = [...visibleGraph.dependencies, ...visibleGraph.externalDependencies];
    return computeFocusSet(focusedId, deps);
  }, [focusedId, visibleGraph]);

  const collapseGroup = useCallback((gid: string) => {
    setCollapsedGroups((prev) => new Set(prev).add(gid));
  }, []);
  const expandGroup = useCallback((gid: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      next.delete(gid);
      return next;
    });
  }, []);

  const nodes = useMemo(() => {
    const brightGroups = new Set<string>();
    if (focusSet) {
      for (const n of layout.nodes) {
        if (n.parentId && focusSet.nodeIds.has(n.id)) brightGroups.add(n.parentId);
      }
    }
    return layout.nodes.map((n) => {
      const dimmed = focusSet
        ? n.type === 'systemGroupNode' || n.type === 'collapsedSystemNode'
          ? !brightGroups.has(n.id)
          : !focusSet.nodeIds.has(n.id)
        : undefined;
      if (n.type === 'systemGroupNode') {
        return { ...n, data: { ...n.data, dimmed, onCollapse: collapseGroup } };
      }
      if (n.type === 'collapsedSystemNode') {
        return { ...n, data: { ...n.data, dimmed, onExpand: expandGroup } };
      }
      return { ...n, data: { ...n.data, dimmed } };
    });
  }, [layout.nodes, focusSet, collapseGroup, expandGroup]);

  const edges = useMemo(
    () =>
      layout.edges.map((e) => {
        const dimmed = focusSet ? !focusSet.edgeIds.has(e.id) : false;
        const selected = Number(e.id) === selectedDepId;
        const style: React.CSSProperties = {
          opacity: dimmed ? 0.12 : 1,
          ...(selected ? { stroke: '#1976d2', strokeWidth: 2.5 } : {}),
        };
        return { ...e, style };
      }),
    [layout.edges, selectedDepId, focusSet]
  );

  const searchable = useMemo<SearchableComponent[]>(() => {
    if (!data) return [];
    const names = data.system_names ?? {};
    return renderedComponents.map((s) => ({
      id: s.id,
      name: s.name,
      systemName: names[String(s.system_id)] ?? `System ${s.system_id}`,
    }));
  }, [data, renderedComponents]);

  const availableTypes = useMemo(() => {
    if (!data) return [];
    return availableComponentTypes({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.external_subsystems ?? [],
      externalDependencies: data.external_dependencies ?? [],
    });
  }, [data]);

  const toggleType = useCallback((t: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }, []);

  useEffect(() => {
    if (focusedId && visibleIds && !visibleIds.has(focusedId)) setFocusedId(null);
  }, [focusedId, visibleIds]);

  const handleSearchSelect = useCallback(
    (id: number) => {
      setFocusedId(String(id));
      const node = layout.nodes.find((n) => n.id === String(id));
      if (node?.parentId) {
        const group = layout.nodes.find((n) => n.id === node.parentId);
        const absX = (group?.position.x ?? 0) + node.position.x;
        const absY = (group?.position.y ?? 0) + node.position.y;
        rfRef.current?.setCenter(absX + NODE_WIDTH / 2, absY + NODE_HEIGHT / 2, {
          zoom: 1.2,
          duration: 400,
        });
      }
    },
    [layout.nodes]
  );

  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    const id = parseInt(edge.id, 10);
    if (Number.isNaN(id)) return; // aggregated edge — no single dependency to show
    setSelectedDepId((prev) => (prev === id ? null : id));
  }, []);

  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    // system-group node ids are prefixed "group-", collapsed system nodes "sys-"; only components are focusable
    if (node.id.startsWith('group-') || node.id.startsWith('sys-')) return;
    setFocusedId((cur) => (cur === node.id ? null : node.id));
  }, []);

  const handlePaneClick = useCallback(() => setFocusedId(null), []);

  if (loading || (layingOut && layout.nodes.length === 0))
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data || data.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>No subsystems yet. Add subsystems to see the topology diagram.</Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        height: 500,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        overflow: 'hidden',
      }}
    >
      {/* Diagram column: search toolbar above, canvas below */}
      <Box sx={{ flex: 1, minWidth: '60%', display: 'flex', flexDirection: 'column' }}>
        <TopologyToolbar
          components={searchable}
          onSelect={handleSearchSelect}
          availableTypes={availableTypes}
          hiddenTypes={hiddenTypes}
          onToggleType={toggleType}
        />
        <Box sx={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            onlyRenderVisibleElements
            minZoom={0.1}
            maxZoom={2}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onEdgeClick={handleEdgeClick}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            onInit={(inst) => {
              rfRef.current = inst;
            }}
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </Box>
      </Box>

      {/* Detail pane — only shown when an edge is selected */}
      {selectedDep && (
        <DependencyDetailPane dep={selectedDep} onClose={() => setSelectedDepId(null)} />
      )}
    </Box>
  );
}
