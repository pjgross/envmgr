import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Box, Typography, CircularProgress, Alert } from '@mui/material';
import { NODE_WIDTH, NODE_HEIGHT } from './SubsystemNode';
import { type ElkRenderContext, type RenderSubsystem } from './topologyElkGraph';
import { computeCollapseModel, type Grouping } from './topologyModel';
import { layoutTopology } from './topologyLayout';
import { computeFocusSet, type SearchableComponent } from './topologyFocus';
import { computeVisibleGraph, availableComponentTypes, type VisibilityInput } from './topologyVisibility';
import TopologyToolbar from './TopologyToolbar';
import FloatingEdge from './FloatingEdge';
import DependencyDetailPane from './DependencyDetailPane';
import type { ComponentDependencyResponse } from '../../types/dependency';

const edgeTypes = { floating: FloatingEdge };

export interface TopologyCanvasProps {
  graph: VisibilityInput | null;
  grouping: Grouping;
  loading: boolean;
  error: string | null;
  colorFor: (componentType: string) => string;
  nodeTypes: NodeTypes;
  findDependency: (id: number) => ComponentDependencyResponse | null;
  height?: number;
  emptyMessage?: string;
}

export default function TopologyCanvas({
  graph,
  grouping,
  loading,
  error,
  colorFor,
  nodeTypes,
  findDependency,
  height = 500,
  emptyMessage = 'No components yet.',
}: TopologyCanvasProps) {
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const rfRef = useRef<ReactFlowInstance | null>(null);

  // Reset transient state when the underlying graph changes (e.g. entity switch).
  useEffect(() => {
    setSelectedDepId(null);
    setFocusedId(null);
    setCollapsedGroups(new Set());
  }, [graph]);

  const selectedDep = useMemo(
    () => (selectedDepId === null ? null : findDependency(selectedDepId)),
    [selectedDepId, findDependency]
  );

  const visibleGraph = useMemo(() => {
    if (!graph) return null;
    return computeVisibleGraph(graph, { hiddenTypes });
  }, [graph, hiddenTypes]);

  const renderedComponents = useMemo(() => {
    if (!visibleGraph) return [];
    return [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems].filter(
      (s) => !collapsedGroups.has(grouping.keyOf(s))
    );
  }, [visibleGraph, collapsedGroups, grouping]);

  const visibleIds = useMemo(
    () => (visibleGraph ? new Set(renderedComponents.map((s) => String(s.id))) : null),
    [visibleGraph, renderedComponents]
  );

  const [layout, setLayout] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });
  const [layingOut, setLayingOut] = useState(false);

  useEffect(() => {
    if (!visibleGraph) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const model = computeCollapseModel(visibleGraph, { collapsedGroups, grouping });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems]) subsystems.set(s.id, s);

    const ctx: ElkRenderContext = { subsystems, colorFor };

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
  }, [visibleGraph, grouping, collapsedGroups, colorFor]);

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

  const searchable = useMemo<SearchableComponent[]>(
    () =>
      renderedComponents.map((s) => ({
        id: s.id,
        name: s.name,
        systemName: grouping.meta(grouping.keyOf(s)).name,
      })),
    [renderedComponents, grouping]
  );

  const availableTypes = useMemo(() => (graph ? availableComponentTypes(graph) : []), [graph]);

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
    // group node ids are prefixed "group-", collapsed group nodes "sys-"; only components are focusable
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
  if (!graph || graph.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>{emptyMessage}</Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        height,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        overflow: 'hidden',
      }}
    >
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

      {selectedDep && (
        <DependencyDetailPane dep={selectedDep} onClose={() => setSelectedDepId(null)} />
      )}
    </Box>
  );
}
