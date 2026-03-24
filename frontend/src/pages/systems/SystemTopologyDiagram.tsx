import { useCallback, useEffect, useMemo, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from '@dagrejs/dagre'
import { Box, Chip, Typography, CircularProgress, Alert } from '@mui/material'
import type { AppDispatch, RootState } from '../../store'
import SystemGroupNode from '../../components/topology/SystemGroupNode'
import DependencyDetailPane from '../../components/topology/DependencyDetailPane'
import { fetchTopology, clearTopology } from '../../store/topologySlice'
import type { SubSystemResponse } from '../../types/system'
import type { ComponentDependencyResponse } from '../../types/dependency'

// Color mapping by component_type
const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2',      // blue
  cache: '#f57c00',         // amber
  message_queue: '#7b1fa2', // purple
  web_service: '#388e3c',   // green
  api_gateway: '#00796b',   // teal
  worker: '#e64a19',        // orange
  frontend: '#303f9f',      // indigo
  other: '#616161',         // grey
}

const NODE_WIDTH = 180
const NODE_HEIGHT = 70
const GROUP_PADDING = 40
const GROUP_LABEL_HEIGHT = 20

// Subsystem node component
function SubsystemNode({ data }: { data: { label: SubSystemResponse; color: string } }) {
  const s = data.label
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
        cursor: 'default',
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
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
  )
}

const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode }

const GROUP_GAP = 80  // horizontal gap between system boxes

function getLayoutedElements(
  subsystems: SubSystemResponse[],
  dependencies: ComponentDependencyResponse[],
  externalSubsystems: SubSystemResponse[],
  externalDependencies: ComponentDependencyResponse[],
  systemNames: Record<string, string>,
  currentSystemId: number,
  selectedDepId: number | null,
) {
  const allSubsystems = [...subsystems, ...externalSubsystems]
  const allDependencies = [...dependencies, ...externalDependencies]

  if (allSubsystems.length === 0) return { nodes: [], edges: [] }

  // Group subsystems by system_id
  const groups = new Map<number, SubSystemResponse[]>()
  for (const s of allSubsystems) {
    if (!groups.has(s.system_id)) groups.set(s.system_id, [])
    groups.get(s.system_id)!.push(s)
  }

  // Run dagre independently for each system's subsystems using only that system's internal edges.
  // This guarantees no overlap between groups.
  interface GroupLayout {
    // node positions normalised so the content area starts at (0,0)
    nodePositions: Map<number, { x: number; y: number }>
    contentWidth: number   // right edge of rightmost node
    contentHeight: number  // bottom edge of bottommost node
  }


  const groupLayouts = new Map<number, GroupLayout>()

  for (const [sysId, subs] of groups) {
    const subIds = new Set(subs.map((s) => s.id))
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'LR', ranksep: 80, nodesep: 40 })
    g.setDefaultEdgeLabel(() => ({}))

    subs.forEach((s) => g.setNode(String(s.id), { width: NODE_WIDTH, height: NODE_HEIGHT }))
    // Only add edges internal to this system
    allDependencies.forEach((d) => {
      if (subIds.has(d.from_subsystem_id) && subIds.has(d.to_subsystem_id)) {
        g.setEdge(String(d.from_subsystem_id), String(d.to_subsystem_id))
      }
    })
    dagre.layout(g)

    // Normalise: shift so min top-left is (0,0)
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    subs.forEach((s) => {
      const pos = g.node(String(s.id))
      minX = Math.min(minX, pos.x - NODE_WIDTH / 2)
      minY = Math.min(minY, pos.y - NODE_HEIGHT / 2)
      maxX = Math.max(maxX, pos.x + NODE_WIDTH / 2)
      maxY = Math.max(maxY, pos.y + NODE_HEIGHT / 2)
    })

    const positions = new Map<number, { x: number; y: number }>()
    subs.forEach((s) => {
      const pos = g.node(String(s.id))
      positions.set(s.id, { x: pos.x - minX, y: pos.y - minY })
    })

    groupLayouts.set(sysId, {
      nodePositions: positions,
      contentWidth: maxX - minX,
      contentHeight: maxY - minY,
    })
  }

  // Place groups side by side: current system first, then external systems
  const sortedSysIds = [...groups.keys()].sort((a, b) => {
    if (a === currentSystemId) return -1
    if (b === currentSystemId) return 1
    return a - b
  })

  const groupOrigins = new Map<number, { x: number; y: number }>()
  let cursorX = 0
  for (const sysId of sortedSysIds) {
    const layout = groupLayouts.get(sysId)!
    groupOrigins.set(sysId, { x: cursorX, y: 0 })
    cursorX += layout.contentWidth + GROUP_PADDING * 2 + GROUP_GAP
  }

  // Group nodes (must appear before child nodes in array)
  const groupNodes: Node[] = sortedSysIds.map((sysId) => {
    const layout = groupLayouts.get(sysId)!
    const origin = groupOrigins.get(sysId)!
    return {
      id: `group-${sysId}`,
      type: 'systemGroupNode',
      position: { x: origin.x, y: origin.y },
      data: {
        label: systemNames[String(sysId)] ?? `System ${sysId}`,
        isCurrent: sysId === currentSystemId,
      },
      style: {
        width: layout.contentWidth + GROUP_PADDING * 2,
        height: layout.contentHeight + GROUP_PADDING * 2 + GROUP_LABEL_HEIGHT,
      },
      selectable: false,
      draggable: false,
    }
  })

  // Subsystem nodes, positions relative to parent group
  const subsystemNodes: Node[] = allSubsystems.map((s) => {
    const layout = groupLayouts.get(s.system_id)!
    const nodeCenter = layout.nodePositions.get(s.id)!
    const color = COMPONENT_COLORS[s.component_type] ?? COMPONENT_COLORS.other
    return {
      id: String(s.id),
      parentId: `group-${s.system_id}`,
      position: {
        // nodeCenter is the dagre centre; convert to top-left and add padding
        x: nodeCenter.x - NODE_WIDTH / 2 + GROUP_PADDING,
        y: nodeCenter.y - NODE_HEIGHT / 2 + GROUP_PADDING + GROUP_LABEL_HEIGHT,
      },
      data: { label: s, color },
      type: 'subsystemNode',
    }
  })

  const edges: Edge[] = allDependencies.map((d) => ({
    id: String(d.id),
    source: String(d.from_subsystem_id),
    target: String(d.to_subsystem_id),
    label: d.label ?? d.dependency_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    ...(d.direction === 'two_way' ? { markerStart: { type: MarkerType.ArrowClosed } } : {}),
    style: d.id === selectedDepId ? { stroke: '#1976d2', strokeWidth: 2.5 } : undefined,
  }))

  return { nodes: [...groupNodes, ...subsystemNodes], edges }
}

interface Props {
  systemId: number
}

export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>()
  const { data, loading, error } = useSelector((state: RootState) => state.topology)
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null)

  useEffect(() => {
    dispatch(fetchTopology(systemId))
    return () => {
      dispatch(clearTopology())
    }
  }, [systemId, dispatch])

  // Clear selection when topology data changes (e.g. system switch)
  useEffect(() => {
    setSelectedDepId(null)
  }, [data])

  const selectedDep = useMemo(() => {
    if (selectedDepId === null || !data) return null
    return [...data.dependencies, ...(data.external_dependencies ?? [])]
      .find((d) => d.id === selectedDepId) ?? null
  }, [selectedDepId, data])

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [], edges: [] }
    return getLayoutedElements(
      data.subsystems,
      data.dependencies,
      data.external_subsystems ?? [],
      data.external_dependencies ?? [],
      data.system_names ?? {},
      systemId,
      selectedDepId,
    )
  }, [data, systemId, selectedDepId])

  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    const id = parseInt(edge.id, 10)
    setSelectedDepId((prev) => (prev === id ? null : id))
  }, [])

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
  if (error) return <Alert severity="error">{error}</Alert>
  if (!data || data.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>No subsystems yet. Add subsystems to see the topology diagram.</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', height: 500, border: 1, borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}>
      {/* Diagram */}
      <Box sx={{ flex: 1, minWidth: '60%', position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          onEdgeClick={handleEdgeClick}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </Box>

      {/* Detail pane — only shown when an edge is selected */}
      {selectedDep && (
        <DependencyDetailPane
          dep={selectedDep}
          onClose={() => setSelectedDepId(null)}
        />
      )}
    </Box>
  )
}
