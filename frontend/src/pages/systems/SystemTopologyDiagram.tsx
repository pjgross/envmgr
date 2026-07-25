import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import ELK from 'elkjs/lib/elk.bundled.js';
import {
  buildElkGraph,
  elkToReactFlow,
  type ElkRenderContext,
  type RenderSubsystem,
  type RenderDependency,
} from '../../components/topology/topologyElkGraph';
import { computeFocusSet, type SearchableComponent } from '../../components/topology/topologyFocus';
import TopologyToolbar from '../../components/topology/TopologyToolbar';
import { Box, Chip, Typography, CircularProgress, Alert } from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import FloatingEdge from '../../components/topology/FloatingEdge';
import DependencyDetailPane from '../../components/topology/DependencyDetailPane';
import { fetchTopology, clearTopology } from '../../store/topologySlice';
import type { SubSystemResponse } from '../../types/system';

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

const NODE_WIDTH = 180;
const NODE_HEIGHT = 70;

// Subsystem node component
function SubsystemNode({
  data,
}: {
  data: { label: SubSystemResponse; color: string; dimmed?: boolean };
}) {
  const s = data.label;
  return (
    <Box
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px solid ${data.color}`,
        borderRadius: 1,
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: 'pointer',
        opacity: data.dimmed ? 0.25 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <Typography
        variant="body2"
        fontWeight="bold"
        noWrap
        sx={{ width: '100%', textAlign: 'center' }}
      >
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: data.color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {s.technology && (
        <Typography variant="caption" color="text.secondary" noWrap>
          {s.technology}
        </Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}

const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode };
const edgeTypes = { floating: FloatingEdge };

const elk = new ELK();

interface Props {
  systemId: number;
}

export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { data, loading, error } = useSelector((state: RootState) => state.topology);
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
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
  }, [data]);

  const selectedDep = useMemo(() => {
    if (selectedDepId === null || !data) return null;
    return (
      [...data.dependencies, ...(data.external_dependencies ?? [])].find(
        (d) => d.id === selectedDepId
      ) ?? null
    );
  }, [selectedDepId, data]);

  const [layout, setLayout] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });
  const [layingOut, setLayingOut] = useState(false);

  useEffect(() => {
    if (!data) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const graph = buildElkGraph({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.external_subsystems ?? [],
      externalDependencies: data.external_dependencies ?? [],
    });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...data.subsystems, ...(data.external_subsystems ?? [])]) subsystems.set(s.id, s);
    const dependencies = new Map<number, RenderDependency>();
    for (const d of [...data.dependencies, ...(data.external_dependencies ?? [])]) dependencies.set(d.id, d);

    const ctx: ElkRenderContext = {
      currentSystemId: systemId,
      systemNames: data.system_names ?? {},
      subsystems,
      dependencies,
      colorFor: (t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other,
    };

    elk
      .layout(graph)
      .then((res) => {
        if (cancelled) return;
        setLayout(elkToReactFlow(res, ctx));
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
  }, [data, systemId]);

  const focusSet = useMemo(() => {
    if (!focusedId || !data) return null;
    const deps = [...data.dependencies, ...(data.external_dependencies ?? [])];
    return computeFocusSet(focusedId, deps);
  }, [focusedId, data]);

  const nodes = useMemo(() => {
    if (!focusSet) return layout.nodes;
    const brightGroups = new Set<string>();
    for (const n of layout.nodes) {
      if (n.parentId && focusSet.nodeIds.has(n.id)) brightGroups.add(n.parentId);
    }
    return layout.nodes.map((n) =>
      n.type === 'systemGroupNode'
        ? { ...n, data: { ...n.data, dimmed: !brightGroups.has(n.id) } }
        : { ...n, data: { ...n.data, dimmed: !focusSet.nodeIds.has(n.id) } }
    );
  }, [layout.nodes, focusSet]);

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
    return [...data.subsystems, ...(data.external_subsystems ?? [])].map((s) => ({
      id: s.id,
      name: s.name,
      systemName: names[String(s.system_id)] ?? `System ${s.system_id}`,
    }));
  }, [data]);

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
    setSelectedDepId((prev) => (prev === id ? null : id));
  }, []);

  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    // system-group node ids are prefixed "group-" (see topologyElkGraph.ts); only components are focusable
    if (node.id.startsWith('group-')) return;
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
        <TopologyToolbar components={searchable} onSelect={handleSearchSelect} />
        <Box sx={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
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
